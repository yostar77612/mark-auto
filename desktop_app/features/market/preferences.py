from copy import deepcopy
from quantlab.chart_data import TIMEFRAMES
from desktop_app.features.market.chart_memory import ChartMemory
from desktop_app.features.market.indicator_presenter import DEFAULT_INDICATORS
from desktop_app.features.market.rows import _identity


class MarketPreferences:
    def __init__(self, view):
        self.view = view

    def preferences(self):
        memory = self.view._prepare_chart_memory()
        memory.capture(self.view)
        return {
            'version': 1,
            'watchlist': list(self.view._watch),
            'selected': self.view._selected,
            'timeframe': self.view._timeframe,
            'indicators': deepcopy(self.view._indicator_config),
            'theme': 'dark',
            'converge_annotations': self.view.converge_annotations.isChecked(),
            'chart_state': memory.payload(),
        }

    def _prepare_chart_memory(self):
        if not hasattr(self.view, '_view_memory'):
            self.view._view_memory = ChartMemory(_identity, TIMEFRAMES, DEFAULT_INDICATORS)
        return self.view._view_memory

    def restore_preferences(self, payload):
        if (
            not isinstance(payload, dict)
            or set(payload) - {'version', 'watchlist', 'selected', 'timeframe', 'indicators', 'theme', 'converge_annotations', 'chart_state'}
            or type(payload.get('version')) is not int
            or (payload.get('version') != 1)
        ):
            raise ValueError('unsupported preferences')
        watch = payload.get('watchlist', [])
        selected = payload.get('selected', '')
        timeframe = payload.get('timeframe', '1d')
        config = deepcopy(payload.get('indicators', DEFAULT_INDICATORS))
        convergence = payload.get('converge_annotations', True)
        if type(convergence) is not bool:
            raise ValueError('invalid annotation convergence')
        if not isinstance(watch, list) or len(watch) > 100 or any((not _identity(x) for x in watch)) or (len(set(watch)) != len(watch)):
            raise ValueError('invalid watchlist')
        if selected and (not _identity(selected)) or not isinstance(selected, str) or timeframe not in TIMEFRAMES or (payload.get('theme', 'dark') != 'dark'):
            raise ValueError('invalid selection/theme')
        if (
            not isinstance(config, dict)
            or set(config) - set(DEFAULT_INDICATORS)
            or (not set(DEFAULT_INDICATORS).difference({'ATR', 'SuperTrend', 'SAR', 'OBV', 'MA channel'}) <= set(config))
        ):
            raise ValueError('invalid indicators')
        for key in ('ATR', 'SuperTrend', 'SAR', 'OBV', 'MA channel'):
            config.setdefault(key, deepcopy(DEFAULT_INDICATORS[key]))
        for key, default in DEFAULT_INDICATORS.items():
            entry = config[key]
            if not isinstance(entry, dict) or set(entry) != set(default) or type(entry['enabled']) is not bool:
                raise ValueError('invalid indicator shape')
            for param, value in entry.items():
                if param == 'enabled':
                    continue
                values = value if param == 'periods' and isinstance(value, list) else [value]
                if param == 'periods' and (not isinstance(value, list) or len(value) != 4):
                    raise ValueError('four MA periods required')
                if any(
                    (
                        type(v) not in ((int, float) if param in ('deviations', 'multiplier', 'step', 'maximum', 'percent') else (int,))
                        or not (0.01 if param in ('step', 'maximum') else 0.1 if param in ('deviations', 'multiplier', 'percent') else 1)
                        <= v
                        <= (1 if param in ('step', 'maximum') else 1000)
                        for v in values
                    )
                ):
                    raise ValueError('invalid indicator period')
        if config['SAR']['step'] > config['SAR']['maximum']:
            raise ValueError('invalid SAR acceleration')
        if config['MACD']['fast'] >= config['MACD']['slow']:
            raise ValueError('invalid MACD periods')
        self.view._watch = list(watch)
        self.view._watch_initialized = True
        self.view._selected = selected
        self.view._timeframe = timeframe
        self.view._indicator_config = config
        self.view._view_memory = ChartMemory(_identity, TIMEFRAMES, DEFAULT_INDICATORS, payload.get('chart_state'))
        self.view._restoring = True
        try:
            self.view.converge_annotations.setChecked(convergence)
            self.view.timeframe_combo.blockSignals(True)
            self.view.timeframe_combo.setCurrentIndex(self.view.timeframe_combo.findData(timeframe))
            self.view.timeframe_combo.blockSignals(False)
            for key, (check, controls) in self.view._indicator_widgets.items():
                check.setChecked(config[key]['enabled'])
                for name, spin in controls.items():
                    spin.setValue(config[key]['periods'][int(name[-1])] if name.startswith('periods_') else config[key][name])
        finally:
            self.view._restoring = False
        self.view._fill_contracts()
        self.view._render_watch()
        self.view._render_chart()
