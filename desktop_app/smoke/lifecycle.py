"""Offline smoke lifecycle; ordered fixture/evidence behavior is preserved."""

from __future__ import annotations

import sys


def _start_smoke_job(manager, operation, payload):
    # Every smoke job needs the existing bounded whole-subtree join protocol,
    # including ordinary fixture jobs which do not normally require that proof.
    try:
        return manager.start(operation, payload)
    finally:
        if manager.active:
            manager._requires_tree_quiescence = True


def _close_smoke_worker(manager):
    """Bounded cleanup evidence; process-local owner/join proof cannot be guessed."""
    if manager is None:
        return {'verified': True, 'error_type': None}
    error_type = None
    try:
        if manager.active:
            manager._requires_tree_quiescence = True
            if sys.platform == 'win32' and manager.tree is None:
                raise RuntimeError('Missing isolated worker tree')
        manager.close()
    except BaseException as exc:
        error_type = type(exc).__name__
    verified = error_type is None and not manager.active
    if manager._walk_forward_reference is not None:
        verified = verified and manager._quiesced_walk_forward == (manager.job_id, manager._walk_forward_reference)
    elif manager._requires_tree_quiescence:
        verified = verified and manager._tree_quiesced
    return {'verified': bool(verified), 'error_type': error_type}


def _retain_smoke_directory(directory):
    # An uncertain writer/owner forbids deleting its evidence. TemporaryDirectory
    # otherwise removes it at interpreter shutdown even when cleanup is skipped.
    if directory is not None:
        directory._finalizer.detach()
