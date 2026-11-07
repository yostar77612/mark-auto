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
from quantlab.verdict import LEVELS, judge
import time


def _evaluate(dataset, spec_json, config):
    """One fixed spec, one full predeclared window; only minimal E1 leaves worker."""
    result = run_backtest(dataset, validated_spec(spec_json), config)
    returns = [row['return'] for row in result.metrics['daily_returns']]
    stats = mean_positive_test(returns, n_bootstrap=protocol.POLICY['bootstrap_draws'], seed=protocol.POLICY['bootstrap_seed'])
    verdict = judge(stats, required_observations(returns), returns, ())['level']
    return {'verdict': verdict, 'sample_count': len(returns), 'result_hash': content_hash(result)}


def _outcome(value):
    if (
        type(value) is not dict
        or set(value) != {'verdict', 'sample_count', 'result_hash'}
        or value['verdict'] not in LEVELS
        or type(value['sample_count']) is not int
        or not 1 <= value['sample_count'] <= protocol.POLICY['max_bars']
        or not protocol.is_hash(value['result_hash'])
    ):
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

    def capture(self, reference, *, network_authorized=False):
        """One explicit fetch; append immutable planned sessions, never overwrite.

        A no-new-session response does not evaluate or retry evaluation. Each
        later acquisition is a new explicit host call, with the same frozen plan.
        """
        if network_authorized is not True:
            protocol.refuse()
        claimed = False
        try:
            plan, _, _, _ = self._load(reference, statuses=('reserved', 'captured'))
            with store.connection(self.registry, write=True) as db:
                _, status, _, _ = store.load(db, reference, self.workspace)
                if status not in ('reserved', 'captured'):
                    protocol.refuse()
                claimed = True
                db.execute("UPDATE e1_plans SET status='capturing' WHERE reference=?", (reference,))
            request_started_at = protocol.utc_now()
            raw = source.fetch_daily()
            captured_at = protocol.utc_now()
            if captured_at < request_started_at:
                protocol.refuse()
            selected, response_digest = source.projected_rows(raw, plan, request_started_at)
            with store.connection(self.registry, write=True) as db:
                _, status, _, _ = store.load(db, reference, self.workspace)
                if status != 'capturing':
                    protocol.refuse()
                for slot, row in selected.items():
                    prior = db.execute('SELECT payload FROM e1_captures WHERE reference=? AND slot=?', (reference, slot)).fetchone()
                    if prior is not None:
                        if protocol.decode(prior[0])['row'] != row:
                            protocol.refuse()
                        continue
                    payload = {'row': row, 'response_digest': response_digest}
                    db.execute(
                        'INSERT INTO e1_captures VALUES (?,?,?,?,?)',
                        (reference, slot, canonical_json(payload), protocol.text_time(captured_at), content_hash(payload)),
                    )
                db.execute("UPDATE e1_plans SET status='captured' WHERE reference=?", (reference,))
        except BaseException:
            if claimed:
                self._fail(reference)
            raise DomainError('candidate_unavailable') from None

    def evaluate(self, reference):
        """Consume a single attempt before starting; no resume/retry of unknown work."""
        started = time.monotonic()
        claimed = False
        try:
            plan, calendar, config, _ = self._load(reference, statuses=('reserved', 'captured'))
            if max(row['end'] for row in calendar.sessions) > protocol.utc_now():
                protocol.refuse()
            with store.connection(self.registry, write=True) as db:
                _, status, _, _ = store.load(db, reference, self.workspace)
                if status not in ('reserved', 'captured'):
                    protocol.refuse()
                claimed = True
                captures = db.execute('SELECT slot,payload,captured_at,digest FROM e1_captures WHERE reference=? ORDER BY slot', (reference,)).fetchall()
                dataset, dataset_binding = source.captured_dataset(plan, captures)
                dataset_binding['evaluation_started_at'] = protocol.text_time(protocol.utc_now())
                db.execute("UPDATE e1_plans SET status='evaluating',dataset_binding=? WHERE reference=?", (canonical_json(dataset_binding), reference))
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
        except BaseException:
            if claimed:
                self._fail(reference)
            raise DomainError('candidate_unavailable') from None

    def cancel(self, reference):
        try:
            store.terminate(self.registry, self.workspace, reference, 'cancelled')
        except Exception:
            raise DomainError('candidate_unavailable') from None
