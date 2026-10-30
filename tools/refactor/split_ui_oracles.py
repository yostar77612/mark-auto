"""Compare actual pre-split and split native shell construction and normal close."""

from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch


def capture(root, state):
    sys.path.insert(0, str(root))
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QWidget
    from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore, BackupManager, RuntimeGuard
    from desktop_app.shell.main_window import create_window

    app = QApplication.instance() or QApplication([])
    state.mkdir(parents=True, exist_ok=True)
    env = dict(LOCALAPPDATA=str(state / 'local'), APPDATA=str(state / 'roaming'))
    stamp = datetime(2026, 1, 5, 4, 0, tzinfo=timezone.utc)
    with patch.dict(os.environ, env), patch('desktop_app.shell.app_header.CLOCK_OVERRIDE', lambda: stamp):
        paths = AppPaths(state / 'workspace', state / 'bootstrap').ensure()
        manager = JobManager(paths)
        window = create_window(paths, manager, SettingsStore(paths.state / 'settings.json'), BackupManager(paths, manager), RuntimeGuard(paths))
        for timer in window.findChildren(QTimer):
            timer.stop()
        window.show()
        for timer in window.findChildren(QTimer):
            timer.stop()
        app.processEvents()
        controls = []
        for control in window.findChildren(QWidget):
            text = control.text() if isinstance(control, (QLabel, QLineEdit)) else ''
            controls.append((control.objectName(), type(control).__name__, text.replace(str(state), '<TEMP>')))
        snapshot = {
            'title': window.windowTitle(),
            'navigation': [window.navigation.item(i).text() for i in range(window.navigation.count())],
            'pages': window.stack.count(),
            'services': list(window.page_host.callbacks),
            'controls': sorted(controls),
            'status': window.status.text(),
            'active': manager.active,
        }
        manager.close()
        accepted = window.close()
        app.processEvents()
        if not accepted:
            raise AssertionError('Normal close refused: ' + window.status.text())
        snapshot['normal_close'] = accepted
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--capture', type=Path)
    parser.add_argument('--state', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.capture:
        print(json.dumps(capture(args.capture.resolve(), args.state.resolve()), ensure_ascii=False))
        return
    directory = root / '.tmp-layered/slice2-shell-oracle'
    directory.mkdir(exist_ok=True)
    snapshots = {}
    for mode, source in (('baseline', args.baseline.resolve()), ('tree', root)):
        result = subprocess.run(
            [sys.executable, '-B', str(Path(__file__).resolve()), '--capture', str(source), '--state', str(directory / mode)],
            cwd=source,
            capture_output=True,
            text=True,
            encoding='utf-8',
            env=dict(os.environ, PYTHONUTF8='1', QT_QPA_PLATFORM='offscreen', PYTHONDONTWRITEBYTECODE='1'),
            check=True,
        )
        snapshots[mode] = json.loads(result.stdout)
    (directory / 'observations.json').write_text(json.dumps(snapshots, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    changed = [key for key in snapshots['baseline'] if snapshots['baseline'][key] != snapshots['tree'][key]]
    if changed:
        raise AssertionError('Native window changed: ' + repr(changed))
    print(json.dumps({'controls': len(snapshots['tree']['controls']), 'services': len(snapshots['tree']['services']), 'normal_close': True, 'equal': True}))


if __name__ == '__main__':
    main()
