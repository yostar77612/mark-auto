"""Read only authoritative E1 summaries; never open captured OOS payload columns."""

from quantlab.core import content_hash
from quantlab.trading.domain.signal_strategy import CandidateEvidence
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime import e1_protocol as protocol
from quantlab.trading.runtime import e1_store as store
from quantlab.verdict import LEVELS

BINDING_KEYS = {'data_hash', 'source_hash', 'calendar_hash', 'capture_hash', 'source_type', 'bar_count', 'evaluation_started_at'}
RECEIPT_KEYS = {'protocol', 'reference', 'plan_hash', 'dataset_binding_hash', 'source_digest', 'completed_at', 'outcome', 'receipt_hash'}


def _verify_completion(db, reference, plan, binding, receipt, calendar):
    if type(binding) is not dict or set(binding) != BINDING_KEYS or type(receipt) is not dict or set(receipt) != RECEIPT_KEYS:
        protocol.refuse()
    if any(not protocol.is_hash(binding[key]) for key in ('data_hash', 'source_hash', 'calendar_hash', 'capture_hash')):
        protocol.refuse()
    if binding['source_type'] != 'official_local' or type(binding['bar_count']) is not int or binding['bar_count'] != len(calendar.sessions):
        protocol.refuse()
    if (
        receipt['protocol'] != protocol.PROTOCOL
        or receipt['reference'] != reference
        or receipt['plan_hash'] != reference
        or receipt['dataset_binding_hash'] != content_hash(binding)
        or receipt['source_digest'] != plan['source_digest']
        or receipt['receipt_hash'] != content_hash({key: value for key, value in receipt.items() if key != 'receipt_hash'})
        or binding['calendar_hash'] != calendar.hash
    ):
        protocol.refuse()
    # Metadata-only query: captured data, prices and source payloads never enter reader.
    rows = db.execute('SELECT slot,captured_at,digest FROM e1_captures WHERE reference=? ORDER BY slot', (reference,)).fetchmany(
        protocol.POLICY['max_bars'] + 1
    )
    if [row[0] for row in rows] != list(range(len(calendar.sessions))):
        protocol.refuse()
    captures = []
    started = protocol.timestamp(binding['evaluation_started_at'])
    completed = protocol.timestamp(receipt['completed_at'])
    for slot, captured_at, digest in rows:
        if not protocol.is_hash(digest) or not calendar.sessions[slot]['end'] <= protocol.timestamp(captured_at) <= started:
            protocol.refuse()
        captures.append({'slot': slot, 'captured_at': captured_at, 'digest': digest})
    if binding['capture_hash'] != content_hash(captures) or not started <= completed <= protocol.utc_now():
        protocol.refuse()
    outcome = receipt['outcome']
    if (
        type(outcome) is not dict
        or set(outcome) != {'verdict', 'sample_count', 'result_hash'}
        or outcome['verdict'] not in LEVELS
        or type(outcome['sample_count']) is not int
        or outcome['sample_count'] != len({row['trade_date'] for row in calendar.sessions})
        or not protocol.is_hash(outcome['result_hash'])
    ):
        protocol.refuse()
    if outcome['verdict'] == 'statistical_edge' and outcome['sample_count'] < protocol.POLICY['minimum_observations']:
        protocol.refuse()
    return outcome, completed


def read_e1_summaries(workspace, *, registry_path):
    """Trusted composition passes the SAME bootstrap registry used by research.

    Missing authority and inconsistent current evidence refuse. Old source versions
    are ignored, never upgraded. The host-owned registry is a trusted authority,
    not authenticated against an attacker able to coherently rewrite its records.
    Pending/failed/cancelled and explicitly synthetic plans never confer E1.
    """
    try:
        workspace, registry = store.safe_paths(workspace, registry_path)
        with store.connection(registry) as db:
            current = protocol.source_digest()
            if current != protocol.RUNTIME_SOURCE_DIGEST:
                protocol.refuse()
            # Terminal history stays consumed but cannot exhaust the active listing.
            references = db.execute("SELECT reference,plan FROM e1_plans WHERE workspace=? AND status='completed' ORDER BY reference", (str(workspace),))
            evidence = []
            for reference, encoded in references:
                stored = protocol.decode(encoded)
                if type(stored) is not dict or not protocol.is_hash(stored.get('source_digest')):
                    protocol.refuse()
                if stored['source_digest'] != current or stored.get('evidence_mode') != 'production':
                    continue
                plan, _, binding, receipt = store.load(db, reference, workspace)
                calendar, _ = protocol.validate_plan(plan, workspace=workspace, registry=registry)
                if len(evidence) >= 1000:
                    protocol.refuse()
                outcome, completed = _verify_completion(db, reference, plan, binding, receipt, calendar)
                evidence.append(
                    CandidateEvidence(
                        candidate_ref=reference,
                        campaign_ref=plan['campaign_ref'],
                        candidate_fingerprint=plan['candidate_fingerprint'],
                        verdict=outcome['verdict'],
                        oos_consumed=True,
                        sample_count=outcome['sample_count'],
                        completed_at=completed,
                        dataset_family=plan['dataset_family'],
                        dataset_interval=plan['dataset_interval'],
                        signal_spec_json=plan['spec_json'],
                    )
                )
            return tuple(evidence)
    except Exception:
        raise DomainError('candidate_unavailable') from None
