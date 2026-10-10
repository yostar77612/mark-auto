"""Bounded historical market replay into the durable paper broker, never live.

Plans are persisted before submit; broker IDs make interrupted retries idempotent.
A replay is bound to one immutable strategy, dataset, broker journal and margin
policy. This is next-bar market execution, not a streaming feed, order-book
simulation, or a substitute for backtest stop/target execution.
"""
from contextlib import contextmanager
from bisect import bisect_left
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import sys

from .core import ValidationError, canonical_json, content_hash, freeze
from .data import validate_dataset
from .strategies import generate_signals, validate_strategy
from .backtest import calculate_costs


def _require_wal_runtime():
    # Older runtimes contain the WAL-reset race. Do not silently fall back.
    if sqlite3.sqlite_version_info < (3, 51, 3):
        raise ValidationError("WAL replay requires patched SQLite 3.51.3 or newer")


def _require_local_wal_path(path):
    """WAL shared memory is supported only on a verified local filesystem."""
    resolved = path.resolve()
    if sys.platform == "win32":
        import ctypes
        if str(resolved).startswith(("\\\\", "//")) or ctypes.windll.kernel32.GetDriveTypeW(str(resolved.anchor)) not in (2, 3, 6):
            raise ValidationError("WAL replay requires an available local drive")
    elif sys.platform.startswith("linux"):
        # The longest mountpoint covers nested mounts; unknown types fail closed.
        mounts = []
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            before, after = line.split(" - ", 1)
            name = before.split()[4]
            for escaped, character in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
                name = name.replace(escaped, character)
            mount = Path(name)
            if resolved.is_relative_to(mount):
                mounts.append((len(mount.parts), after.split()[0]))
        if not mounts or max(mounts)[1] not in {"ext2", "ext3", "ext4", "xfs", "btrfs", "f2fs", "tmpfs", "overlay", "zfs"}:
            raise ValidationError("WAL replay requires a verified local filesystem")
    else:
        raise ValidationError("WAL replay filesystem verification is unavailable on this platform")



class PaperReplay:
    def __init__(self, path, *, dataset, strategy, broker, margin_per_contract=None,
                 margin_version=None, margin_schedule=None, storage_profile="rollback_full"):
        if storage_profile not in ("rollback_full", "wal_full"):
            raise ValidationError("Unsupported replay storage profile")
        # All replay readers may encounter a migrated WAL database. Check before
        # opening it; raw header reads can invalidate POSIX SQLite file locks.
        _require_wal_runtime()
        _require_local_wal_path(Path(path))
        self.storage_profile = storage_profile
        self._wal_ready = False
        validate_dataset(dataset)
        validate_strategy(strategy)
        if any(key in strategy.parameters for key in ('stop_ticks', 'target_ticks')):
            raise ValidationError('Paper replay cannot execute protective stop/target rules; use the backtest engine or a supported strategy')
        if margin_schedule is None:
            if (not isinstance(margin_per_contract, Decimal) or not margin_per_contract.is_finite()
                    or margin_per_contract <= 0 or not isinstance(margin_version, str) or not margin_version.strip()):
                raise ValidationError('Explicit positive margin and version required')
        elif margin_per_contract is not None or margin_version is not None:
            raise ValidationError('Use either the pinned margin schedule or an explicit scalar margin')
        if not broker._risk_sessions or not broker._margin_schedule:
            raise ValidationError('Replay requires pinned risk sessions and an effective-dated margin schedule')
        if margin_schedule is not None and canonical_json(margin_schedule) != canonical_json(broker._margin_schedule):
            raise ValidationError('Replay margin schedule does not match pinned broker policy')
        if any(bar.contract_id != broker.instrument.contract_id for bar in dataset.bars):
            raise ValidationError('Replay contract must match paper broker; rolls unavailable')
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.dataset, self.strategy, self.broker = dataset, strategy, broker
        self.margin = margin_per_contract
        self.margin_version = margin_version
        self.policy = freeze(json.loads(canonical_json({'risk_sessions': broker._risk_sessions,
                                                        'margin_schedule': broker._margin_schedule})))
        self.policy_hash = content_hash(self.policy)
        binding = {'data': dataset.manifest['data_hash'], 'strategy': strategy,
                   'broker_journal': str(broker.path.resolve()), 'costs': broker.costs,
                   'limits': broker.limits, 'margin': margin_per_contract, 'margin_version': margin_version}
        if margin_schedule is not None:
            binding.update(replay_schema=2, broker_config=broker._config, risk_policy=self.policy)
        # Scalar callers retain their identity; their broker journal still pins
        # the complete policy. Never adopt a scalar ledger into schedule mode.
        self.binding = content_hash(binding)
        # Incomplete date coverage must fail before any replay orders are sent.
        for bar in dataset.bars:
            self._quote_policy(bar)
        starts = [b.timestamp for b in dataset.bars]
        self.targets = {}
        for signal in generate_signals(dataset.bars, strategy):
            index = bisect_left(starts, signal.timestamp)
            if index < len(starts):
                self.targets[index] = signal.target_position
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS replay (id INTEGER PRIMARY KEY, binding TEXT, cursor INTEGER, active INTEGER, plan TEXT)')
            row = db.execute('SELECT binding FROM replay WHERE id=1').fetchone()
            if row and row[0] != self.binding:
                raise ValidationError('Replay is bound to a different dataset, strategy, account configuration or margin mode. '
                                      'Preserve this workspace and its orders; reconcile existing execution before using a separate workspace.')
            if not row:
                db.execute('INSERT INTO replay VALUES (1, ?, 0, 0, NULL)', (self.binding,))
        if storage_profile == 'wal_full':
            with self._connection() as db:
                mode = db.execute('PRAGMA journal_mode=WAL').fetchone()[0]
                if mode != 'wal':
                    raise ValidationError('SQLite refused durable WAL replay storage')
            self._wal_ready = True

    @contextmanager
    def _connection(self):
        _require_wal_runtime()
        _require_local_wal_path(self.path)
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute('PRAGMA synchronous=FULL')
            if db.execute('PRAGMA synchronous').fetchone() != (2,):
                raise ValidationError('SQLite refused FULL replay durability')
            # Preserve bounded automatic checkpointing, including on runtimes
            # built with a different default. Busy checkpoints leave durable WAL.
            db.execute('PRAGMA wal_autocheckpoint=1000')
            if self._wal_ready and db.execute('PRAGMA journal_mode').fetchone() != ('wal',):
                raise ValidationError('Replay WAL storage mode changed externally')
            yield db
        finally:
            db.close()

    @contextmanager
    def _db(self, connection=None):
        if connection is not None:
            # Reuse the handle, never the transaction or a read snapshot.
            with connection:
                yield connection
        else:
            with self._connection() as db, db:
                yield db

    def snapshot(self):
        with self._db() as db:
            return self._snapshot(db)

    def _snapshot(self, db):
        row = db.execute('SELECT cursor,active,plan FROM replay WHERE id=1').fetchone()
        return {'binding': self.binding, 'cursor': row[0], 'total_bars': len(self.dataset.bars),
                'active': bool(row[1]), 'pending_plan': row[2] is not None,
                'complete': row[0] >= len(self.dataset.bars), 'mode': 'historical_synthetic_execution',
                'source_type': self.dataset.manifest['source_type'], 'live_status': 'disabled',
                'execution_scope': 'next-bar market targets; stop/target intrabar simulation excluded'}

    def start(self):
        state = self.broker.snapshot()
        if state['reconciliation_required'] or not state['account_id']:
            raise ValidationError('Reconcile paper account explicitly before starting replay')
        self.broker.set_kill_switch(False)
        with self._db() as db:
            db.execute('UPDATE replay SET active=1 WHERE id=1')
        return self.snapshot()

    def stop(self):
        self.broker.set_kill_switch(True)
        with self._db() as db:
            db.execute('UPDATE replay SET active=0 WHERE id=1')
        return self.snapshot()

    def _fault(self, point):
        """Test-only crash injection seam."""

    def _quote_policy(self, bar):
        if content_hash({'risk_sessions': self.broker._risk_sessions,
                         'margin_schedule': self.broker._margin_schedule}) != self.policy_hash:
            raise ValidationError('Replay pinned broker policy changed')
        policy = self.broker.quote_policy(bar.timestamp)
        if policy['trade_date'] != bar.trade_date:
            raise ValidationError('Replay trade date does not match pinned broker policy')
        # The broker's session trade date, not the UTC date, selects the row.
        margins = [row for row in self.policy['margin_schedule'] if row['effective_from'] <= policy['trade_date']]
        if not margins:
            raise ValidationError('Replay has no effective pinned margin policy')
        margin = max(margins, key=lambda row: row['effective_from'])
        if Decimal(policy['margin_per_contract']) != Decimal(margin['margin_per_contract']):
            raise ValidationError('Replay margin does not match pinned broker policy')
        if self.margin is not None and (Decimal(margin['margin_per_contract']) != self.margin
                                        or margin['version'] != self.margin_version):
            raise ValidationError('Replay scalar margin or version does not match pinned broker policy')
        return policy

    def step(self, *, max_bars=100):
        if type(max_bars) is not int or not 1 <= max_bars <= 1000:
            raise ValidationError('Replay batch must be 1..1000 bars')
        lock = sqlite3.connect(str(self.path) + '.lock', timeout=0)
        try:
            lock.execute('BEGIN IMMEDIATE')
            # An idle handle prevents last-close WAL checkpoints on every bar.
            # Transactions still end at every original durable boundary.
            with self._connection() as connection:
                return self._step(max_bars, connection)
        except sqlite3.OperationalError as exc:
            raise ValidationError('Replay is already active or its storage is unavailable') from exc
        finally:
            lock.rollback()
            lock.close()

    def _step(self, max_bars, connection):
        for _ in range(max_bars):
            replay = self._snapshot(connection)
            state = self.broker.snapshot()
            if not replay['active'] or replay['complete'] or state['kill_switch'] or state['reconciliation_required']:
                break
            index = replay['cursor']
            bar = self.dataset.bars[index]
            policy = self._quote_policy(bar)
            with self._db(connection) as db:
                saved = db.execute('SELECT plan FROM replay WHERE id=1').fetchone()[0]
                if saved is None:
                    plan = []
                    current = state['positions'].get(bar.contract_id, 0)
                    target = self.targets.get(index, current) if bar.volume > 0 else current
                    # Single-contract legs also split reversals into close then open.
                    for leg in range(abs(target - current)):
                        oid = content_hash([self.binding, index, leg])
                        plan.append({'client_order_id': oid, 'strategy_hash': content_hash(self.strategy),
                                     'contract_id': bar.contract_id, 'side': 'buy' if target > current else 'sell',
                                     'quantity': 1, 'order_type': 'market', 'created_at': bar.timestamp})
                    if plan:
                        db.execute('UPDATE replay SET plan=? WHERE id=1', (canonical_json(plan),))
                else:
                    plan = json.loads(saved)
                if not plan:
                    # The empty decision and consumed cursor are one durable
                    # write. A restart must not reinterpret an already-satisfied
                    # target after the account changes, nor persist [] first.
                    db.execute('UPDATE replay SET cursor=cursor+1,plan=NULL WHERE id=1')
            if not plan:
                self._fault('after_empty_cursor')
                continue
            self._fault('after_plan_before_submit')
            for intent in plan:
                state = self.broker.snapshot()
                if state['kill_switch'] or state['reconciliation_required']:
                    return self._snapshot(connection)
                policy = self._quote_policy(bar)
                quote = {'account_id': state['account_id'], 'contract_id': bar.contract_id,
                         'timestamp': bar.timestamp, 'price': bar.open, **policy}
                order = self.broker.submit(intent, quote=quote, now=bar.timestamp)
                self._fault('after_submit_before_fill')
                if order['status'] in ('accepted', 'filled'):
                    price = bar.open + (1 if intent['side'] == 'buy' else -1) * self.broker.costs.slippage_ticks
                    commission, tax = calculate_costs(price, 1, self.broker.costs)
                    oid = intent['client_order_id']
                    self.broker.apply_event({'event_id': oid + ':fill', 'fill_id': oid + ':fill',
                                             'order_id': oid, 'sequence': 1, 'type': 'fill', 'timestamp': bar.timestamp,
                                             'quantity': 1, 'price': price, 'commission': commission, 'tax': tax})
                    self._fault('after_fill_before_cursor')
                elif order['status'] not in ('rejected', 'cancelled'):
                    raise ValidationError('Replay order is unresolved; reconcile before retry')
            with self._db(connection) as db:
                db.execute('UPDATE replay SET cursor=cursor+1,plan=NULL WHERE id=1')
        return self._snapshot(connection)
