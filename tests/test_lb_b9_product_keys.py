"""Cheap offline futures-key, storage, preference and hash contracts."""

from dataclasses import replace
import json
from pathlib import Path
import unittest

from PySide6.QtWidgets import QApplication

from desktop_app.features.market.dashboard import MarketDashboard
from quantlab.chart_drawings import DrawingStore, HorizontalLine
from quantlab.core import content_hash, canonical_json
from quantlab.research_core.adapters.settings_store import SettingsStore
from quantlab.product_keys import converge_key, MONTH_CODES, PRODUCT_KEYS
from quantlab.research import _summary
from quantlab.taifex_expiries import load_expiries, lookup_expiry
from tests.test_backtest import bar, dataset, run, spec
from tests.test_lb_b8_drawings import anchor, local_profile


ROOT = Path(__file__).resolve().parents[1]


class ProductKeysTests(unittest.TestCase):
    def test_all_months_year_digits_and_families(self):
        for prefix, key in PRODUCT_KEYS.items():
            for month in 'ABCDEFGHIJKL':
                for year in '0123456789':
                    with self.subTest(prefix=prefix, month=month, year=year):
                        self.assertEqual(converge_key(prefix + month + year), key)
            for suffix in ('R1', 'R2'):
                self.assertEqual(converge_key(prefix + suffix), key)
        self.assertEqual([converge_key(s) for s in ('TXFR1', 'TXFI6', 'TXFJ6')], ['TXF'] * 3)
        self.assertEqual([converge_key(s) for s in ('MXFR1', 'MXFI6', 'MTXJ6')], ['MXF'] * 3)
        self.assertEqual([converge_key(s) for s in ('TMFR1', 'TMFI6', 'TMFJ6')], ['TMF'] * 3)
        self.assertEqual(len({converge_key(s) for s in ('TXFR1', 'MXFR1', 'TMFR1')}), 3)

    def test_shipped_verified_months(self):
        data = load_expiries()
        self.assertEqual(tuple(MONTH_CODES), tuple(f'{i:02d}' for i in range(1, 13)))
        for product, prefix in (('TX', 'TXF'), ('MTX', 'MXF'), ('TMF', 'TMF')):
            for row in data['expiries']:
                month = row['contract_month']
                with self.subTest(product=product, month=month):
                    self.assertIsNotNone(lookup_expiry(product, month, data=data))
                    key = converge_key(prefix + 'R1')
                    self.assertEqual(converge_key(prefix + MONTH_CODES[month[-2:]] + month[3]), key)
                    self.assertEqual(converge_key(f'TAIFEX:{product}:{month}'), key)

    def test_options_unknowns_and_disabled_identity(self):
        options = ('TXO20000A6', 'TXO20100A6', 'TXO20000B6', 'TXO20000M6', 'TX120000A6', 'TX220000M6', 'TXO202610C20000', 'TXO202610P20000')
        self.assertEqual(len(set(map(converge_key, options))), len(options))
        unknowns = ('', None, 1, True, [], {}, 'txfi6', ' TXFI6', 'TXFM6', 'TXFR3', 'TXFA26', 'TAIFEX:TX:202610W1', 'TAIFEX:TX:000001')
        for value in (*options, *unknowns):
            self.assertIs(converge_key(value), value)
        for value in (*options, *unknowns, 'TXFI6', 'MXFR1', 'TMFJ6'):
            self.assertIs(converge_key(value, enabled=False), value)
        for value in (None, 0, 1, 'true'):
            with self.assertRaises(ValueError):
                converge_key('TXFI6', enabled=value)

    def test_original_storage_shared_lookup_and_byte_losslessness(self):
        drawing = HorizontalLine(anchor())
        with local_profile() as profile:
            store = DrawingStore(profile)
            store.save('TXFI6', (drawing,))
            # Symbol-code stores from B8 also work without discovery metadata.
            store.path_for('TXFI6').with_suffix('.key').unlink()
            before = {p.name: p.read_bytes() for p in store.directory.iterdir()}
            for enabled in (True, False, True):
                for symbol in ('TXFI6', 'TXFJ6', 'TXFR1'):
                    self.assertEqual(store.load(symbol, enabled=enabled), (drawing,) if enabled or symbol == 'TXFI6' else ())
                for symbol in ('MXFI6', 'MXFR1', 'TMFI6', 'TMFR1', 'TXO20000A6'):
                    self.assertEqual(store.load(symbol, enabled=enabled), ())
                self.assertEqual({p.name: p.read_bytes() for p in store.directory.iterdir()}, before)
            store.save('TAIFEX:TMF:202610', (drawing,))
            self.assertEqual(store.load('TMFR1'), (drawing,))
            self.assertEqual(store.load('TAIFEX:TMF:202611'), (drawing,))
            self.assertEqual(store.load('TMFR1', enabled=False), ())
            second = replace(drawing, anchor=anchor(25))
            store.save('TXFJ6', (second,))
            self.assertEqual(store.load('TXFR1'), (drawing, second))
            self.assertEqual(store.load_exact('TXFI6'), (drawing,))

    def test_research_hashes_unchanged(self):
        data = dataset([bar(i, 20000 + i) for i in range(8)])
        strategy = spec()

        def hashes():
            result = run(data, [(0, 1), (5, 0)], st=strategy)
            return content_hash(data), data.manifest['data_hash'], content_hash(strategy), content_hash(result), canonical_json(_summary(result))

        before = hashes()
        with local_profile() as profile:
            store = DrawingStore(profile)
            store.save('TXFI6', (HorizontalLine(anchor()),))
            for enabled in (True, False, True):
                store.load('TXFR1', enabled=enabled)
                SettingsStore(profile / 'settings.json').save({'market': {'version': 1, 'converge_annotations': enabled}})
                self.assertEqual(hashes(), before)
        for module in ('research', 'backtest', 'data', 'core', 'strategies', 'provider'):
            self.assertNotIn('product_keys', (ROOT / 'quantlab' / (module + '.py')).read_text(encoding='utf-8-sig'))


class PreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_ui_toggle_persistence_legacy_and_malformed_payloads(self):
        dashboard = MarketDashboard()
        self.addCleanup(dashboard.close)
        with local_profile() as profile:
            store = DrawingStore(profile)
            drawing = HorizontalLine(anchor())
            store.save('TAIFEX:TX:202609', (drawing,))
            dashboard.drawing_store = store
            dashboard._selected = 'TAIFEX:TX:202610'
            dashboard.refresh_annotations()
            self.assertEqual(dashboard.chart.drawings, (drawing,))
            original = {p.name: p.read_bytes() for p in store.directory.iterdir()}
            settings = SettingsStore(profile / 'settings.json')
            changes = []
            dashboard.preferences_changed.connect(lambda: changes.append(dashboard.preferences()))
            for enabled in (False, True):
                dashboard.converge_annotations.setChecked(enabled)
                self.assertEqual(dashboard.chart.drawings, (drawing,) if enabled else ())
                settings.save({'market': dashboard.preferences()})
                dashboard.restore_preferences(settings.load()['market'])
                self.assertEqual(dashboard.converge_annotations.isChecked(), enabled)
            self.assertEqual(len(changes), 2)
            self.assertEqual({p.name: p.read_bytes() for p in store.directory.iterdir()}, original)
            dashboard.restore_preferences({'version': 1})
            self.assertTrue(dashboard.converge_annotations.isChecked())
            for bad in ('false', 1, None, [], {}):
                before = dashboard.preferences()
                with self.assertRaises(ValueError):
                    dashboard.restore_preferences({'version': 1, 'converge_annotations': bad})
                self.assertEqual(dashboard.preferences(), before)
            settings.save({})
            self.assertEqual(settings.load(), {})

    def test_public_oracle_and_size_limits(self):
        # Existing oracle assertions are reused unchanged.
        from tests.test_lb_b8_drawings import DrawingTests

        DrawingTests().test_public_name_oracle_and_class_size_unchanged()
        names = json.loads((ROOT / 'tests/fixtures/desktop_widget_names.json').read_text(encoding='utf-8'))
        self.assertIn('market_converge_annotations', names)
        self.assertEqual(names, sorted(set(names)))
