from desktop_app.strings.catalog import ui_text
from PySide6.QtCore import QSignalBlocker
from quantlab import indicators

DEFAULT_INDICATORS = {
    'MA': {'enabled': True, 'periods': [5, 10, 20, 60]},
    'EMA': {'enabled': False, 'period': 20},
    'RSI': {'enabled': False, 'period': 14},
    'MACD': {'enabled': False, 'fast': 12, 'slow': 26, 'signal': 9},
    'KD': {'enabled': False, 'period': 9, 'k_period': 3, 'd_period': 3},
    'Bollinger': {'enabled': False, 'period': 20, 'deviations': 2},
    'VWAP': {'enabled': False},
    'ATR': {'enabled': False, 'period': 14},
    'SuperTrend': {'enabled': False, 'period': 10, 'multiplier': 3},
    'SAR': {'enabled': False, 'step': 0.02, 'maximum': 0.2},
    'OBV': {'enabled': False},
    'MA channel': {'enabled': False, 'period': 20, 'percent': 2},
}


class IndicatorPresenter:
    def __init__(self, view):
        self.view = view

    def _indicators_changed(self, *args):
        if self.view._restoring:
            return
        config = {}
        for key, (check, controls) in self.view._indicator_widgets.items():
            value = {'enabled': check.isChecked()}
            if key == 'MA':
                value['periods'] = [controls[f'periods_{i}'].value() for i in range(4)]
            else:
                value.update({name: spin.value() for name, spin in controls.items()})
            config[key] = value
        if config['SAR']['step'] > config['SAR']['maximum']:
            self.view._restore_indicator_controls()
            self.view.message.setText(ui_text('market.indicator.invalid_sar'))
            return
        if config['MACD']['fast'] >= config['MACD']['slow']:
            self.view._restore_indicator_controls()
            self.view.message.setText(ui_text('market.indicators_changed.invalid_macd'))
            return
        changed = {key for key in config if config[key] != self.view._indicator_config[key]}
        failures = self.view._apply_indicators(config, reject_failures=changed)
        if failures:
            self.view._restore_indicator_controls()
            self.view.message.setText(ui_text('market.indicators_changed.restored_parameters').format(self.view._indicator_failure_text(failures)))
            return
        self.view._prepare_chart_memory().indicators_edited(config, self.view._indicator_config)
        self.view._indicator_config = config
        self.view.preferences_changed.emit()

    def _restore_indicator_controls(self):
        widgets = [widget for check, controls in self.view._indicator_widgets.values() for widget in (check, *controls.values())]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        try:
            for key, (check, controls) in self.view._indicator_widgets.items():
                check.setChecked(self.view._indicator_config[key]['enabled'])
                for name, spin in controls.items():
                    value = (
                        self.view._indicator_config[key]['periods'][int(name[-1])] if name.startswith('periods_') else self.view._indicator_config[key][name]
                    )
                    spin.setValue(value)
        finally:
            for blocker in blockers:
                blocker.unblock()

    def _apply_indicators(self, config=None, *, reject_failures=()):
        bars = getattr(self.view, '_display_bars', ())
        closes = []
        highs = []
        lows = []
        keep = []
        volumes = []
        for index, bar in enumerate(bars):
            previous = bars[index - 1] if index else None
            if (
                previous is not None
                and bar.interval.endswith('m')
                and ((bar.trade_date, bar.session, bar.session_open) == (previous.trade_date, previous.session, previous.session_open))
                and (bar.timestamp > previous.end)
            ):
                volumes.append(None)
                closes.append(None)
                highs.append(None)
                lows.append(None)
            keep.append(len(closes))
            volumes.append(bar.volume)
            closes.append(bar.close)
            highs.append(bar.high)
            lows.append(bar.low)
        overlays = {}
        panels = {}
        names = []
        failures = []
        for key, options in (self.view._indicator_config if config is None else config).items():
            if not options['enabled']:
                continue
            label = {
                'ATR': lambda: ui_text('market.indicator.atr').format(options['period']),
                'SuperTrend': lambda: ui_text('market.indicator.supertrend').format(options['period'], format(options['multiplier'], 'g')),
                'SAR': lambda: ui_text('market.indicator.sar').format(format(options['step'], 'g'), format(options['maximum'], 'g')),
                'OBV': lambda: ui_text('market.indicator.obv'),
                'MA channel': lambda: ui_text('market.indicator.channel').format(options['period'], format(options['percent'], 'g')),
            }.get(key, lambda: key)()
            names.append((key, label))
            kwargs = {k: v for k, v in options.items() if k != 'enabled'}
            try:
                if key == 'MA':
                    for period in kwargs['periods']:
                        overlays[f'MA{period}'] = indicators.sma(closes, period=period)
                elif key == 'EMA':
                    overlays['EMA'] = indicators.ema(closes, **kwargs)
                elif key == 'RSI':
                    panels['RSI'] = {'RSI': indicators.rsi(closes, **kwargs)}
                elif key == 'MACD':
                    panels['MACD'] = indicators.macd(closes, **kwargs)
                elif key == 'KD':
                    panels['KD'] = indicators.kd(highs, lows, closes, **kwargs)
                elif key == 'Bollinger':
                    overlays.update({'BB ' + k: v for k, v in indicators.bollinger(closes, **kwargs).items()})
                elif key == 'ATR':
                    panels[label] = {'': indicators.atr(highs, lows, closes, **kwargs)}
                elif key == 'OBV':
                    panels[label] = {'': indicators.obv(closes, volumes)}
                elif key == 'SuperTrend':
                    overlays[label] = indicators.supertrend(highs, lows, closes, **kwargs)
                elif key == 'SAR':
                    overlays[label] = indicators.sar(highs, lows, closes, **kwargs)
                elif key == 'MA channel':
                    for band, values in indicators.ma_channel(closes, **kwargs).items():
                        overlays[ui_text('market.indicator.band').format(label, band)] = values
                elif key == 'VWAP':
                    overlays[ui_text('market.apply_indicators.vwap_estimate')] = indicators.session_vwap(bars)
            except indicators.IndicatorResourceLimitError:
                failures.append(key)
        rejected = tuple((key for key in failures if key in reject_failures))
        if rejected:
            return rejected
        summary = ' / '.join((label + (ui_text('market.apply_indicators.calculation_failed') if key in failures else '') for key, label in names)) or ui_text(
            'market.apply_indicators.indicators_disabled'
        )
        self.view.indicator_summary.setText(ui_text('market.apply_indicators.warmup_hint').format(summary))
        overlays = {
            name: values if name == ui_text('market.apply_indicators.vwap_estimate') else tuple((values[i] for i in keep)) for name, values in overlays.items()
        }
        panes = {f'{panel} {key}'.rstrip(): tuple((values[i] for i in keep)) for panel, entries in panels.items() for key, values in entries.items()}
        if 'MACD histogram' in panes:
            panes['MACD histogram 1×'] = panes.pop('MACD histogram')
        self.view.chart.set_overlays(overlays, panes=panes, pane_styles={'MACD histogram 1×': 'histogram'} if 'MACD histogram 1×' in panes else {})
        message = getattr(self.view, '_indicator_message_base', ui_text('market.apply_indicators.historical_not_live'))
        self.view.message.setText(
            message + (ui_text('market.apply_indicators.omitted_indicators').format(self.view._indicator_failure_text(failures)) if failures else '')
        )
        self.view.chart.display_changed.emit()
        return ()

    def refresh_annotations(self):
        if self.view.drawing_store is not None:
            self.view.chart.set_drawings(
                self.view.drawing_store.load(self.view._selected, enabled=self.view.converge_annotations.isChecked()) if self.view._selected else ()
            )

    def _annotation_preferences_changed(self):
        if not self.view._restoring:
            self.view.refresh_annotations()
            self.view.preferences_changed.emit()
