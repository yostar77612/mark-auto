"""Synthetic capture instruments for the R7 behavior-preserving split."""

import ast
from contextlib import ExitStack
from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage, QPainter, QFont
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QAbstractButton, QTableWidget
import shiboken6

from desktop_charts import CandlestickChart, ChartTrace, ChartMarker, ReferenceLine
from desktop_pages import mount, result_layers
from tests.test_chart_data import bar, START
from desktop_strings import ui_text
from tests.test_t9_onboarding import sandbox_ui

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    'desktop_pages/mount.py': ('mount_pages', None),
    'desktop_market.py': ('__init__', 'MarketDashboard'),
    'desktop_charts.py': ('paintEvent', 'CandlestickChart'),
    'desktop_pages/result_layers.py': ('result_snapshot_lines', None),
    'desktop_pages/views.py': ('refresh_views', 'ViewCoordinator'),
}


def public_names(source):
    tree = ast.parse(source)

    def names(body):
        result = []
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                result.append(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                result.extend(a.asname or a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.Assign):
                result.extend(t.id for t in node.targets if isinstance(t, ast.Name))
        return sorted(n for n in result if not n.startswith('_'))

    return [names(tree.body), {n.name: names(n.body) for n in tree.body if isinstance(n, ast.ClassDef) and not n.name.startswith('_')}]


class Token:
    def __init__(self, name, events):
        object.__setattr__(self, 'name', name)
        object.__setattr__(self, 'events', events)

    def __getattr__(self, name):
        return Token(self.name + '.' + name, self.events)

    def __setattr__(self, name, value):
        self.events.append([self.name, name, value.name if isinstance(value, Token) else type(value).__name__])
        object.__setattr__(self, name, value)

    def __call__(self, *args, **kwargs):
        self.events.append(['call', self.name])


class Callbacks(dict):
    def __init__(self, events):
        super().__init__()
        self.events = events

    def __setitem__(self, name, value):
        self.events.append(['callbacks', name])
        super().__setitem__(name, value)

    def update(self, values):
        self.events.append(['callbacks', 'update'])
        for name, value in values.items():
            self[name] = value


def mount_capture(step=None):
    events = []
    shell, host, state = (Token(n, events) for n in ('shell', 'host', 'state'))
    object.__setattr__(shell, 'page_host', host)
    object.__setattr__(host, 'state', state)
    object.__setattr__(host, 'callbacks', Callbacks(events))
    object.__setattr__(shell, 'page_services', lambda: {'service': lambda: None})
    with ExitStack() as stack:
        for name in ('WidgetTools', 'MarketPage', 'DataPage', 'StrategyPage', 'BacktestPage', 'ComparePage', 'PaperPage', 'SettingsPage', 'ViewCoordinator'):

            def construct(*args, name=name):
                events.append(['construct', name])
                return Token(name, events)

            stack.enter_context(patch.object(mount, name, construct))
        (step or mount.mount_pages)(shell)
    return events, list(host.callbacks), shell


def chart_capture(kind):
    chart = CandlestickChart()
    chart.setFont(QFont('DejaVu Sans', 10))
    chart.resize(800, 480)
    counts = {'save': 0, 'restore': 0}

    class Painter(QPainter):
        def save(self):
            counts['save'] += 1
            return super().save()

        def restore(self):
            counts['restore'] += 1
            return super().restore()

    try:
        if kind:
            bars = tuple(bar(i, 100 + i % 7, session_end=START + timedelta(minutes=60)) for i in range(40))
            trace = ChartTrace(bars[0].contract_id, 'a' * 64, 'b' * 64, ui_text('charts.__post_init__.text_1'))
            chart.set_series(bars, trace=trace, source_label='synthetic', status_label='fixture')
            if kind == 2:
                # Keep this dependency local to the stage that uses it.
                from quantlab.chart_drawings import Anchor, HorizontalLine

                chart.set_overlays({'MA': [102] * 40}, panes={'hist': [i % 5 - 2 for i in range(40)]}, pane_styles={'hist': 'histogram'})
                chart.set_drawings((HorizontalLine(Anchor(bars[10].timestamp, Decimal(103))),))
                chart.set_markers((ChartMarker(12, 'fill', 'entry', Decimal(102), 1), ChartMarker(15, 'signal', 'intent')), trace=trace)
                chart.set_reference_lines((ReferenceLine('reference', Decimal(104)), ReferenceLine('snapshot', Decimal(102), 20, bars[20].end)), trace=trace)
                chart.crosshair_index = 20
            if kind == 3:
                chart.set_series(bars, source_label='synthetic', status_label='fixture')
                chart.set_paper_snapshot(
                    {
                        'verification': 'synthetic_paper_only',
                        'account_id': 'fixture',
                        'orders': {
                            'order': {
                                'status': 'accepted',
                                'filled_quantity': 0,
                                'intent': {'side': 'buy', 'quantity': 2, 'limit_price': '104', 'contract_id': bars[0].contract_id, 'order_type': 'limit'},
                            }
                        },
                    }
                )
        image = QImage(chart.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        with patch('desktop_charts.QPainter', Painter):
            chart.render(image)
        return [sha256(bytes(image.constBits())).hexdigest(), counts]
    finally:
        shiboken6.delete(chart)


def snapshot_cases():
    # Keep this dependency local to the stage that uses it.
    from tests.test_result_reference_layers import fixture

    # Keep this dependency local to the stage that uses it.
    from tests.test_backtest import run

    data, result, _ = fixture(mtm=True)
    cid = data.bars[0].contract_id
    cases = [
        (replace(result, equity=()), data.bars, cid),
        (run(data, []), data.bars, cid),
        (result, data.bars, cid),
        (result, (), cid),
        (replace(result, rejects=({'reason': 'warning'},)), data.bars, cid),
        (result, data.bars, 'long-name-' * 30),
        (result, data.bars, '\u5408\u7d04'),
        (result, data.bars, None),
    ]
    return cases


def snapshot_capture():
    return [
        [
            {**asdict(line), 'price': str(line.price), 'as_of': line.as_of.isoformat() if line.as_of else None}
            for line in result_layers.result_snapshot_lines(*case)
        ]
        for case in snapshot_cases()
    ]


def window_capture():
    # Keep this dependency local to the stage that uses it.
    import tempfile

    # Keep this dependency local to the stage that uses it.
    from desktop_ui import MainWindow

    # Keep this dependency local to the stage that uses it.
    from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore

    # Keep this dependency local to the stage that uses it.
    from quantlab.reporting import save_dataset, export_report

    # Keep this dependency local to the stage that uses it.
    from tests.test_backtest import bar as engine_bar, dataset, run

    # Keep this dependency local to the stage that uses it.
    from datetime import datetime, timezone

    with (
        sandbox_ui(),
        patch('desktop_pages.app_header.CLOCK_OVERRIDE', lambda: datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)),
        tempfile.TemporaryDirectory(prefix='r7-capture-') as folder,
    ):
        paths = AppPaths(Path(folder) / 'workspace').ensure()
        jobs = JobManager(paths)
        window = MainWindow(paths, jobs, SettingsStore(paths.state / 'settings.json'))
        try:
            for timer in window.findChildren(QTimer):
                timer.stop()
            attrs, keys = sorted(vars(window)), list(window.page_host.callbacks)
            focus = []
            current = window
            while True:
                if current.objectName():
                    focus.append([current.objectName(), current.accessibleName(), current.accessibleDescription()])
                current = current.nextInFocusChain()
                if current is window:
                    break
            states, calls = [], []
            coordinator = window.views_page
            data = dataset([engine_bar(i, 20000 + i) for i in range(4)])
            for kind in range(4):
                if kind == 1:
                    save_dataset(data, paths.state / 'dataset.json')
                if kind == 2:
                    export_report(run(data, [(0, 1)]), paths.state / 'reports')
                if kind == 3:
                    with patch.object(window.paper_page, '_quiesce_and_recover'):
                        window.freeze_paper('synthetic')
                order = []
                with ExitStack() as stack:
                    for name in (
                        '_refresh_walk_forward_references',
                        '_refresh_analysis_saved',
                        'load_market_cache',
                        'show_result',
                        'inspect_candidate',
                        '_refresh_recovery_controls',
                    ):
                        original = getattr(coordinator, name)

                        def record(*args, name=name, original=original, **kwargs):
                            order.append(name)
                            return original(*args, **kwargs)

                        stack.enter_context(patch.object(coordinator, name, record))
                    window.refresh_views()
                calls.append(order)
                states.append(
                    [
                        [
                            w.objectName(),
                            w.text() if isinstance(w, (QLabel, QAbstractButton)) else [w.rowCount(), w.columnCount()],
                            w.isEnabled(),
                            w.isVisible(),
                        ]
                        for w in window.findChildren(QWidget)
                        if w.objectName() and isinstance(w, (QLabel, QAbstractButton, QTableWidget))
                    ]
                )
            errors = []
            with patch.object(coordinator, '_refresh_analysis_saved', Mock(side_effect=ValueError('synthetic'))):
                try:
                    coordinator.refresh_views()
                except ValueError:
                    errors.append('propagated')
            with patch.dict(window.page_host.callbacks, load_dataset=Mock(side_effect=ValueError('synthetic'))):
                coordinator.refresh_views()
                errors.append(window.overview.text())
            return {'attributes': attrs, 'callbacks': keys, 'focus': focus, 'states': states, 'calls': calls, 'errors': errors}
        finally:
            window.close()
            shiboken6.delete(window)
            jobs.close()


def capture():
    app = QApplication.instance() or QApplication([])
    assert app is not None
    events, keys, _ = mount_capture()
    return {
        'base': '8d84b26',
        'mount': events,
        'stub_callbacks': keys,
        'charts': [chart_capture(i) for i in range(4)],
        'snapshots': snapshot_capture(),
        'window': window_capture(),
        'public': {p: public_names((ROOT / p).read_text(encoding='utf-8-sig')) for p in TARGETS},
    }
