"""Existing backup worker use cases; concrete dependencies arrive through ports."""

from quantlab.research_core.ports.ui_operations import UiOperationPorts
from pathlib import Path


def _handle_ui_backup_create(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    manager = ports.backups.BackupManager(paths)
    return {'backup': str(manager.create(Path(payload['path'])))}


def _handle_ui_backup_restore(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    manager = ports.backups.BackupManager(paths)
    manager.restore(Path(payload['path']))
    return {'restored': True, 'reconciliation_required': True}
