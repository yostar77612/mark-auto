"""Explicit fixed-model assumptions and byte-stable legacy minute receipts."""

from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from threading import Event
import json
import unittest

from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.minute_receipt import MinuteResearchReceipt
from quantlab.trading.application.minute_research import research_minutes
from quantlab.trading.application.provenance import ProducerProfile
from quantlab.trading.domain.minute_research import FixedModelMinuteSettings, MinuteResearchSettings, complete_minutes
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.minute_receipt_store import MinuteReceiptStore
from tests.test_minute_research import fixture
from tests import test_minute_research_host as host_support


def fixed_settings(settings, **changes):
    values = {field.name: getattr(settings, field.name) for field in fields(MinuteResearchSettings)}
    values.update(historical_contract=None, sdk_code='TMFK6')
    values.update(changes)
    return FixedModelMinuteSettings(**values)


class MinuteBasisTests(unittest.TestCase):
    def test_legacy_settings_result_and_receipt_wire_hashes_are_unchanged(self):
        strategy, spec, calendar, rows, fees, settings = fixture()
        now = calendar.sessions[-1].closes_at + timedelta(days=1)
        bars = complete_minutes(rows, spec.instrument_id, calendar, settings, now)
        result = research_minutes(strategy, spec, calendar, bars, fees, settings=settings)
        self.assertEqual(sha256(dumps(settings).encode()).hexdigest(), '8ff9a6ea4c98a2b82d668a625c198da87a264168d45ac31faf64f186f26f4400')
        self.assertEqual(sha256(dumps(result).encode()).hexdigest(), '753620af2b4e68a40556dc32cf1f633a101a46fa5c86113c20ece9b0ef6b9adc')
        self.assertEqual(result.fingerprint, 'a9d3568d6602af9637f6375ecdb41c398e6bc6bbc35fd806b68f7024c4de0769')
        self.assertEqual(loads(dumps(result)), result)
        settings = replace(settings, raw_data_digest=sha256(dumps(rows).encode()).hexdigest())
        manifest = (('quantlab/trading/fixture.py', 'a' * 64),)
        digest = sha256(json.dumps(manifest, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
        profile = ProducerProfile('MARKAUTO-TRADING-V2-PROFILE-1', 2, manifest, digest)
        result = research_minutes(strategy, spec, calendar, bars, fees, settings=settings, source_profile=profile)
        receipt = MinuteResearchReceipt(result, strategy, spec, calendar, fees, profile, rows, now)
        self.assertEqual(sha256(dumps(receipt).encode()).hexdigest(), 'f6c0a7b2a7885fa0e3e43f0a5d9bd5ddc067ddb30534b084f8d006b10dafd8ff')
        self.assertEqual(loads(dumps(receipt)), receipt)

    def test_fixed_model_is_explicit_versioned_and_fingerprinted_not_historical_truth(self):
        strategy, spec, calendar, rows, fees, original = fixture()
        now = calendar.sessions[-1].closes_at + timedelta(days=1)
        for interval in ('1m', '5m'):
            settings = replace(original, interval=interval)
            fixed = fixed_settings(settings)
            bars = complete_minutes(rows, spec.instrument_id, calendar, settings, now)
            legacy = research_minutes(strategy, spec, calendar, bars, fees, settings=settings)
            modeled = research_minutes(strategy, spec, calendar, bars, fees, settings=fixed)
            self.assertEqual(modeled.trades, legacy.trades)
            changed_observation = replace(spec, effective_at=now, margin=spec.margin + 1)
            observed = research_minutes(strategy, changed_observation, calendar, bars, fees, settings=fixed)
            self.assertEqual(observed.trades, modeled.trades)
            self.assertNotEqual(observed.fingerprint, modeled.fingerprint)
            self.assertNotEqual(modeled.fingerprint, legacy.fingerprint)
            self.assertNotEqual(modeled.dataset_id, legacy.dataset_id)
            self.assertEqual(loads(dumps(modeled)), modeled)
            self.assertEqual(fixed.basis, 'FIXED_MODEL')
            self.assertEqual(fixed.historical_applicability, 'UNKNOWN')
            self.assertIsNone(fixed.historical_contract)
            for changes in ({'basis': 'VERIFIED'}, {'historical_applicability': 'VERIFIED'}, {'model_version': 'other'}, {'sdk_code': 'TMFR1'}):
                with self.subTest(changes=changes), self.assertRaises(DomainError):
                    replace(fixed, **changes)

    def test_fixed_model_still_rejects_wrong_contract_expiry_and_incomplete_grid(self):
        strategy, spec, calendar, rows, fees, original = fixture()
        settings = fixed_settings(original)
        now = calendar.sessions[-1].closes_at + timedelta(days=1)
        bars = complete_minutes(rows, spec.instrument_id, calendar, settings, now)
        wrong = replace(strategy, form=replace(strategy.form, instrument_id='TMF:199901'))
        with self.assertRaisesRegex(DomainError, 'contract mismatch'):
            research_minutes(wrong, spec, calendar, bars, fees, settings=settings)
        month = settings.first_day.strftime('%Y%m')
        expired = replace(spec, instrument_id='TMF:' + month, expiry=settings.first_day, delivery_month=month)
        expired_strategy = replace(strategy, form=replace(strategy.form, instrument_id=expired.instrument_id))
        with self.assertRaisesRegex(DomainError, 'contract expiry'):
            research_minutes(expired_strategy, expired, calendar, bars, fees, settings=settings)
        with self.assertRaisesRegex(DomainError, 'complete sessions'):
            research_minutes(strategy, spec, calendar, bars[:-1], fees, settings=settings)


class FixedModelHostTests(unittest.TestCase):
    def setUp(self):
        self.fixture = host_support.MinuteHostTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def test_generated_observation_supports_explicit_fixed_model_and_persists_unknown_basis(self):
        host = self.fixture
        settings = fixed_settings(host.settings)
        self.assertGreater(host.spec.effective_at, host.sdk.rows[0].start)
        with self.assertRaisesRegex(DomainError, 'without historical proof'):
            replace(settings, historical_contract=host.settings.historical_contract)
        receipt = host.run_host(settings=settings)
        self.assertEqual(receipt.raw_bars, host.sdk.rows)
        self.assertEqual(receipt.spec, host.spec)
        self.assertEqual(receipt.result.minute_settings.basis, 'FIXED_MODEL')
        self.assertEqual(receipt.result.minute_settings.historical_applicability, 'UNKNOWN')
        self.assertEqual(receipt.result.minute_settings.sdk_code, 'TMFK6')
        self.assertEqual(receipt.fees, host.resources.fees)
        self.assertTrue(receipt.result.trades)
        store = MinuteReceiptStore(host.receipt_path, datetime.now(timezone.utc))
        try:
            self.assertEqual(store.read(1), receipt)
        finally:
            store.close()
        # Reference mode remains rejected without its interval even after fixed-model cache fill.
        with self.assertRaisesRegex(DomainError, 'historical contract applicability'):
            host.run_host(settings=replace(host.settings, historical_contract=None))

    def test_fixed_model_wrong_sdk_binding_and_sparse_refill_never_publish(self):
        host = self.fixture
        settings = fixed_settings(host.settings)
        with self.assertRaisesRegex(DomainError, 'contract code mismatch'):
            host.run_host(settings=replace(settings, sdk_code='TMFOTHER'))
        self.assertEqual(host.sdk.calls, [])
        self.assertFalse(host.receipt_path.exists())
        host.sdk.rows = host.sdk.rows[:-1]
        with self.assertRaisesRegex(DomainError, 'incomplete after refill'):
            host.run_host(settings=settings)
        self.assertFalse(host.receipt_path.exists())

    def test_fixed_model_cancellation_does_not_publish(self):
        host = self.fixture
        cancel = Event()
        cancel.set()
        with self.assertRaisesRegex(DomainError, 'canceled'):
            host.run_host(settings=fixed_settings(host.settings), cancel=cancel)
        self.assertFalse(host.receipt_path.exists())
        self.assertIsNone(host.bundle.minute_research_active)
