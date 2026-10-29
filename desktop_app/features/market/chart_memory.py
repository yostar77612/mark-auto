"""Bounded presentation preferences; no market data or persistent I/O."""

from copy import deepcopy


class ChartMemory:
    LIMIT = 200
    MAX_INDEX = 10_000_000

    def __init__(self, identity, timeframes, indicators, payload=None):
        self.identity = identity
        self.timeframes = timeframes
        self.entries = {}
        self.active = None
        self.edited = set()
        if not isinstance(payload, dict) or type(payload.get('version')) is not int or payload['version'] != 1:
            return
        entries = payload.get('entries')
        if not isinstance(entries, dict):
            return
        for key, value in entries.items():
            if not isinstance(key, str) or len(key) > 80 or key.count('/') != 1:
                continue
            instrument, timeframe = key.split('/')
            if not identity(instrument) or timeframe not in timeframes or not isinstance(value, dict):
                continue
            enabled = value.get('indicators')
            entry = {}
            if isinstance(enabled, list):
                entry['indicators'] = [name for name in indicators if name in enabled]
            zoom = value.get('zoom')
            if (
                isinstance(zoom, dict)
                and all(type(zoom.get(k)) is int and 0 <= zoom[k] <= self.MAX_INDEX for k in ('start', 'count'))
                and 1 <= zoom['count'] <= 600
                and type(zoom.get('latest')) is bool
            ):
                entry['zoom'] = {k: zoom[k] for k in ('start', 'count', 'latest')}
            self.put(key, entry)
            self.edited.add(key)

    def put(self, key, entry):
        if self.entries.get(key) == entry:
            return
        self.entries.pop(key, None)
        self.entries[key] = entry
        while len(self.entries) > self.LIMIT:
            oldest = next(iter(self.entries))
            del self.entries[oldest]
            self.edited.discard(oldest)

    def capture(self, dashboard, *, switching=False):
        chart = dashboard.chart
        if self.active is None or not chart.bars:
            return
        start, end = chart.visible_range
        default_start = max(0, len(chart.bars) - min(chart.MAX_VISIBLE, 100))
        if not switching and self.active not in self.entries and self.active not in self.edited and (start, end) == (default_start, len(chart.bars)):
            return
        self.put(
            self.active,
            {
                'zoom': {'start': start, 'count': end - start, 'latest': end == len(chart.bars)},
                'indicators': [k for k, v in dashboard._indicator_config.items() if v['enabled']],
            },
        )

    def restore(self, dashboard):
        instrument, timeframe = dashboard._selected, dashboard._timeframe
        self.active = f'{instrument}/{timeframe}' if self.identity(instrument) and timeframe in self.timeframes else None
        entry = self.entries.get(self.active, {})
        enabled = entry.get('indicators')
        if enabled is not None:
            for key, value in dashboard._indicator_config.items():
                value['enabled'] = key in enabled
            dashboard._restore_indicator_controls()
        chart = dashboard.chart
        zoom = entry.get('zoom')
        if zoom and chart.bars:
            chart._count = min(zoom['count'], len(chart.bars), chart.MAX_VISIBLE)
            last = max(0, len(chart.bars) - chart._count)
            chart._start = last if zoom['latest'] else min(last, zoom['start'])
            chart.update()

    def payload(self):
        return {'version': 1, 'entries': deepcopy(self.entries)}

    def indicators_edited(self, config, previous):
        # Parameters remain global preferences. Untouched default contexts follow
        # parameter edits; explicit per-context enablement stays independent.
        if any({k: v for k, v in config[name].items() if k != 'enabled'} != {k: v for k, v in previous[name].items() if k != 'enabled'} for name in config):
            for key, entry in self.entries.items():
                if key not in self.edited:
                    entry.pop('indicators', None)
        if self.active is not None:
            self.edited.add(self.active)
