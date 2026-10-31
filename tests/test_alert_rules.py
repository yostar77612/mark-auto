"""Decimal alert fixtures, edge rearming, cooldown and completed-bar eligibility."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import unittest

from quantlab.trading.domain.alerts import (
    AlertKind,
    AlertObservation,
    AlertRule,
    AlertTriggerState,
    alert_condition,
    evaluate_alert,
    kd,
    sma,
)
from quantlab.trading.domain.freshness import Freshness
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.validation import DomainError

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
ID = 'TWSE:2330'


def bar(close='100', *, opening=None, low=None, high=None, volume=10, minute=0, final=True):
    price = D(close)
    return LiveBar(
        ID,
        NOW + timedelta(minutes=minute),
        NOW + timedelta(minutes=minute + 1),
        NOW.date(),
        'REGULAR',
        price if opening is None else D(opening),
        price if high is None else D(high),
        price if low is None else D(low),
        price,
        volume,
        final,
    )


def fixtures():
    tick = AlertObservation(
        ID,
        NOW,
        price=D('100'),
        previous_price=D('99'),
        reference_price=D('98'),
        previous_high=D('99'),
        previous_low=D('80'),
        day_high=D('99'),
        day_low=D('80'),
        minutes_since_open=6,
        freshness=Freshness.LIVE,
    )
    bars = {
        AlertKind.FAST_MOVE: ({'minutes': 2}, (bar('100'), bar('102', opening='100', minute=1))),
        AlertKind.VOLUME_SURGE: ({'count': 3}, tuple(bar(volume=v, minute=i) for i, v in enumerate((10, 10, 10, 30)))),
        AlertKind.MA_CROSS: ({'short': 2, 'long': 3}, tuple(bar(str(v), minute=i) for i, v in enumerate((3, 2, 1, 5)))),
        AlertKind.KD_CROSS: (
            {'n': 2, 'k_smoothing': 2, 'd_smoothing': 2, 'low': 50, 'high': 50},
            tuple(bar(str(v), low='1', high='11', minute=i) for i, v in enumerate((1, 1, 7))),
        ),
    }
    for kind in AlertKind:
        if kind in bars:
            params, values = bars[kind]
            yield AlertRule(kind.value, kind, instrument_id=ID, params=params), replace(tick, bars=values)
        elif kind in (AlertKind.LIMIT_UP, AlertKind.LIMIT_DOWN, AlertKind.PRICE_JUMP, AlertKind.VOLUME_BURST):
            yield AlertRule(kind.value, kind, instrument_id=ID), replace(tick, scanner_kind=kind, scanner_subtype='TOUCH')
        else:
            yield AlertRule(kind.value, kind, instrument_id=ID), tick


class AlertRulesTests(unittest.TestCase):
    def test_all_twelve_conditions_and_edge_cooldown(self):
        seen = []
        for rule, observation in fixtures():
            with self.subTest(kind=rule.kind):
                seen.append(rule.kind)
                self.assertTrue(alert_condition(rule, observation)[0])
                state, fired, _ = evaluate_alert(rule, observation, AlertTriggerState())
                self.assertTrue(fired)
                state, fired, _ = evaluate_alert(rule, replace(observation, occurred_at=NOW + timedelta(seconds=1)), state)
                self.assertFalse(fired)
                # An eligible false observation re-arms every kind, including scanner pulses.
                if rule.kind in (AlertKind.LIMIT_UP, AlertKind.LIMIT_DOWN, AlertKind.PRICE_JUMP, AlertKind.VOLUME_BURST):
                    false = replace(observation, scanner_active=False)
                elif observation.bars:
                    false = replace(observation, bars=tuple(bar('100', minute=i) for i in range(5)))
                else:
                    false = replace(observation, price=D('90'), previous_price=D('90'), reference_price=D('90'))
                state, fired, _ = evaluate_alert(rule, replace(false, occurred_at=NOW + timedelta(seconds=2)), state)
                self.assertFalse(fired)
                self.assertFalse(state.active)
                state, fired, _ = evaluate_alert(rule, replace(observation, occurred_at=NOW + timedelta(seconds=3)), state)
                self.assertFalse(fired)
                state, _, _ = evaluate_alert(rule, replace(false, occurred_at=NOW + timedelta(seconds=59)), state)
                state, fired, _ = evaluate_alert(rule, replace(observation, occurred_at=NOW + timedelta(seconds=60)), state)
                self.assertTrue(fired)
        self.assertEqual(list(AlertKind), seen)

    def test_unfinished_and_incomplete_bars_never_trigger(self):
        for rule, observation in fixtures():
            if observation.bars:
                for changes in ({'final': False}, {'incomplete': True}):
                    with self.subTest(kind=rule.kind, changes=changes):
                        bad = replace(observation, bars=(*observation.bars[:-1], replace(observation.bars[-1], **changes)))
                        self.assertIsNone(alert_condition(rule, bad))
                        self.assertFalse(evaluate_alert(rule, bad, AlertTriggerState())[1])

    def test_non_live_and_backfill_ticks_are_ignored(self):
        for rule, observation in fixtures():
            if not observation.bars and observation.scanner_kind is None:
                for freshness in (Freshness.UNKNOWN, Freshness.DELAYED, Freshness.STOPPED, Freshness.CLOSED):
                    self.assertIsNone(alert_condition(rule, replace(observation, freshness=freshness)))
                self.assertIsNone(alert_condition(rule, replace(observation, backfilling=True)))

    def test_decimal_indicators_exact_flat_and_short_history(self):
        self.assertEqual(D(2), sma((D(1), D(2), D(3)), 3))
        self.assertIsNone(sma((D(1),), 2))
        self.assertEqual(((D(50), D(50)),) * 3, kd(tuple(bar() for _ in range(4)), n=2))
        self.assertEqual((), kd((bar(),), n=2))
        values = kd(tuple(bar(str(v), low='1', high='11') for v in (1, 1, 7)), 2, 2, 2)
        self.assertEqual(((D(25), D('37.5')), (D('42.5'), D(40))), values)

    def test_boundary_validation_and_immutable_params(self):
        invalid = (
            (AlertKind.PRICE_CROSS, {'price': 'NaN'}),
            (AlertKind.PRICE_CROSS, {'price': 0}),
            (AlertKind.FAST_MOVE, {'minutes': '1.5'}),
            (AlertKind.CHANGE_PERCENT, {'percent': 11}),
            (AlertKind.MA_CROSS, {'short': 20, 'long': 20}),
            (AlertKind.KD_CROSS, {'low': 51}),
            (AlertKind.VOLUME_SURGE, {'period': '1d'}),
            (AlertKind.PRICE_JUMP, {'direction': 'SIDEWAYS'}),
        )
        for kind, params in invalid:
            with self.subTest(kind=kind, params=params), self.assertRaises(DomainError):
                AlertRule('r', kind, instrument_id=ID, params=params)
        with self.assertRaises(DomainError):
            AlertRule('r', AlertKind.PRICE_CROSS, scope='MARKET')
        rule = AlertRule('r', AlertKind.PRICE_CROSS, instrument_id=ID)
        with self.assertRaises(TypeError):
            rule.params['price'] = D(2)
        for kind in (AlertKind.VOLUME_SURGE, AlertKind.LIMIT_UP, AlertKind.LIMIT_DOWN, AlertKind.PRICE_JUMP, AlertKind.VOLUME_BURST):
            with self.assertRaises(DomainError):
                AlertRule('r', kind, instrument_id='INDEX:IX0001')

    def test_reference_unknown_opening_delay_period_and_index_volume(self):
        for rule, o in fixtures():
            if rule.kind == AlertKind.CHANGE_PERCENT:
                self.assertIsNone(alert_condition(rule, replace(o, reference_price=None)))
            if rule.kind == AlertKind.DAY_HIGH_LOW:
                self.assertIsNone(alert_condition(rule, replace(o, minutes_since_open=4)))
            if o.bars:
                self.assertIsNone(alert_condition(rule, replace(o, period='5m')))
            if rule.kind == AlertKind.VOLUME_SURGE:
                self.assertIsNone(alert_condition(rule, replace(o, instrument_id='INDEX:IX0001')))


if __name__ == '__main__':
    unittest.main()
