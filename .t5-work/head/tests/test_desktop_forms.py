"""Freeze desktop form payload compatibility against existing backend contracts."""
import importlib.util
import os
import unittest
from copy import deepcopy

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None


@unittest.skipUnless(HAS_QT, 'Install desktop requirements for Qt form tests')
class DesktopFormsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_policy_header_units_are_visible_and_have_full_tooltips(self):
        from desktop_forms import _Rows
        columns = [('margin', '保證金 TWD／口'), ('session', '盤別（日盤 day／夜盤 night）')]
        form = _Rows('header_fixture', columns)
        header = form.table.horizontalHeader()
        for index, (_, label) in enumerate(columns):
            self.assertEqual(form.table.horizontalHeaderItem(index).toolTip(), label)
            self.assertGreaterEqual(form.table.columnWidth(index), header.fontMetrics().horizontalAdvance(label))
        form.close()

    def test_all_strategy_families_roundtrip(self):
        from desktop_forms import StrategyForm
        from quantlab.strategies import builtin_strategies, validate_strategy
        from quantlab.core import StrategySpec, to_dict
        form = StrategyForm()
        for spec in builtin_strategies():
            form.from_payload(to_dict(spec))
            self.assertEqual(form.build_payload(), to_dict(spec))
            validate_strategy(StrategySpec(**form.build_payload()))

    def test_strategy_invalid_never_clamped(self):
        from desktop_forms import StrategyForm
        from quantlab.core import ValidationError
        form = StrategyForm()
        for value in ('NaN', '-1', '100000000000000000000000', '1.5', ''):
            form.fields['fast'].setText(value)
            with self.assertRaises(ValidationError): form.build_payload()
        form.fields['fast'].setText('20')
        with self.assertRaises(ValidationError): form.build_payload()

    def test_config_dates_precision_and_schedules_roundtrip(self):
        from desktop_forms import BacktestForm
        from quantlab.reporting import demo_config
        from quantlab.core import to_dict, ValidationError
        from quantlab.__main__ import config_from_json
        config = to_dict(demo_config())
        config['costs']['commission_per_side'] = '20.1234567890123456789'
        config['instrument_expiries'] = {'TAIFEX:TMF:202601': '2026-01-21'}
        payload = dict(config=config, start_date='2026-01-01', end_date='2026-01-21')
        form = BacktestForm().from_payload(payload)
        self.assertEqual(form.build_payload(), payload)
        config_from_json(form.build_payload()['config'])
        for bad in ('NaN', 'Infinity', '-1', '1e999999'):
            form.fields['initial_cash'].setText(bad)
            with self.assertRaises(ValidationError): form.build_payload()
        form.from_payload(payload)
        form.fields['start_date'].setText('2026-02-30')
        with self.assertRaises(ValidationError): form.build_payload()

    def test_campaign_contract_and_invalid_splits(self):
        from desktop_forms import CampaignForm
        from quantlab.research import demo_campaign_config, _campaign_config
        from quantlab.reporting import synthetic_dataset, demo_config
        from quantlab.core import to_dict, ValidationError
        data = synthetic_dataset(160)
        config = demo_campaign_config(data, demo_config())
        config['backtest_config'] = to_dict(config['backtest_config'])
        form = CampaignForm().from_payload(config)
        self.assertEqual(form.build_payload(), config)
        from quantlab.__main__ import config_from_json
        parsed = form.build_payload(); parsed['backtest_config'] = config_from_json(parsed['backtest_config'])
        _campaign_config(data, parsed)
        form.fields['validation_start'].setText('1')
        with self.assertRaises(ValidationError): form.build_payload()
        form.from_payload(config)
        form.fields['max_trials'].setText('16')
        with self.assertRaises(ValidationError): form.build_payload()

    def test_paper_intent_quote_and_explicit_confirmation(self):
        from desktop_forms import PaperIntentForm, PaperQuoteForm, PaperSnapshotForm, PaperActionForm
        from quantlab.core import ValidationError
        intent = dict(client_order_id='test-1', strategy_hash='a'*64, contract_id='TAIFEX:TMF:202601', side='buy', quantity=1, order_type='limit', created_at='2026-01-05T01:00:00Z', limit_price='20000')
        quote = dict(account_id='paper-test', contract_id=intent['contract_id'], price='20000', timestamp=intent['created_at'], trade_date='2026-01-05', session_open='2026-01-05T00:45:00Z', session_end='2026-01-05T05:45:00Z', margin_per_contract='100000')
        self.assertEqual(PaperIntentForm().from_payload(intent).build_payload(), intent)
        self.assertEqual(PaperQuoteForm().from_payload(quote).build_payload(), quote)
        snapshot = dict(account_id='paper-test', cash='1000000', positions={}, orders={}, fills={})
        self.assertEqual(PaperSnapshotForm().from_payload(snapshot).build_payload(), snapshot)
        action = PaperActionForm().from_payload(dict(now=intent['created_at'], order_id='test-1', reconcile_confirmed=True))
        self.assertFalse(action.confirm.isChecked())
        with self.assertRaises(ValidationError): action.build_payload('submit')
        action.confirm.setChecked(True)
        self.assertTrue(action.build_payload('submit')['reconcile_confirmed'])
        action.clear_confirmation()
        with self.assertRaises(ValidationError): action.build_payload('replay')
        self.assertEqual(action.build_payload('cancel'), {'now':intent['created_at'], 'order_id':'test-1'})
        action.fields['order_id'].clear()
        with self.assertRaises(ValidationError): action.build_payload('cancel')
        with self.assertRaises(ValidationError): PaperQuoteForm().build_payload()

    def test_paper_policy_roundtrip_backend_validation(self):
        from desktop_forms import PaperPolicyForm
        from quantlab.paper import PaperBroker
        from quantlab.core import Instrument
        policy = dict(contract_id='TAIFEX:TMF:202601', risk_sessions=[dict(open='2026-01-05T00:45:00Z', end='2026-01-05T05:45:00Z', trade_date='2026-01-05', source='test fixture', session='day')], margin_schedule=[dict(effective_from='2026-01-01', margin_per_contract='100000', version='test-v1')])
        form = PaperPolicyForm().from_payload(policy)
        self.assertEqual(form.build_payload(), policy)
        broker = object.__new__(PaperBroker)
        broker.instrument = Instrument(policy['contract_id'])
        broker._risk_sessions = policy['risk_sessions']; broker._margin_schedule = policy['margin_schedule']
        broker._validate_policy()

    def test_result_table_readonly_and_named_fields(self):
        from desktop_forms import ResultTable, StrategyForm
        from PySide6.QtWidgets import QAbstractItemView
        table = ResultTable(); table.set_rows([{'net_pnl':'12.30', 'trade_count':2}])
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.editTriggers(), QAbstractItemView.EditTrigger.NoEditTriggers)
        form = StrategyForm()
        for field in form.fields.values():
            self.assertTrue(field.objectName())
            self.assertTrue(field.accessibleName())

    def test_paper_invalid_inputs_and_nested_records_preserved(self):
        from desktop_forms import PaperIntentForm, PaperSnapshotForm, PaperPolicyForm
        from quantlab.core import ValidationError
        from quantlab.paper import PaperBroker
        intent = dict(client_order_id='test-1', strategy_hash='a'*64, contract_id='TAIFEX:TMF:202601', side='buy', quantity=1, order_type='limit', created_at='2026-01-05T01:00:00Z', limit_price='20000')
        form = PaperIntentForm().from_payload(intent)
        broker = object.__new__(PaperBroker)
        self.assertEqual(broker._intent(form.build_payload()),intent)
        for bad in ('NaN','-20','0','1.1','1e9999'):
            form.fields['limit_price'].setText(bad)
            with self.assertRaises(ValidationError): form.build_payload()
        form.from_payload(intent); form.fields['created_at'].setText('2026-01-05T09:00:00+08:00')
        with self.assertRaises(ValidationError): form.build_payload()
        snapshot = dict(account_id='paper',cash='1000',positions={'TAIFEX:TMF:202601':-1},orders={'test-1':{'status':'unknown','filled_quantity':0}},fills={})
        original = deepcopy(snapshot)
        form = PaperSnapshotForm().from_payload(snapshot)
        snapshot['orders'].clear()
        self.assertEqual(form.build_payload(),original)
        self.assertEqual(form.record_tables['orders'].rowCount(),1)
        with self.assertRaises(ValidationError): PaperPolicyForm().build_payload()

    def test_no_stale_backtest_defaults_after_loading_minimal_config(self):
        from desktop_forms import BacktestForm
        from quantlab.reporting import demo_config
        from quantlab.core import to_dict
        config = to_dict(demo_config())
        minimal = {'initial_cash':'1','costs':config['costs']}
        form = BacktestForm().from_payload({'config':minimal})
        result = form.build_payload()['config']
        self.assertIsNone(result['initial_margin_per_contract'])
        self.assertEqual(result['max_position'],1)
        for rounding in ('none','floor_twd','ceiling_twd','half_up_twd'):
            config['costs']['tax_rounding'] = rounding
            form.from_payload({'config':config})
            self.assertEqual(form.build_payload()['config']['costs']['tax_rounding'],rounding)

    def test_decimal_precision_and_range_parser(self):
        from desktop_forms import number
        from quantlab.core import ValidationError
        self.assertEqual(number('0.12345678901234567890123456789','費用'),'0.12345678901234567890123456789')
        for bad in ('NaN','sNaN','Infinity','-Infinity','1e1000000','0e-999999','9'*129,'1.1'):
            with self.assertRaises(ValidationError): number(bad,'數量',integer=True)

    def test_campaign_deselection_and_confirm_reset(self):
        from desktop_forms import CampaignForm, PaperActionForm
        from quantlab.core import ValidationError, to_dict
        from quantlab.research import demo_campaign_config
        from quantlab.reporting import synthetic_dataset,demo_config
        config = demo_campaign_config(synthetic_dataset(160),demo_config())
        config['backtest_config'] = to_dict(config['backtest_config'])
        form = CampaignForm().from_payload(config)
        for box in form.families.values(): box.setChecked(False)
        with self.assertRaises(ValidationError): form.build_payload()
        action = PaperActionForm(); action.confirm.setChecked(True)
        action.from_payload({'reconcile_confirmed':True})
        with self.assertRaises(ValidationError): action.build_payload('reconcile')
        self.assertEqual(action.build_payload('kill'),{})
        self.assertEqual(action.build_payload('snapshot'),{})
