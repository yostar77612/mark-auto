"""Trusted host orchestration for prospective single-candidate E1 evaluation.

No method is an AI tool or IPC handler. Capture requires a separate explicit host
network action. Public operations return only a reference or no value, never OOS
results. Real data is used only when the owner later operates this host workflow.
"""

from quantlab.backtest import run_backtest
from quantlab.core import canonical_json, content_hash
from quantlab.research import _run_bounded
from quantlab.significance import mean_positive_test, required_observations
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime import e1_protocol as protocol
from quantlab.trading.runtime import e1_source as source
from quantlab.trading.runtime import e1_store as store
from quantlab.trading.runtime.v1_signal_source import validated_spec
from quantlab.verdict import judge
import sqlite3
import time


def _evaluate(dataset, spec_json, config):
    """One fixed spec, one full predeclared window; only minimal E1 leaves worker."""
    result = run_backtest(dataset, validated_spec(spec_json), config)
    returns = [row['return'] for row in result.metrics['daily_returns']]
    stats = mean_positive_test(returns, n_bootstrap=protocol.POLICY['bootstrap_draws'], seed=protocol.POLICY['bootstrap_seed'])
    verdict = judge(stats, required_observations(returns), returns, ())['level']
    return {'verdict': verdict, 'sample_count': len(returns), 'result_hash': content_hash(result)}


def _outcome(value):
    # Shared structure; at evaluation time the count must also be 1..max_bars (and, in
    # evaluate(), equal the dataset's trade days). The reader checks the frozen calendar.
    if not protocol.valid_outcome_shape(value) or not 1 <= value['sample_count'] <= protocol.POLICY['max_bars']:
        protocol.refuse()
    return value


class E1QualificationHost:
    """Host composition supplies authoritative bootstrap controls, never user JSON."""

    def __init__(self, workspace, *, registry_path):
        self.workspace, self.registry = store.safe_paths(workspace, registry_path)

    def freeze(self, *, campaign_ref, contract_id, signal_spec_json, calendar, config, evidence_mode='production'):
        """Freeze candidate, future calendar, source, costs and policy; consume once."""
        try:
            plan = protocol.make_plan(
                workspace=self.workspace,
                registry=self.registry,
                campaign_ref=campaign_ref,
                contract_id=contract_id,
                signal_spec_json=signal_spec_json,
                calendar=calendar,
                config=config,
                evidence_mode=evidence_mode,
            )
            return store.reserve(self.registry, self.workspace, plan)
        except Exception:
            raise DomainError('candidate_unavailable') from None

    def _load(self, reference, *, statuses):
        with store.connection(self.registry) as db:
            plan, status, binding, receipt = store.load(db, reference, self.workspace)
        if status not in statuses or receipt is not None:
            protocol.refuse()
        calendar, config = protocol.validate_plan(plan, workspace=self.workspace, registry=self.registry)
        return plan, calendar, config, binding

    def _fail(self, reference):
        # Failure to update is still fail-closed: evaluating/capturing are not
        # admissible evidence and their already committed coverage is never freed.
        try:
            store.terminate(self.registry, self.workspace, reference, 'failed')
        except Exception:
            pass

    def _release(self, reference, status):
        """Return a claimed-but-unwritten capture to its admitted state; True when done.

        Only for failures that wrote nothing and whose outcome is known (transient fetch or
        projection problems, lock contention). The planned window stays consumed either way.
        """
        try:
            with store.connection(self.registry, write=True) as db:
                db.execute("UPDATE e1_plans SET status=? WHERE reference=? AND status='capturing'", (status, reference))
            return True
        except Exception:
            return False

    def capture(self, reference, *, network_authorized=False):
        """One explicit fetch; append immutable planned sessions, never overwrite.

        A no-new-session response does not evaluate or retry evaluation. Each
        later acquisition is a new explicit host call, with the same frozen plan.

        The plan is claimed ('capturing') before the request so capture stays exclusive.
        If the fetch or projection then fails with nothing written, the outcome is known and
        the plan returns to its prior state, so a later explicit call may retry. A crash, an
        interrupt, a write failure or a conflicting revision leaves/makes it terminal.
        """
        if network_authorized is not True:
            protocol.refuse()
        claimed, prior = False, None
        try:
            plan, _, _, _ = self._load(reference, statuses=('reserved', 'captured'))
            with store.connection(self.registry, write=True) as db:
                _, status, _, _ = store.load(db, reference, self.workspace)
                if status not in ('reserved', 'captured'):
                    protocol.refuse()
                prior = status
                db.execute("UPDATE e1_plans SET status='capturing' WHERE reference=? AND status=?", (reference, status))
            claimed = True
            try:
                request_started_at = protocol.utc_now()
                raw = source.fetch_daily()
                captured_at = protocol.utc_now()
                if captured_at < request_started_at:
                    protocol.refuse()
                selected, response_digest = source.projected_rows(raw, plan, request_started_at)
            except Exception:
                claimed = not self._release(reference, prior)
                raise
            try:
                with store.connection(self.registry, write=True) as db:
                    _, status, _, _ = store.load(db, reference, self.workspace)
                    if status != 'capturing':
                        protocol.refuse()
                    for slot, row in selected.items():
                        prior_capture = db.execute('SELECT payload FROM e1_captures WHERE reference=? AND slot=?', (reference, slot)).fetchone()
                        if prior_capture is not None:
                            if protocol.decode(prior_capture[0])['row'] != row:
                                protocol.refuse()
                            continue
                        payload = {'row': row, 'response_digest': response_digest}
                        db.execute(
                            'INSERT INTO e1_captures VALUES (?,?,?,?,?)',
                            (reference, slot, canonical_json(payload), protocol.text_time(captured_at), content_hash(payload)),
                        )
                    db.execute("UPDATE e1_plans SET status='captured' WHERE reference=?", (reference,))
            except sqlite3.OperationalError as exc:
                # The single write transaction rolled back, so a busy/locked registry wrote nothing.
                if store.is_lock_contention(exc):
                    claimed = not self._release(reference, prior)
                raise
        except Exception:
            if claimed:
                self._fail(reference)
            raise DomainError('candidate_unavailable') from None
        except BaseException:
            # Shutdown requests keep the unknown-state accounting but are never swallowed.
            if claimed:
                self._fail(reference)
            raise

    def evaluate(self, reference):
        """Consume a single attempt before starting; no resume/retry of unknown work.

        Preconditions are checked first, so an unmet one (sessions still open, captures
        incomplete) changes nothing and the plan stays admitted. Captured rows that are
        present but inconsistent can never become valid (captures are immutable): terminal.
        The attempt is claimed ('evaluating') only once the exact dataset is built.
        """
        started = time.monotonic()
        claimed = inconsistent = False
        try:
            plan, calendar, config, _ = self._load(reference, statuses=('reserved', 'captured'))
            if max(row['end'] for row in calendar.sessions) > protocol.utc_now():
                protocol.refuse()
            with store.connection(self.registry, write=True) as db:
                _, status, _, _ = store.load(db, reference, self.workspace)
                if status not in ('reserved', 'captured'):
                    protocol.refuse()
                captures = db.execute('SELECT slot,payload,captured_at,digest FROM e1_captures WHERE reference=? ORDER BY slot', (reference,)).fetchall()
                if not source.complete(plan, captures):
                    protocol.refuse()
                try:
                    dataset, dataset_binding = source.captured_dataset(plan, captures)
                except Exception:
                    inconsistent = True
                    raise
                dataset_binding['evaluation_started_at'] = protocol.text_time(protocol.utc_now())
                db.execute(
                    "UPDATE e1_plans SET status='evaluating',dataset_binding=? WHERE reference=? AND status IN ('reserved','captured')",
                    (canonical_json(dataset_binding), reference),
                )
            claimed = True
            # Exact input dataset and one-attempt state are durable BEFORE scoring.
            outcome = _outcome(
                _run_bounded(
                    _evaluate,
                    (dataset, plan['spec_json'], config),
                    deadline=started + protocol.POLICY['max_runtime_seconds'],
                    config={
                        'process_start_method': 'spawn',
                        'worker_memory_mb': protocol.POLICY['worker_memory_mb'],
                        'max_ipc_bytes': protocol.POLICY['max_ipc_bytes'],
                    },
                )['value']
            )
            if outcome['sample_count'] != len({bar.trade_date for bar in dataset.bars}):
                protocol.refuse()
            completed = protocol.utc_now()
            if completed < protocol.timestamp(dataset_binding['evaluation_started_at']):
                protocol.refuse()
            receipt = {
                'protocol': protocol.PROTOCOL,
                'reference': reference,
                'plan_hash': content_hash(plan),
                'dataset_binding_hash': content_hash(dataset_binding),
                'source_digest': plan['source_digest'],
                'completed_at': protocol.text_time(completed),
                'outcome': outcome,
            }
            receipt['receipt_hash'] = content_hash(receipt)
            with store.connection(self.registry, write=True) as db:
                stored, status, binding, previous = store.load(db, reference, self.workspace)
                if status != 'evaluating' or previous is not None or binding != dataset_binding or stored != plan:
                    protocol.refuse()
                # Atomic terminal receipt, never a replaceable UI/export sidecar.
                db.execute("UPDATE e1_plans SET status='completed',receipt=? WHERE reference=?", (canonical_json(receipt), reference))
        except Exception:
            if claimed or inconsistent:
                self._fail(reference)
            raise DomainError('candidate_unavailable') from None
        except BaseException:
            if claimed:
                self._fail(reference)
            raise

    def cancel(self, reference):
        try:
            store.terminate(self.registry, self.workspace, reference, 'cancelled')
        except Exception:
            raise DomainError('candidate_unavailable') from None
