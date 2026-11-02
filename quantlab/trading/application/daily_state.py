"""Durable daily signal identities; current execution facts are never saved here."""

from dataclasses import dataclass
from datetime import date, datetime

from quantlab.trading.domain.auto_cycle import EvaluationCursor


@dataclass(frozen=True)
class DailyIntent:
    cursor: EvaluationCursor
    account_ref: str
    action: str
    instrument_id: str
    lot_id: str
    evidence_fingerprint: str
    calendar_id: str
    calendar_version: str
    target_trade_date: date
    not_before: datetime
    deadline: datetime
    created_at: datetime
    phase: str = 'READY'
    order_id: str = ''
    code: str = ''


@dataclass(frozen=True)
class DailyState:
    intents: tuple[DailyIntent, ...] = ()
    authorized_run: str = ''
    owner_stamp: str = ''
    waiting_session: bool = False
