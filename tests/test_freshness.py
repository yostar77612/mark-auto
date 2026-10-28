"""Explicit-time freshness and configuration contracts; no clocks or network IO."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import unittest

from quantlab.trading.domain.freshness import Freshness, LiveMarketSettings, classify_freshness
from quantlab.trading.domain.validation import DomainError


class FreshnessTests(unittest.TestCase):
    def test_states_thresholds_and_precedence(self):
        now = datetime(2026, 10, 28, tzinfo=timezone.utc)
        for age, connected, session, expected in (
            (0, True, True, Freshness.LIVE),
            (10, True, True, Freshness.LIVE),
            (10.001, True, True, Freshness.DELAYED),
            (60, True, True, Freshness.DELAYED),
            (60.001, True, True, Freshness.STOPPED),
            (0, False, True, Freshness.STOPPED),
            (100, False, False, Freshness.CLOSED),
            (0, True, None, Freshness.UNKNOWN),
            (None, True, True, Freshness.UNKNOWN),
            (None, False, False, Freshness.UNKNOWN),
            (-1, True, True, Freshness.UNKNOWN),
        ):
            with self.subTest(age=age, connected=connected, session=session):
                received = None if age is None else now - timedelta(seconds=age)
                self.assertIs(classify_freshness(received, now=now, connected=connected, in_session=session), expected)
        custom = LiveMarketSettings(delayed_seconds=2, stopped_seconds=5)
        self.assertIs(classify_freshness(now - timedelta(seconds=3), now=now, connected=True, in_session=True, settings=custom), Freshness.DELAYED)

    def test_settings_boundary_and_defaults(self):
        settings = LiveMarketSettings()
        self.assertEqual(
            (settings.delayed_seconds, settings.stopped_seconds, settings.buffer_trade_days, settings.queue_limit, settings.subscription_limit),
            (10, 60, 30, 10000, 20),
        )
        for changes in (
            {'delayed_seconds': 0},
            {'stopped_seconds': 10},
            {'stopped_seconds': 9},
            {'buffer_trade_days': -1},
            {'queue_limit': 0},
            {'subscription_limit': 21},
            {'subscription_limit': 0},
            {'queue_limit': True},
            {'delayed_seconds': '10'},
        ):
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                replace(settings, **changes)
        with self.assertRaises(FrozenInstanceError):
            settings.queue_limit = 3


if __name__ == '__main__':
    unittest.main()
