"""Cheap offline B8 contracts: time anchors, isolated storage, history and paint."""

from tools.refactor.split_ui_r3b import window_public_names

import ast
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4

from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from desktop_app.components.charts import CandlestickChart
from quantlab import chart_drawings as cd
from quantlab.chart_data import aggregate_bars
from quantlab.core import content_hash, canonical_json
from quantlab.research import _summary
from tests.test_chart_data import bar, START
from tests.test_backtest import bar as engine_bar, dataset, spec, run
# Source scans below use current physical paths.


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def local_profile():
    # mkdir's inherited ACL avoids Windows sandbox failures from mkdtemp's 0700.
    path = ROOT / ('.b8-test-' + uuid4().hex)
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


def anchor(minute=17, price='2.125'):
    return cd.Anchor(START + timedelta(minutes=minute, seconds=15), D(price))


def series():
    return tuple(replace(bar(i, 2, session_end=START + timedelta(minutes=120)), high=D(3), low=D(1)) for i in range(120))


class DrawingTests(unittest.TestCase):
    def test_strict_immutable_time_price_contract(self):
        a = anchor()
        for value in (17, True, datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=8)))):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cd.Anchor(value, D(2))
        for value in (2, 2.0, True, D(0), D(-1), D('NaN'), D('sNaN'), D('Infinity')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cd.Anchor(a.timestamp, value)
        for cls in (cd.HorizontalLine, cd.TrendLine, cd.Ray, cd.Box):
            args = (a,) if cls is cd.HorizontalLine else (a, anchor(30))
            drawing = cls(*args)
            with self.assertRaises(FrozenInstanceError):
                setattr(drawing, fields(drawing)[0].name, a)
            with self.assertRaises(ValueError):
                cls(*((17,) if cls is cd.HorizontalLine else (17, a)))
            self.assertFalse({'index', 'bar_index'} & {f.name for f in fields(drawing)})
        self.assertFalse({'index', 'bar_index'} & {f.name for f in fields(cd.Anchor)})
        with self.assertRaises(FrozenInstanceError):
            a.price = D(3)

    def test_all_eight_timeframes_containment_and_byte_identical_round_trip(self):
        drawings = (cd.HorizontalLine(anchor()), cd.TrendLine(anchor(), anchor(95)), cd.Ray(anchor(), anchor(50)), cd.Box(anchor(), anchor(75)))
        original = cd.serialize(drawings).encode()
        self.assertEqual(CandlestickChart.timeframes, ('1m', '3m', '5m', '15m', '30m', '60m', '1d', '1w'))
        for timeframe in (*CandlestickChart.timeframes, '1m', '60m', '1m'):
            bars = aggregate_bars(series(), timeframe=timeframe).bars
            for drawing in drawings:
                for a in cd.anchors(drawing):
                    position, price = cd.project_anchor(a, bars)
                    self.assertLessEqual(bars[position].timestamp, a.timestamp)
                    self.assertLess(a.timestamp, bars[position].end)
                    self.assertEqual(price, a.price)
            self.assertEqual(cd.deserialize(original), drawings)
            self.assertEqual(cd.serialize(drawings).encode(), original)

    def test_boundaries_gaps_and_no_date_inference(self):
        bars = series()
        self.assertEqual(cd.project_anchor(cd.Anchor(bars[1].timestamp, D(2)), bars), (1, D(2)))
        self.assertIsNone(cd.project_anchor(anchor(1), (bars[0], bars[2])))
        self.assertIsNone(cd.project_anchor(cd.Anchor(bars[-1].end, D(2)), bars))
        date_only = replace(bars[0], timestamp=None, end=None, interval='1d', session_open=None, session_end=None)
        self.assertIsNone(cd.project_anchor(anchor(), (date_only,)))

    def test_undo_redo_add_move_delete_and_branch(self):
        history = cd.DrawingHistory()
        first, moved = cd.HorizontalLine(anchor()), cd.HorizontalLine(anchor(20, '2.5'))
        self.assertEqual(history.undo(), ())
        self.assertEqual(history.redo(), ())
        history.add(first)
        self.assertEqual(history.undo(), ())
        self.assertEqual(history.redo(), (first,))
        history.move(0, moved)
        self.assertEqual(history.undo(), (first,))
        self.assertEqual(history.redo(), (moved,))
        history.delete(0)
        self.assertEqual(history.undo(), (moved,))
        self.assertEqual(history.redo(), ())
        history.undo()
        history.add(first)
        self.assertEqual(history.redo(), (moved, first))

    def test_history_depth_and_invalid_action_is_transactional(self):
        history = cd.DrawingHistory((cd.HorizontalLine(anchor()),))
        for i in range(cd.MAX_HISTORY + 5):
            history.move(0, cd.HorizontalLine(anchor(price=str(i + 1))))
        for _ in range(cd.MAX_HISTORY):
            history.undo()
        oldest = history.drawings
        self.assertEqual(history.undo(), oldest)
        self.assertEqual(oldest[0].anchor.price, D(5))
        with self.assertRaises(ValueError):
            history.add(123)
        self.assertNotEqual(history.redo(), oldest)

    def test_storage_round_trip_atomic_replace_and_failure_preserves_data(self):
        values = (cd.HorizontalLine(anchor()), cd.TrendLine(anchor(), anchor(22)), cd.Ray(anchor(), anchor(42)), cd.Box(anchor(), anchor(75)))
        with local_profile() as tmp:
            store = cd.DrawingStore(Path(tmp) / 'profile')
            path = store.path_for('TAIFEX:TMF:202610')
            self.assertNotIn('research', path.parts)
            self.assertNotIn('data', path.parts)
            store.save('TAIFEX:TMF:202610', values)
            self.assertEqual(store.load('TAIFEX:TMF:202610'), values)
            old = path.read_bytes()
            real_replace = os.replace

            def observe(source, destination):
                self.assertEqual(Path(source).parent, path.parent)
                self.assertNotEqual(Path(source), path)
                self.assertEqual(path.read_bytes(), old)
                self.assertEqual(cd.deserialize(Path(source).read_bytes()), ())
                real_replace(source, destination)

            with patch.object(cd.os, 'replace', side_effect=observe) as mocked:
                store.save('TAIFEX:TMF:202610', ())
                mocked.assert_called_once()
            with patch.object(cd.os, 'replace', side_effect=OSError('injected failure')):
                with self.assertRaises(OSError):
                    store.save('TAIFEX:TMF:202610', values)
            self.assertEqual(store.load('TAIFEX:TMF:202610'), ())
            self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_reject_bad_payload_without_deleting_user_data(self):
        good = cd.serialize((cd.HorizontalLine(anchor()),))
        payload = json.loads(good)
        oversized = {'version': 1, 'drawings': payload['drawings'] * (cd.MAX_DRAWINGS + 1)}
        invalid = [
            b'\xff',
            b'{',
            good[:-2].encode(),
            good.replace('"version":1', '"version":2').encode(),
            good.replace('horizontal', 'unknown').encode(),
            json.dumps(oversized).encode(),
            b'x' * (cd.MAX_FILE_BYTES + 1),
            b'null',
            b'[]',
            b'{"version":true,"drawings":[]}',
            good.replace('"2.125"', '2.125').encode(),
        ]
        with local_profile() as tmp:
            store = cd.DrawingStore(tmp)
            path = store.path_for('fixture')
            path.parent.mkdir()
            for raw in invalid:
                with self.subTest(raw=raw[:40]):
                    path.write_bytes(raw)
                    self.assertEqual(store.load('fixture'), ())
                    self.assertEqual(path.read_bytes(), raw)
            with self.assertRaises(ValueError):
                store.save('fixture', (cd.HorizontalLine(anchor()),) * (cd.MAX_DRAWINGS + 1))
            self.assertEqual(path.read_bytes(), invalid[-1])
            for forbidden in ('data/research', 'research', 'results', 'hash-bound'):
                with self.assertRaises(ValueError):
                    cd.DrawingStore(Path(tmp) / forbidden)

    def test_hash_isolation_during_create_edit_delete(self):
        data = dataset([engine_bar(i, 20000 + i) for i in range(8)])
        strategy = spec()

        def hashes():
            result = run(data, [(0, 1), (5, 0)], st=strategy)
            return tuple(
                v.encode()
                for v in (content_hash(data), data.manifest['data_hash'], content_hash(strategy), content_hash(result), canonical_json(_summary(result)))
            )

        before = hashes()
        with local_profile() as tmp:
            store = cd.DrawingStore(tmp)
            history = cd.DrawingHistory()
            for action in (lambda: history.add(cd.HorizontalLine(anchor())), lambda: history.move(0, cd.HorizontalLine(anchor(25))), lambda: history.delete(0)):
                action()
                store.save('fixture', history.drawings)
                self.assertEqual(store.load('fixture'), history.drawings)
                self.assertEqual(hashes(), before)
        for name in ('research', 'backtest', 'data', 'core', 'strategies', 'provider'):
            source = (ROOT / 'quantlab' / (name + '.py')).read_text(encoding='utf-8-sig')
            self.assertNotIn('chart_drawings', source)

    def test_model_has_no_qt_or_research_dependency(self):
        source = (ROOT / 'quantlab/chart_drawings.py').read_text(encoding='utf-8')
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                self.assertFalse(any(a.name.startswith(('PySide', 'quantlab')) for a in node.names))
            if isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0)

    def test_public_name_oracle_and_class_size_unchanged(self):
        expected = json.loads((ROOT / 'tests/fixtures/desktop_ui_public_names.json').read_text(encoding='utf-8'))
        self.assertEqual(window_public_names(), expected)
        source = (ROOT / 'desktop_app/components/charts.py').read_text(encoding='utf-8-sig')
        chart = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == 'CandlestickChart')
        self.assertLessEqual(chart.end_lineno - chart.lineno + 1, 500)
        for path in (ROOT / 'desktop_app/shell/main_window.py', *sorted((ROOT / 'desktop_app').rglob('*.py'))):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
                if isinstance(node, ast.ClassDef) and (node.name == 'MainWindow' or node.name.endswith('Page')):
                    self.assertLessEqual(node.end_lineno - node.lineno + 1, 400 if node.name == 'MainWindow' else 500, node.name)


class DrawingPaintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.chart = CandlestickChart()
        self.chart.resize(800, 500)

    def tearDown(self):
        self.chart.close()

    def render(self):
        image = QImage(self.chart.size(), QImage.Format.Format_ARGB32)
        image.fill(0)
        self.chart.render(image, QPoint())
        return image

    def test_offscreen_geometry_for_all_shapes_and_timeframe_switch(self):
        bars = series()
        a, b = anchor(75, '2.4'), anchor(95, '1.6')
        drawings = (cd.HorizontalLine(a), cd.TrendLine(a, b), cd.Ray(a, b), cd.Box(a, b))
        stored = cd.serialize(drawings)
        for timeframe in ('1m', '60m', '1m'):
            aggregated = aggregate_bars(bars, timeframe=timeframe).bars
            self.chart.set_drawings(())
            self.chart.set_timeframe(timeframe)
            self.chart.set_series(aggregated)
            baseline = self.render()
            for drawing in drawings:
                self.chart.set_drawings((drawing,))
                image = self.render()
                self.assertNotEqual(bytes(image.constBits()), bytes(baseline.constBits()))
                position, price = cd.project_anchor(a, aggregated)
                start, end = self.chart.visible_range
                rect = self.chart.price_rect
                # Independent expected scale: source low=1 high=3, padding=0.5.
                xx = rect.left() + (position - start + 0.5) * rect.width() / (end - start)
                yy = rect.bottom() - (float(price) - 0.5) / 3 * rect.height()
                self.assertTrue(
                    any(image.pixelColor(round(xx) + dx, round(yy) + dy).name() == '#64d9df' for dx in (-1, 0, 1) for dy in (-1, 0, 1)),
                    (timeframe, drawing, xx, yy),
                )
            self.assertEqual(cd.serialize(drawings), stored)

    def test_updates_emit_no_market_request_and_keep_market_layers(self):
        self.chart.set_series(series())
        self.chart.set_overlays({'fixture': (D(2),) * len(self.chart.bars)})
        before = (self.chart.bars, self.chart.overlays, self.chart.timeframe)
        requests = []
        self.chart.timeframe_changed.connect(requests.append)
        history = cd.DrawingHistory()
        self.chart.set_drawings(history.add(cd.HorizontalLine(anchor())))
        self.chart.set_drawings(history.move(0, cd.HorizontalLine(anchor(30))))
        self.chart.set_drawings(history.undo())
        self.chart.set_drawings(history.redo())
        self.chart.set_drawings(history.delete(0))
        self.assertEqual(requests, [])
        self.assertEqual((self.chart.bars, self.chart.overlays, self.chart.timeframe), before)
        with self.assertRaises(ValueError):
            self.chart.set_drawings([123])
