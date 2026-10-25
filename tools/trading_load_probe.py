"""Native Qt/independent-engine load acceptance. Default is 1800 real seconds.

Only creates local synthetic data below a fresh explicit root. A short run is
reported SHORT_VALIDATION, never as the required 30-minute acceptance.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
from decimal import Decimal
import json
import hashlib
import math
import os
from pathlib import Path
import platform
import sys
import sqlite3
from threading import Event, Thread
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from desktop_trading import TradingWindow
from quantlab.trading.application.context import QuoteBatch
from quantlab.trading.application.contracts import StrategyForm, UiAction, UiCommand
from quantlab.trading.domain.models import Environment, HoldingKind, Market, Quote, Side
from quantlab.trading.runtime.build import synthetic_catalog
from quantlab.trading.runtime.ipc import IpcFacade, read_session
from quantlab.trading.runtime.protocol import Operation
import trading_runtime
from tools.trading_load_report import write_report

ROOT = Path(__file__).resolve().parents[1]


def process_memory(pid: int) -> dict[str, int]:
    """Inspect only this probe and the engine process it started."""

    class Memory(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('peak_rss', 'rss', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile', 'private')
        ]

    kernel, psapi = ctypes.WinDLL('kernel32', use_last_error=True), ctypes.WinDLL('psapi', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x0410, False, pid)
    if not handle:
        raise OSError(ctypes.get_last_error(), 'owned process memory unavailable')
    try:
        memory = Memory()
        memory.cb = ctypes.sizeof(memory)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
            raise OSError(ctypes.get_last_error(), 'owned process memory unavailable')
        return {'rss': memory.rss, 'private': memory.private}
    finally:
        kernel.CloseHandle(handle)


def source_identity() -> dict[str, str]:
    paths = [*ROOT.glob('quantlab/trading/**/*.py'), *ROOT.glob('desktop_trading/*.py')]
    paths.extend((ROOT / 'trading_runtime.py', ROOT / 'desktop_strings.py', ROOT / 'tools/trading_load_report.py', Path(__file__).resolve()))
    return {str(path.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}


def machine_specification() -> dict[str, object]:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
            (name, ctypes.c_ulonglong)
            for name in ('physical', 'available_physical', 'pagefile', 'available_pagefile', 'virtual', 'available_virtual', 'extended')
        ]

    value = MemoryStatus()
    value.length = ctypes.sizeof(value)
    function = ctypes.WinDLL('kernel32', use_last_error=True).GlobalMemoryStatusEx
    function.argtypes = [ctypes.POINTER(MemoryStatus)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(value)):
        raise OSError(ctypes.get_last_error(), 'machine memory unavailable')
    return {
        'platform': platform.platform(),
        'processor': platform.processor(),
        'logical_cpus': os.cpu_count(),
        'python': sys.version,
        'sqlite': sqlite3.sqlite_version,
        'physical_memory_bytes': value.physical,
    }


def prepare(facade: IpcFacade) -> dict[str, object]:
    def command(action: UiAction, **values: object):
        receipt = facade.execute(UiCommand(action, facade.snapshot().version, **values))
        if not receipt.accepted:
            raise RuntimeError(f'{action.value} rejected: {receipt.code}')
        return receipt

    command(UiAction.RECONCILE)
    specs = tuple(s for s in synthetic_catalog().instruments if s.market is Market.STOCK)
    references = []
    for index in range(100):
        spec = specs[index % len(specs)]
        form = StrategyForm(
            f'Load candidate {index + 1:03d}',
            Market.STOCK,
            HoldingKind.SWING,
            3,
            5,
            Side.BUY,
            spec.instrument_id,
            'local-stock',
            Environment.LOCAL,
            Decimal('10000'),
            Decimal('0.02'),
            'BUY_AND_HOLD',
        )
        references.append(command(UiAction.CREATE_STRATEGY, strategy=form).reference)
    for reference in references[:5]:
        for action in (UiAction.VALIDATE, UiAction.RESEARCH, UiAction.DEPLOY):
            command(action, target_id=reference)
    command(UiAction.RESUME)
    state = facade.snapshot()
    metrics = facade.request(Operation.METRICS).metrics
    active = tuple(s for s in state.strategies if s.state == 'ACTIVE')
    if len(state.strategies) != 100 or len(active) != 5 or len({s.instrument_id for s in active}) != 5 or metrics.subscription_count != 20:
        raise RuntimeError('load preconditions are not the required 100/20/5')
    return {
        'candidate_count': len(state.strategies),
        'active_strategies': [s.strategy_id for s in active],
        'active_instruments': [s.instrument_id for s in active],
        'subscription_count': metrics.subscription_count,
        'initial_quote_count': metrics.quote_count,
    }


class QuoteProducer(Thread):
    def __init__(self, root: Path, seconds: int, stop: Event):
        super().__init__(name='owned-local-quotes')
        self.root, self.seconds, self.stop = root, seconds, stop
        self.sent = self.acknowledged = 0
        self.error = ''
        self.max_schedule_lag = 0.0

    def run(self) -> None:
        try:
            self.produce()
        except Exception as exc:
            self.error = type(exc).__name__ + ': ' + str(exc)

    def produce(self) -> None:
        facade = IpcFacade(self.root)
        state = facade.snapshot()
        specs = synthetic_catalog().instruments
        prices = {s.instrument_id: s.price for s in state.markets}
        stamp = datetime.fromisoformat(state.markets[0].quote_time)
        last_count = facade.request(Operation.METRICS).metrics.quote_count
        started = time.monotonic()
        for batch_index in range(self.seconds * 10):
            target = started + batch_index / 10
            if self.stop.wait(max(0.0, target - time.monotonic())):
                return
            self.max_schedule_lag = max(self.max_schedule_lag, time.monotonic() - target)
            items = []
            for offset in range(10):
                sequence = batch_index * 10 + offset + 1000
                spec = specs[(batch_index * 10 + offset) % len(specs)]
                price = prices[spec.instrument_id] + spec.tick_size * ((batch_index // 2) % 4)
                items.append(
                    Quote(
                        spec.instrument_id, price, price + spec.tick_size, price, stamp, stamp, stamp.date(), sequence=sequence, source='LOCAL_SYNTHETIC_LOAD'
                    )
                )
            self.sent += len(items)
            after = facade.request(Operation.QUOTES, quotes=QuoteBatch(tuple(items))).metrics.quote_count
            if after - last_count != len(items):
                raise RuntimeError('acknowledged quote count mismatch')
            last_count = after
            self.acknowledged += len(items)
        self.stop.wait(max(0.0, started + self.seconds - time.monotonic()))


class Probe:
    def __init__(self, root: Path, report: Path, seconds: int, facade: IpcFacade, evidence: dict[str, object]):
        self.root, self.report, self.seconds, self.facade, self.evidence = root, report, seconds, facade, evidence
        self.engine_pid = read_session(root).process_id
        self.app = QApplication.instance() or QApplication(sys.argv[:1])
        if self.app.platformName() != 'windows':
            raise RuntimeError('native Windows Qt platform required')
        self.window = TradingWindow(facade, facade.snapshot())
        self.window.setProperty('allow_close_for_tests', True)
        self.window.resize(1366, 768)
        self.window.poll.stop()
        self.window.navigation.setCurrentRow(2)
        self.stop = Event()
        self.producer = QuoteProducer(root, seconds, self.stop)
        self.started = 0.0
        self.pending: float | None = None
        self.latencies: list[float] = []
        self.memory: list[dict[str, object]] = []
        self.errors: list[str] = []
        self.timer = QTimer()
        self.timer.setInterval(5)
        self.timer.timeout.connect(self.tick)
        self.next_refresh = self.next_memory = 0.0
        self.finished = False

    def run(self) -> int:
        self.window.show()
        self.window.activateWindow()
        self.window.setFocus()
        self.app.processEvents()
        self.started = time.monotonic()
        self.producer.start()
        self.timer.start()
        code = self.app.exec()
        if not self.finished:
            self.errors.append('native_window_closed_before_completion')
            self.finish()
            return 1
        return code

    def tick(self) -> None:
        try:
            self.observe()
        except Exception as exc:
            self.errors.append(type(exc).__name__ + ': ' + str(exc))
            self.finish()

    def observe(self) -> None:
        elapsed = time.monotonic() - self.started
        if self.pending is not None and self.window._operation is None:
            self.latencies.append((time.perf_counter() - self.pending) * 1000)
            self.pending = None
            for row, market in enumerate(self.window.state.markets):
                if self.window.markets.item(row, 3).text() != str(market.price):
                    raise RuntimeError('displayed market quote does not match refreshed read model')
        if elapsed >= self.next_refresh and self.pending is None:
            self.next_refresh = elapsed + 1
            self.pending = time.perf_counter()
            QTest.keyClick(self.window, Qt.Key.Key_F5)
            if self.window._operation is None:
                raise RuntimeError('native F5 did not start the UI refresh operation')
        if elapsed >= self.next_memory:
            self.next_memory = elapsed + 10
            pid = read_session(self.root).process_id
            if trading_runtime._STARTED[self.root.resolve()].pid != pid:
                raise RuntimeError('engine ownership changed')
            self.memory.append({'seconds': elapsed, 'ui': process_memory(os.getpid()), 'engine': process_memory(pid)})
            write_report(self.report, self.result('RUNNING'))
        if self.producer.error:
            raise RuntimeError(self.producer.error)
        if elapsed >= self.seconds and not self.producer.is_alive() and self.pending is None:
            self.finish()

    def result(self, status: str) -> dict[str, object]:
        ordered = sorted(self.latencies)
        p95 = ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)] if ordered else None
        return {
            'schema_version': 2,
            'status': status,
            'required_duration_seconds': 1800,
            'requested_duration_seconds': self.seconds,
            'elapsed_seconds': time.monotonic() - self.started,
            'started_utc': self.evidence['started_utc'],
            'machine': self.evidence['machine'],
            'source_files_sha256': self.evidence['source_files_sha256'],
            'isolated_root': str(self.root),
            'ui_process_id': os.getpid(),
            'engine_process_id': self.engine_pid,
            'load': self.evidence['load'],
            'sent_quotes': self.producer.sent,
            'acknowledged_quotes': self.producer.acknowledged,
            'target_quotes': self.seconds * 100,
            'max_quote_schedule_lag_seconds': self.producer.max_schedule_lag,
            'quote_schedule_lag_limit_seconds': 1,
            'refresh_samples_ms': self.latencies,
            'refresh_p95_ms': p95,
            'refresh_limit_ms': 300,
            'memory_samples': self.memory,
            'errors': self.errors,
            'native_qt_platform': self.app.platformName(),
            'window': {
                'width': self.window.width(),
                'height': self.window.height(),
                'device_pixel_ratio': self.window.devicePixelRatioF(),
                'screen_width': self.window.screen().geometry().width(),
                'screen_height': self.window.screen().geometry().height(),
                'screen_dpi': self.window.screen().logicalDotsPerInch(),
            },
            'synthetic_clock': 'fixed explicit local lab clock; source is not a live exchange',
            'real_orders': False,
        }

    def finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        self.timer.stop()
        self.stop.set()
        self.producer.join(12)
        self.pending = None
        report = self.result('EVALUATING')
        metrics = self.facade.request(Operation.METRICS).metrics
        report['final_quote_count'] = metrics.quote_count
        report['quote_delta'] = metrics.quote_count - self.evidence['load']['initial_quote_count']
        bounds = self.memory_bounds()
        report['memory_bounds'] = bounds
        report['source_unchanged'] = source_identity() == self.evidence['source_files_sha256']
        passed = not self.errors and not self.producer.error and self.producer.sent == self.seconds * 100 and self.producer.acknowledged == self.producer.sent
        passed = (
            passed
            and report['source_unchanged']
            and report['quote_delta'] == self.producer.sent
            and report['refresh_p95_ms'] is not None
            and report['refresh_p95_ms'] <= 300
            and bounds['passed']
            and self.producer.max_schedule_lag <= 1
        )
        report['status'] = 'PASS' if passed and self.seconds == 1800 else 'SHORT_VALIDATION_PASS' if passed else 'FAIL'
        report['acceptance_30_minutes'] = bool(passed and self.seconds == 1800)
        write_report(self.report, report)
        if self.window._operation is not None:
            self.window._operation.wait(12000)
            self.app.processEvents()
        self.window.close()
        self.app.exit(0 if passed else 1)

    def memory_bounds(self) -> dict[str, object]:
        warm = [sample for sample in self.memory if sample['seconds'] >= min(60, self.seconds / 4)] or self.memory
        changes = {
            role: {kind: max((s[role][kind] for s in warm), default=0) - min((s[role][kind] for s in warm), default=0) for kind in ('private', 'rss')}
            for role in ('ui', 'engine')
        }
        slopes = {}
        for role in ('ui', 'engine'):
            tail = warm[-max(2, len(warm) // 4) :]
            span = tail[-1]['seconds'] - tail[0]['seconds'] if len(tail) > 1 else 0
            slopes[role] = {kind: (tail[-1][role][kind] - tail[0][role][kind]) * 60 / span if span else 0 for kind in ('private', 'rss')}
        return {
            'observed_growth_bytes': changes,
            'growth_limit_bytes': 64 * 1024 * 1024,
            'tail_slope_bytes_per_minute': slopes,
            'tail_slope_limit_bytes_per_minute': 1024 * 1024,
            'passed': all(v <= 64 * 1024 * 1024 for values in changes.values() for v in values.values())
            and all(v <= 1024 * 1024 for values in slopes.values() for v in values.values()),
        }


def cleanup_owned_engine(root: Path, report: Path, initialized: bool) -> None:
    process = trading_runtime._STARTED.get(root)
    try:
        if initialized:
            trading_runtime.shutdown(root)
        elif process is not None:
            if process.poll() is None:
                process.terminate()  # Only the fresh isolated child this probe owns.
            process.wait(timeout=5)
            trading_runtime._STARTED.pop(root, None)
    except Exception:
        if report.exists():
            saved = json.loads(report.read_text(encoding='utf-8'))
            saved.update(status='FAIL', acceptance_30_minutes=False, shutdown_verified=False)
            write_report(report, saved)
        raise
    if report.exists():
        saved = json.loads(report.read_text(encoding='utf-8'))
        saved['owned_engine_exit_code'] = process.poll() if process is not None else None
        saved['shutdown_verified'] = initialized and process is not None and process.poll() == 0 and not (root / 'engine-session-v2.json').exists()
        write_report(report, saved)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=1800)
    args = parser.parse_args()
    root, report = args.root.resolve(), args.report.resolve()
    if os.name != 'nt' or os.environ.get('QT_QPA_PLATFORM') in ('offscreen', 'minimal'):
        raise SystemExit('This acceptance requires native Windows Qt.')
    if not 1 <= args.seconds <= 1800 or root.exists() or report.exists() or not root.is_relative_to(ROOT.parent / 't') or root.is_symlink():
        raise SystemExit('Use a fresh absolute isolated root below workspace/t and 1..1800 seconds.')
    report.parent.mkdir(parents=True, exist_ok=True)
    facade = None
    try:
        facade = trading_runtime.ensure_engine(root)
        evidence = {
            'started_utc': datetime.now(timezone.utc).isoformat(),
            'machine': machine_specification(),
            'source_files_sha256': source_identity(),
            'load': prepare(facade),
        }
        return Probe(root, report, args.seconds, facade, evidence).run()
    except Exception as exc:
        if not report.exists():
            write_report(
                report,
                {
                    'schema_version': 2,
                    'status': 'FAIL',
                    'acceptance_30_minutes': False,
                    'isolated_root': str(root),
                    'requested_duration_seconds': args.seconds,
                    'errors': [type(exc).__name__ + ': ' + str(exc)],
                    'phase': 'setup-or-native-ui',
                },
            )
        raise
    finally:
        cleanup_owned_engine(root, report, facade is not None)


if __name__ == '__main__':
    raise SystemExit(main())
