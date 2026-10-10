"""Offline, synthetic paper journal. This is not a broker integration.

Fresh accounts are explicitly funded with reconcile({account_id, cash,
positions: {}, orders: {}, fills: {}}). Later reconciliation must match those
five fields from snapshot(); unknown orders additionally require an explicit
order_statuses mapping to accepted/partial/filled/cancelled/rejected.
Quote schema: account_id, contract_id, timestamp, price, trade_date,
session_open, session_end, margin_per_contract. All timestamps are UTC and
session intervals must match the constructor-pinned risk_sessions. Margin must
match constructor-pinned effective-dated margin_schedule. Missing policy blocks
all new orders. quote_policy(timestamp) supplies the pinned quote fields. Optional session opening_reference={price,known_at,version} pins a daily
equity baseline for carried positions; missing reference blocks new-day intents.
Margin is an explicit synthetic assumption, not a verified historical schedule.
submit journals an intent and ACK; it never manufactures a fill. apply_event
accepts event_id, order_id, sequence (starting at 1), type and timestamp.
Fills also require fill_id, quantity, price, commission and tax. Rejected or
quarantined payloads remain in the journal. No network or credential access.
Consecutive losses count fully closed FIFO entry-fill lots net of allocated
entry/exit costs; partial closes accumulate, zero/profit breaks the streak.
The configured loss threshold latches permanently for this journal, including
a streak reached before later pending wins; restart/reconcile never clears it.
Order frequency counts persisted accepted intent reservations in (now-window,now],
including interrupted submissions, excluding rejects, exact retries, cancels and reads.
Default limits: 3 consecutive losses, 20 orders per 60 seconds.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, InvalidOperation, localcontext, ROUND_HALF_EVEN, Context
import json
from pathlib import Path
import sqlite3
from typing import Any

from .core import Instrument, CostSpec, ValidationError, canonical_json, content_hash, freeze


class JournalConflict(ValidationError):
    """An identity was reused with different content."""


class ReconciliationError(ValidationError):
    """External state differs; local state is never silently overwritten."""


class LiveTradingDisabled(RuntimeError):
    pass


def _integer(value, name, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValidationError(f'{name} must be an integer >= {minimum}')
    return value


def _money(value, name, *, positive=False):
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise ValidationError(f'{name} must be a finite decimal string or Decimal')
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValidationError(f'invalid {name}') from None
    if not result.is_finite() or result < 0 or (positive and not result):
        raise ValidationError(f'{name} must be finite and nonnegative')
    return result


def _time(value, name='timestamp'):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            raise ValidationError(f'invalid {name}') from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValidationError(f'{name} must be timezone-aware UTC')
    return value


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValidationError(f'{name} must be a nonempty string of at most 256 characters')
    return value


def _json(value):
    return json.loads(canonical_json(value))


@dataclass(frozen=True)
class RiskLimits:
    max_position: int
    max_order_quantity: int
    max_daily_loss: Decimal
    max_quote_age_seconds: int
    max_consecutive_losses: int = 3
    max_orders_per_window: int = 20
    window_seconds: int = 60

    def __post_init__(self):
        _integer(self.max_position, 'max_position', minimum=1)
        _integer(self.max_order_quantity, 'max_order_quantity', minimum=1)
        _money(self.max_daily_loss, 'max_daily_loss', positive=True)
        _integer(self.max_quote_age_seconds, 'max_quote_age_seconds', minimum=1)
        for name, maximum in (('max_consecutive_losses',1000), ('max_orders_per_window',10000), ('window_seconds',86400)):
            value = _integer(getattr(self,name), name, minimum=1)
            if value > maximum:
                raise ValidationError(f'{name} exceeds bounded maximum {maximum}')


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str


def _initial():
    return dict(account_id=None, cash='0', positions={}, orders={}, fills={},
                lots=[], round_trips=[], consecutive_losses=0, max_consecutive_losses_observed=0, consecutive_loss_halt=False, order_send_timestamps=[], daily_pnl={}, daily_equity_baselines={}, kill_switch=False, reconciliation_required=True,
                quarantined={}, last_timestamp=None, last_mark_price=None, last_mark_timestamp=None, verification='synthetic_paper_only', real_broker='not_verified')


def _reduce(state, op, payload):
    """Pure journal replay, independently recomputing balances from fills."""
    s = deepcopy(state)
    if op == 'initialize':
        s['account_id'], s['cash'] = payload['account_id'], payload['cash']
        s['reconciliation_required'] = False
    elif op in ('intent', 'risk_reject'):
        oid = payload['intent']['client_order_id']
        s['orders'][oid] = dict(intent=payload['intent'], status='submitting', filled_quantity=0,
                                sequence=0, trade_date=payload.get('trade_date'),
                                session_open=payload.get('session_open'), session_end=payload.get('session_end'),
                                last_event_timestamp=None)
        if op == 'intent':
            cutoff = _time(payload['now']) - timedelta(seconds=payload['window_seconds'])
            s['order_send_timestamps'] = [stamp for stamp in s['order_send_timestamps'] if _time(stamp) > cutoff]
            s['order_send_timestamps'].append(payload['now'])
            s['last_mark_price'], s['last_mark_timestamp'] = payload['quote']['price'], payload['now']
        if op == 'risk_reject':
            s['orders'][oid]['status'] = 'rejected'
            s['orders'][oid]['reason'] = payload['reason']
    elif op == 'ack':
        order = s['orders'][payload['order_id']]
        if order['status'] == 'submitting':
            order['status'] = 'accepted'
    elif op == 'cancel_request':
        order = s['orders'][payload['order_id']]
        order['cancel_requested'] = True
        if order['status'] not in ('filled', 'cancelled', 'rejected', 'unknown', 'submitting'):
            order['status'] = 'cancel_pending'
    elif op == 'event':
        e = payload
        order = s['orders'][e['order_id']]
        order['sequence'] = e['sequence']
        order['last_event_timestamp'] = e['timestamp']
        typ = e['type']
        if typ == 'unknown':
            order['status'] = 'unknown'
            s['reconciliation_required'] = True
        elif typ == 'ack':
            if order['status'] == 'submitting':
                order['status'] = 'accepted'
                s['reconciliation_required'] = True
        elif typ in ('cancel', 'reject'):
            if order['status'] != 'filled':
                order['status'] = 'cancelled' if typ == 'cancel' else 'rejected'
        elif typ == 'fill':
            s['last_mark_price'], s['last_mark_timestamp'] = e['price'], e['timestamp']
            intent = order['intent']
            direction = 1 if intent['side'] == 'buy' else -1
            remaining, realized = e['quantity'], Decimal('0')
            price, multiplier = Decimal(e['price']), Decimal(e['multiplier'])
            expense = Decimal(e['commission']) + Decimal(e['tax'])
            expense_remaining = expense
            for lot in s['lots']:
                if remaining and lot['quantity'] and lot['direction'] != direction:
                    matched = min(remaining, lot['quantity'])
                    gross = (price - Decimal(lot['price'])) * lot['direction'] * matched * multiplier
                    realized += gross
                    lot['gross_realized'] = str(Decimal(lot['gross_realized']) + gross)
                    allocated = expense_remaining if matched == remaining else expense * matched / e['quantity']
                    expense_remaining -= allocated
                    lot['exit_cost'] = str(Decimal(lot['exit_cost']) + allocated)
                    remaining -= matched
                    lot['quantity'] -= matched
                    if not lot['quantity']:
                        lot_net = Decimal(lot['gross_realized']) - Decimal(lot['entry_cost']) - Decimal(lot['exit_cost'])
                        s['round_trips'].append(dict(entry_fill_id=lot['entry_fill_id'], exit_fill_id=e['fill_id'],
                            quantity=lot['original_quantity'], gross_pnl=lot['gross_realized'], entry_cost=lot['entry_cost'],
                            exit_cost=lot['exit_cost'], net_pnl=str(lot_net), timestamp=e['timestamp']))
                        s['consecutive_losses'] = s['consecutive_losses'] + 1 if lot_net < 0 else 0
                        s['max_consecutive_losses_observed'] = max(s['max_consecutive_losses_observed'], s['consecutive_losses'])
            s['lots'] = [lot for lot in s['lots'] if lot['quantity']]
            if remaining:
                s['lots'].append(dict(quantity=remaining, original_quantity=remaining, direction=direction, price=e['price'], entry_trade_date=order['trade_date'],
                                      entry_fill_id=e['fill_id'], entry_cost=str(expense_remaining), gross_realized='0', exit_cost='0'))
            net = realized - Decimal(e['commission']) - Decimal(e['tax'])
            s['cash'] = str(Decimal(s['cash']) + net)
            day = order['trade_date']
            s['daily_pnl'][day] = str(Decimal(s['daily_pnl'].get(day, '0')) + net)
            position = s['positions'].get(intent['contract_id'], 0) + direction * e['quantity']
            if position:
                s['positions'][intent['contract_id']] = position
            else:
                s['positions'].pop(intent['contract_id'], None)
            s['fills'][e['fill_id']] = e
            order['filled_quantity'] += e['quantity']
            if order['filled_quantity'] == intent['quantity']:
                order['status'] = 'filled'
            elif order['status'] not in ('cancelled', 'cancel_pending', 'unknown'):
                order['status'] = 'partial'
    elif op == 'quarantine':
        s['quarantined'][payload['event_id']] = payload
        s['reconciliation_required'] = True
    elif op == 'daily_baseline':
        s['daily_equity_baselines'][payload['trade_date']] = payload
    elif op == 'consecutive_loss_halt':
        s['consecutive_loss_halt'] = True
    elif op == 'risk_breach':
        s['reconciliation_required'] = True
    elif op == 'reconcile_failure':
        s['reconciliation_required'] = True
    elif op == 'restart':
        s['reconciliation_required'] = True
        for order in s['orders'].values():
            if order['status'] == 'submitting':
                order['status'] = 'unknown'
    elif op == 'kill':
        s['kill_switch'] = payload['active']
    elif op == 'reconcile':
        for oid, status in payload.get('order_statuses', {}).items():
            s['orders'][oid]['status'] = status
        s['reconciliation_required'] = False
    else:
        raise JournalConflict('unknown journal operation')
    stamp = payload.get('timestamp') if op == 'event' else payload.get('now') if op in ('intent', 'cancel_request', 'daily_baseline') else None
    if stamp is not None:
        s['last_timestamp'] = stamp
    return s


class PaperBroker:
    def __init__(self, journal_path: Path, *, instrument: Instrument, costs: CostSpec, limits: RiskLimits,
                 risk_sessions=(), margin_schedule=()):
        self.instrument, self.costs, self.limits = instrument, costs, limits
        # Canonical copies sever all aliases; persisted config detects policy changes.
        self._risk_sessions = freeze(_json(risk_sessions))
        self._margin_schedule = freeze(_json(margin_schedule))
        self._validate_policy()
        self.path = Path(journal_path)
        self._storage_uncertain = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._config = content_hash(dict(journal_schema=4, instrument=instrument, costs=costs, limits=limits,
                                         risk_sessions=self._risk_sessions, margin_schedule=self._margin_schedule))
        with self._transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS journal (seq INTEGER PRIMARY KEY AUTOINCREMENT, identity TEXT UNIQUE NOT NULL, operation TEXT NOT NULL, payload TEXT NOT NULL, state_hash TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS materialized (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL)')
            old = db.execute("SELECT value FROM metadata WHERE key='config'").fetchone()
            if old and old[0] != self._config:
                raise JournalConflict('journal instrument/cost/risk configuration mismatch')
            if not old:
                db.execute("INSERT INTO metadata VALUES ('config', ?)", (self._config,))
                db.execute('INSERT INTO materialized VALUES (1, ?)', (canonical_json(_initial()),))
            state = self._restore(db)
            if old:
                self._append(db, state, 'restart', {}, self._next_id(db, 'restart'))

    def _validate_policy(self):
        if not isinstance(self._risk_sessions, list) or not isinstance(self._margin_schedule, list):
            raise ValidationError('Risk sessions and margin schedule must be sequences')
        previous = None
        for row in sorted(self._risk_sessions, key=lambda r: r.get('open', '')):
            required = {'open', 'end', 'trade_date', 'source', 'session'}
            if not isinstance(row, dict) or not required <= row.keys() or row.keys() - required - {'contract_id', 'opening_reference'}:
                raise ValidationError('Explicit bounded risk session required')
            opening, closing = _time(row['open']), _time(row['end'])
            if opening >= closing or (previous is not None and opening < previous):
                raise ValidationError('Overlapping or invalid risk sessions')
            previous = closing
            if row.get('contract_id', self.instrument.contract_id) != self.instrument.contract_id:
                raise ValidationError('Risk session contract mismatch')
            if row['session'] not in ('day', 'night') or not isinstance(row['source'], str) or not row['source']:
                raise ValidationError('Risk session needs source and day/night classification')
            try:
                if date.fromisoformat(row['trade_date']).isoformat() != row['trade_date']:
                    raise ValueError()
            except (TypeError, ValueError):
                raise ValidationError('Risk session trade_date must be ISO date') from None
        for day in {r['trade_date'] for r in self._risk_sessions}:
            rows = [r for r in self._risk_sessions if r['trade_date'] == day]
            earliest = min(_time(r['open']) for r in rows)
            references = [r['opening_reference'] for r in rows if 'opening_reference' in r]
            for reference in references:
                if not isinstance(reference, dict) or set(reference) != {'price', 'known_at', 'version'}:
                    raise ValidationError('Opening reference requires price, known_at and version')
                _money(reference['price'], 'opening reference price', positive=True)
                _text(reference['version'], 'opening reference version')
                if _time(reference['known_at']) > earliest:
                    raise ValidationError('Opening reference must be known by first trade-date session open')
            if references and any(reference != references[0] for reference in references):
                raise ValidationError('Conflicting trade-date opening references')
        dates = set()
        for row in self._margin_schedule:
            if not isinstance(row, dict) or set(row) != {'effective_from', 'margin_per_contract', 'version'}:
                raise ValidationError('Explicit effective-dated margin policy required')
            try:
                if date.fromisoformat(row['effective_from']).isoformat() != row['effective_from']:
                    raise ValueError()
            except (TypeError, ValueError):
                raise ValidationError('Margin effective_from must be ISO date') from None
            if row['effective_from'] in dates:
                raise ValidationError('Duplicate margin effective date')
            dates.add(row['effective_from'])
            _money(row['margin_per_contract'], 'margin_per_contract', positive=True)
            _text(row['version'], 'margin version')

    def quote_policy(self, timestamp):
        """Return the pinned synthetic session and margin assumptions for a quote."""
        stamp = _time(timestamp)
        rows = [r for r in self._risk_sessions if _time(r['open']) <= stamp < _time(r['end'])]
        if len(rows) != 1:
            raise ValidationError('timestamp outside pinned risk sessions')
        row = rows[0]
        margins = [r for r in self._margin_schedule if r['effective_from'] <= row['trade_date']]
        if not margins:
            raise ValidationError('no effective pinned margin policy')
        margin = max(margins, key=lambda r: r['effective_from'])
        return dict(trade_date=row['trade_date'], session_open=row['open'], session_end=row['end'],
                    margin_per_contract=margin['margin_per_contract'])

    @contextmanager
    def _transaction(self):
        with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
            try:
                db = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
            except sqlite3.Error:
                self._storage_uncertain = True
                raise
            was_uncertain = self._storage_uncertain
            try:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('BEGIN IMMEDIATE')
                yield db
                db.commit()
            except BaseException as exc:
                if was_uncertain or isinstance(exc, sqlite3.Error):
                    # Storage may have lost an inbound event or an ACK. Once
                    # storage returns, durably latch reconciliation before use.
                    self._storage_uncertain = True
                db.rollback()
                raise
            finally:
                db.close()

    def _fault(self, point):
        """Fault-injection seam; never used to simulate a real broker."""

    def _next_id(self, db, label):
        seq = db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM journal').fetchone()[0]
        return f'{label}:{seq}'

    def _restore(self, db):
        state = _initial()
        for operation, payload, expected in db.execute('SELECT operation,payload,state_hash FROM journal ORDER BY seq'):
            state = _reduce(state, operation, json.loads(payload))
            if content_hash(state) != expected:
                raise JournalConflict('journal replay checksum mismatch')
        saved = db.execute('SELECT state FROM materialized WHERE id=1').fetchone()
        if not saved or canonical_json(state) != saved[0]:
            raise JournalConflict('materialized snapshot disagrees with journal replay')
        if self._storage_uncertain:
            state = self._append(db, state, 'reconcile_failure',
                                 {'reason': 'storage failure; explicit reconciliation required'},
                                 self._next_id(db, 'storage_recovery'))
            self._storage_uncertain = False
        return state

    def _append(self, db, state, operation, payload, identity):
        payload = _json(payload)
        old = db.execute('SELECT operation,payload FROM journal WHERE identity=?', (identity,)).fetchone()
        if old:
            if old != (operation, canonical_json(payload)):
                raise JournalConflict('mismatched duplicate identity')
            return state
        state = _reduce(state, operation, payload)
        db.execute('INSERT INTO journal(identity,operation,payload,state_hash) VALUES (?,?,?,?)',
                   (identity, operation, canonical_json(payload), content_hash(state)))
        db.execute('UPDATE materialized SET state=? WHERE id=1', (canonical_json(state),))
        return state

    def snapshot(self):
        with self._transaction() as db:
            return self._restore(db)

    def journal_events(self):
        """Ordered, read-only journal records for audit UI (synthetic data only)."""
        with self._transaction() as db:
            self._restore(db)
            return [dict(sequence=row[0], identity=row[1], operation=row[2], payload=json.loads(row[3]), state_hash=row[4])
                    for row in db.execute('SELECT seq,identity,operation,payload,state_hash FROM journal ORDER BY seq')]

    def _intent(self, intent):
        required = {'client_order_id', 'strategy_hash', 'contract_id', 'side', 'quantity', 'order_type', 'created_at'}
        if not isinstance(intent, dict) or not required <= intent.keys() or intent.keys() - required - {'limit_price'}:
            raise ValidationError('invalid intent fields')
        for name in ('client_order_id', 'strategy_hash', 'contract_id'):
            _text(intent[name], name)
        _integer(intent['quantity'], 'quantity', minimum=1)
        _time(intent['created_at'], 'created_at')
        if intent['side'] not in ('buy', 'sell') or intent['order_type'] not in ('market', 'limit'):
            raise ValidationError('unsupported side/order_type')
        if intent['order_type'] == 'limit':
            self._price(intent.get('limit_price'))
        elif 'limit_price' in intent:
            raise ValidationError('market intent cannot contain limit_price')
        return _json(intent)

    def _price(self, value):
        price = _money(value, 'price', positive=True)
        if price != price.to_integral_value():
            raise ValidationError('price is not an integral tick')
        return price

    def _risk(self, state, intent, quote, now):
        if state['reconciliation_required'] or any(o['status'] in ('unknown', 'submitting') for o in state['orders'].values()):
            return RiskDecision(False, 'reconciliation_required')
        if state['kill_switch']:
            return RiskDecision(False, 'kill_switch')
        if state['consecutive_loss_halt']:
            return RiskDecision(False, 'max_consecutive_losses')
        if not state['account_id'] or quote.get('account_id') != state['account_id']:
            return RiskDecision(False, 'account_mismatch')
        if intent['contract_id'] != self.instrument.contract_id or quote.get('contract_id') != intent['contract_id']:
            return RiskDecision(False, 'instrument_mismatch')
        if not self._risk_sessions or not self._margin_schedule:
            return RiskDecision(False, 'missing_risk_policy')
        if state['last_timestamp'] and now < _time(state['last_timestamp']):
            return RiskDecision(False, 'time_regression')
        cutoff = now - timedelta(seconds=self.limits.window_seconds)
        if sum(_time(stamp) > cutoff for stamp in state['order_send_timestamps']) >= self.limits.max_orders_per_window:
            return RiskDecision(False, 'max_orders_per_window')
        stamp = _time(quote.get('timestamp'))
        if stamp > now or (now - stamp).total_seconds() > self.limits.max_quote_age_seconds:
            return RiskDecision(False, 'stale_or_future_quote')
        if _time(intent['created_at']) > now:
            return RiskDecision(False, 'future_intent')
        opening, closing = _time(quote.get('session_open')), _time(quote.get('session_end'))
        if not opening <= stamp <= now < closing:
            return RiskDecision(False, 'outside_session')
        try:
            policy = self.quote_policy(now)
        except ValidationError:
            return RiskDecision(False, 'outside_pinned_session')
        if (_time(policy['session_open']) != opening or _time(policy['session_end']) != closing
                or quote.get('trade_date') != policy['trade_date']
                or _money(quote.get('margin_per_contract'), 'margin_per_contract', positive=True) != Decimal(policy['margin_per_contract'])):
            return RiskDecision(False, 'risk_policy_mismatch')
        day = policy['trade_date']
        try:
            if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
                raise ValueError
        except ValueError:
            raise ValidationError('trade_date must be ISO date') from None
        if self.instrument.expiry and day > self.instrument.expiry:
            return RiskDecision(False, 'expired_instrument')
        if day < self.costs.effective_from:
            return RiskDecision(False, 'cost_schedule_not_effective')
        if day not in state['daily_equity_baselines']:
            return RiskDecision(False, 'overnight_daily_loss_baseline_required')
        price = self._price(quote.get('price'))
        margin = _money(quote.get('margin_per_contract'), 'margin_per_contract', positive=True)
        quantity = intent['quantity']
        if quantity > self.limits.max_order_quantity:
            return RiskDecision(False, 'max_order_quantity')
        position = state['positions'].get(intent['contract_id'], 0)
        buy, sell = (quantity, 0) if intent['side'] == 'buy' else (0, quantity)
        for order in state['orders'].values():
            if order['status'] not in ('filled', 'cancelled', 'rejected'):
                remainder = order['intent']['quantity'] - order['filled_quantity']
                if order['intent']['side'] == 'buy':
                    buy += remainder
                else:
                    sell += remainder
        worst = max(abs(position + buy), abs(position - sell), abs(position))
        if worst > self.limits.max_position:
            return RiskDecision(False, 'max_position')
        unrealized = sum(((price - Decimal(lot['price'])) * lot['quantity'] * lot['direction'] * self.instrument.multiplier for lot in state['lots']), Decimal('0'))
        pnl = Decimal(state['cash']) + unrealized - Decimal(state['daily_equity_baselines'][day]['equity'])
        if pnl <= -Decimal(self.limits.max_daily_loss):
            return RiskDecision(False, 'max_daily_loss')
        expected_cost = (self.costs.commission_per_side + price * self.instrument.multiplier * self.costs.tax_rate) * (buy + sell)
        if Decimal(state['cash']) + min(unrealized, Decimal('0')) < worst * margin + expected_cost:
            return RiskDecision(False, 'insufficient_cash_or_margin')
        return RiskDecision(True, 'allowed')

    def _daily_baseline(self, state, quote, now):
        if state['reconciliation_required'] or state['kill_switch'] or quote.get('account_id') != state['account_id']:
            return None
        if state['last_timestamp'] and now < _time(state['last_timestamp']):
            return None
        try:
            policy = self.quote_policy(now)
        except ValidationError:
            return None
        day = policy['trade_date']
        if day in state['daily_equity_baselines'] or quote.get('trade_date') != day:
            return None
        baseline = Decimal(state['cash'])
        reference = None
        if state['lots']:
            references = [r['opening_reference'] for r in self._risk_sessions
                          if r['trade_date'] == day and 'opening_reference' in r]
            if not references:
                return None
            reference = references[0]
            mark = Decimal(reference['price'])
            baseline += sum(((mark-Decimal(lot['price'])) * lot['quantity'] * lot['direction'] * self.instrument.multiplier
                             for lot in state['lots']), Decimal('0'))
        return dict(trade_date=day, equity=str(baseline), reference=reference, now=now,
                    method='pinned_opening_reference' if reference else 'flat_opening_cash')

    def _worst_exposure(self, state):
        position = state['positions'].get(self.instrument.contract_id, 0)
        buy = sell = 0
        for order in state['orders'].values():
            if order['status'] not in ('filled', 'cancelled', 'rejected'):
                remaining = order['intent']['quantity'] - order['filled_quantity']
                if order['intent']['side'] == 'buy':
                    buy += remaining
                else:
                    sell += remaining
        return max(abs(position), abs(position + buy), abs(position - sell))

    def _capacity_breach(self, state):
        exposure = self._worst_exposure(state)
        if exposure > self.limits.max_position or Decimal(state['cash']) < 0:
            return True
        if not exposure:
            return False
        if state['last_mark_price'] is None or state['last_mark_timestamp'] is None:
            return True
        policy = self.quote_policy(state['last_mark_timestamp'])
        mark = Decimal(state['last_mark_price'])
        unrealized = sum(((mark-Decimal(lot['price'])) * lot['quantity'] * lot['direction'] * self.instrument.multiplier
                          for lot in state['lots']), Decimal('0'))
        available = Decimal(state['cash']) + min(unrealized, Decimal('0'))
        return available < exposure * Decimal(policy['margin_per_contract'])

    def submit(self, intent: dict, *, quote: dict, now: datetime):
        now, intent = _time(now, 'now'), self._intent(intent)
        if not isinstance(quote, dict):
            raise ValidationError('quote must be an object')
        oid = intent['client_order_id']
        with self._transaction() as db:
            state = self._restore(db)
            if oid in state['orders']:
                if state['orders'][oid]['intent'] != intent:
                    raise JournalConflict('client_order_id reused with different intent')
                return deepcopy(state['orders'][oid])
            baseline = self._daily_baseline(state, quote, now)
            if baseline is not None:
                state = self._append(db, state, 'daily_baseline', baseline, 'daily_baseline:' + baseline['trade_date'])
            decision = self._risk(state, intent, quote, now)
            if not decision.allowed:
                state = self._append(db, state, 'risk_reject', {'intent': intent, 'reason': decision.reason, 'quote': quote, 'now': now}, 'intent:' + oid)
                return deepcopy(state['orders'][oid])
            state = self._append(db, state, 'intent', dict(intent=intent, trade_date=quote['trade_date'], session_open=quote['session_open'], session_end=quote['session_end'], quote=quote, now=now, window_seconds=self.limits.window_seconds), 'intent:' + oid)
            self._fault('before_intent_commit')
        self._fault('after_intent_commit')
        with self._transaction() as db:
            state = self._restore(db)
            state = self._append(db, state, 'ack', {'order_id': oid}, 'ack:' + oid)
            self._fault('before_ack_commit')
        self._fault('after_ack_commit')
        return deepcopy(state['orders'][oid])

    def cancel(self, order_id: str, *, now: datetime):
        now = _time(now, 'now')
        with self._transaction() as db:
            state = self._restore(db)
            if state['last_timestamp'] and now < _time(state['last_timestamp']):
                raise ValidationError('cancel timestamp regression')
            if order_id not in state['orders']:
                raise ValidationError('unknown order')
            if state['orders'][order_id].get('cancel_requested'):
                return deepcopy(state['orders'][order_id])
            state = self._append(db, state, 'cancel_request', {'order_id': order_id, 'now': now}, 'cancel_request:' + order_id)
            return deepcopy(state['orders'][order_id])

    def apply_event(self, event: dict):
        try:
            return self._apply_event(event)
        except ValidationError as exc:
            # Invalid inbound execution data is uncertainty, not a harmless input
            # typo. Commit a separate diagnostic after the failed transaction has
            # rolled back, then preserve the original API exception for callers.
            try:
                rejected = _json(event)
            except (TypeError, ValueError):
                rejected = {'unserializable_type': type(event).__name__}
            with self._transaction() as db:
                state = self._restore(db)
                identity = self._next_id(db, 'invalid_event')
                self._append(db, state, 'quarantine',
                             {'event_id': identity, 'reason': str(exc), 'rejected_payload': rejected}, identity)
            raise

    def _apply_event(self, event: dict):
        if not isinstance(event, dict):
            raise ValidationError('event must be an object')
        event = deepcopy(event)
        required = {'event_id', 'order_id', 'sequence', 'type', 'timestamp'}
        if not required <= event.keys():
            raise ValidationError('missing event fields')
        for key in ('event_id', 'order_id'):
            _text(event[key], key)
        _time(event['timestamp'])
        _integer(event['sequence'], 'sequence', minimum=1)
        if event['type'] not in ('ack', 'fill', 'cancel', 'reject', 'unknown'):
            raise ValidationError('unknown event type')
        permitted = required | ({'fill_id', 'quantity', 'price', 'commission', 'tax'} if event['type'] == 'fill' else {'reason'})
        if event.keys() - permitted:
            raise ValidationError('unknown event fields')
        if event['type'] == 'fill':
            for key in ('fill_id', 'quantity', 'price', 'commission', 'tax'):
                if key not in event:
                    raise ValidationError('missing fill fields')
            _text(event['fill_id'], 'fill_id')
            _integer(event['quantity'], 'quantity', minimum=1)
            self._price(event['price'])
            _money(event['commission'], 'commission')
            _money(event['tax'], 'tax')
            event['multiplier'] = self.instrument.multiplier
        event = _json(event)
        identity = 'event:' + event['event_id']
        with self._transaction() as db:
            state = self._restore(db)
            old = db.execute('SELECT payload FROM journal WHERE identity=?', (identity,)).fetchone()
            if old:
                if old[0] != canonical_json(event):
                    raise JournalConflict('event_id reused with different payload')
                return {'status': 'duplicate', 'event_id': event['event_id']}
            order = state['orders'].get(event['order_id'])
            invalid = not order or event['sequence'] != order['sequence'] + 1
            if order and _time(event['timestamp']) < _time(order['intent']['created_at']):
                invalid = True
            if state['last_timestamp'] and _time(event['timestamp']) < _time(state['last_timestamp']):
                invalid = True
            if order and order.get('last_event_timestamp') and _time(event['timestamp']) < _time(order['last_event_timestamp']):
                invalid = True
            if order and event['type'] == 'fill':
                if not order.get('session_open') or not order.get('session_end') or not (_time(order['session_open']) <= _time(event['timestamp']) < _time(order['session_end'])):
                    invalid = True
                invalid = invalid or event['fill_id'] in state['fills'] or order['status'] == 'rejected'
                invalid = invalid or order['filled_quantity'] + event['quantity'] > order['intent']['quantity']
                limit = order['intent'].get('limit_price')
                if limit:
                    price, limit = Decimal(event['price']), Decimal(limit)
                    invalid = invalid or (price > limit if order['intent']['side'] == 'buy' else price < limit)
            if order and event['type'] == 'reject' and order['filled_quantity']:
                invalid = True
            operation = 'quarantine' if invalid else 'event'
            state = self._append(db, state, operation, event, identity)
            if operation == 'event' and event['type'] == 'fill' and self._capacity_breach(state):
                state = self._append(db, state, 'risk_breach',
                                     {'event_id': event['event_id'], 'reason': 'post_fill_exposure_or_margin_breach'}, identity + ':risk_breach')
            if operation == 'event' and event['type'] == 'fill' and not state['consecutive_loss_halt'] and state['max_consecutive_losses_observed'] >= self.limits.max_consecutive_losses:
                state = self._append(db, state, 'consecutive_loss_halt',
                                     {'event_id':event['event_id'], 'observed':state['max_consecutive_losses_observed'], 'limit':self.limits.max_consecutive_losses}, identity + ':loss_halt')
            self._fault('before_event_commit')
        self._fault('after_event_commit')
        return {'status': 'quarantined' if invalid else 'applied', 'event_id': event['event_id']}

    def reconcile(self, snapshot: dict):
        if not isinstance(snapshot, dict):
            raise ReconciliationError('snapshot must be an object')
        required = ('account_id', 'cash', 'positions', 'orders', 'fills')
        error = None
        with self._transaction() as db:
            state = self._restore(db)
            try:
                if any(key not in snapshot for key in required):
                    raise ReconciliationError('complete orders/fills/positions/cash/account snapshot required')
                if state['account_id'] is None:
                    _text(snapshot['account_id'], 'account_id')
                    cash = _money(snapshot['cash'], 'cash', positive=True)
                    if any(snapshot[key] != {} for key in ('positions', 'orders', 'fills')):
                        raise ReconciliationError('fresh paper accounts must have no orders, fills or positions')
                    state = self._append(db, state, 'initialize', dict(account_id=snapshot['account_id'], cash=str(cash)), self._next_id(db, 'initialize'))
                else:
                    external = _json(snapshot)
                    for key in required:
                        if canonical_json(external[key]) != canonical_json(state[key]):
                            raise ReconciliationError(f'{key} discrepancy; local journal unchanged')
                    if state['quarantined']:
                        raise ReconciliationError('quarantined events require investigation; cannot silently discard or replay')
                    if self._capacity_breach(state):
                        raise ReconciliationError('Unresolved position/reserved exposure, cash or marked margin breach')
                    statuses = external.get('order_statuses', {})
                    unknown = {oid for oid, order in state['orders'].items() if order['status'] in ('unknown', 'submitting')}
                    if not isinstance(statuses, dict) or set(statuses) != unknown:
                        raise ReconciliationError('explicit resolution required for every unknown order')
                    for oid, status in statuses.items():
                        order = state['orders'][oid]
                        filled, quantity = order['filled_quantity'], order['intent']['quantity']
                        valid = {'cancelled'} | ({'accepted', 'rejected'} if filled == 0 else {'partial'} if filled < quantity else {'filled'})
                        if status not in valid:
                            raise ReconciliationError('resolved order status conflicts with fills')
                    state = self._append(db, state, 'reconcile', {'order_statuses': statuses}, self._next_id(db, 'reconcile'))
            except ValidationError as exc:
                error = ReconciliationError(str(exc))
                state = self._append(db, state, 'reconcile_failure', {'reason': str(exc)}, self._next_id(db, 'reconcile_failure'))
        if error:
            raise error
        return deepcopy(state)

    def set_kill_switch(self, active: bool):
        if type(active) is not bool:
            raise ValidationError('kill switch must be boolean')
        with self._transaction() as db:
            state = self._restore(db)
            if not active and (state['reconciliation_required'] or any(o['status'] in ('unknown', 'submitting') for o in state['orders'].values())):
                raise ReconciliationError('reconcile before disabling kill switch')
            self._append(db, state, 'kill', {'active': active}, self._next_id(db, 'kill'))


class LiveBroker:
    """Deliberately incapable of live execution; no flag enables it."""
    def __init__(self, *args, **kwargs):
        raise LiveTradingDisabled('Live trading is disabled; paper tests do not verify a real broker')

    def submit(self, *args, **kwargs):
        raise LiveTradingDisabled('Live trading is disabled')

    cancel = apply_event = snapshot = reconcile = set_kill_switch = submit
