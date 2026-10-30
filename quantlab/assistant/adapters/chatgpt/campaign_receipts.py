"""Campaign receipts responsibility; original guards and ordering preserved."""

from __future__ import annotations

from quantlab.assistant.domain.plan_protocol import PlanError
from quantlab.assistant.domain.plan_protocol import _fail
from quantlab.assistant.domain.plan_protocol import _unique
from quantlab.core import content_hash
from quantlab.research_core.domain.receipts import _validated_receipt_snapshot
import json
import sqlite3


def _checked_campaign_rows(db, schema, expected):
    """Must run in the same transaction as the global expectation read."""
    try:
        budget = db.execute('SELECT binding,calls,blocked FROM ' + schema + '.plan_budget WHERE id=1').fetchone()
        rows = db.execute(
            'SELECT sequence,request_hash,request_bytes,status,response_hash,usage,received_bytes,elapsed_seconds FROM '
            + schema
            + '.plan_calls ORDER BY sequence LIMIT 101'
        ).fetchall()
        if (
            not budget
            or expected is None
            or budget[:2] != expected
            or type(budget[1]) is not int
            or not 1 <= budget[1] <= 100
            or len(rows) != budget[1]
            or [row[0] for row in rows] != list(range(1, budget[1] + 1))
        ):
            _fail('campaign_controls_inconsistent')
        _rows_to_receipts(rows)
        return budget, rows
    except sqlite3.Error:
        raise PlanError('campaign_controls_unavailable') from None


def _rows_to_receipts(rows):
    claims = {
        'billing_route': 'chatgpt_plan',
        'paid_api_fallback': False,
        'token_upper_bound_enforced': False,
        'spend_upper_bound_enforced': False,
        'account_credit_policy': 'unverified_user_setting',
    }
    try:
        receipts = []
        for row in rows:
            if type(row[5]) is not str or len(row[5]) > 512:
                _fail('campaign_controls_invalid')
            usage = json.loads(row[5], object_pairs_hook=_unique, parse_constant=lambda _: _fail('campaign_controls_invalid'))
            receipts.append(
                dict(
                    claims,
                    sequence=row[0],
                    request_hash=row[1],
                    request_bytes=row[2],
                    status=row[3],
                    response_hash=row[4],
                    token_usage=usage,
                    received_bytes=row[6],
                    elapsed_seconds=row[7],
                )
            )
        # Reuse the same strict, allowlisted receipt schema as parent persistence.
        descriptor = {'version': 1}
        return _validated_receipt_snapshot({'version': 1, 'provider_descriptor_hash': content_hash(descriptor), 'receipts': receipts}, descriptor)
    except Exception:
        raise PlanError('campaign_controls_invalid') from None
