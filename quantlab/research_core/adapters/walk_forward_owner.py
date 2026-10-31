"""Durable original-writer ownership evidence; never grants recovery alone."""

import os
from quantlab.shared.runtime_errors import RuntimeSafetyError
from .state_json import _json_bytes, _read_json


class WalkForwardOwner:
    def __init__(self, paths, check_regular_path):
        self.paths = paths
        self.check_regular_path = check_regular_path

    def _walk_forward_owner_path(self, reference):
        folder = self.paths.state / 'walk_forward' / reference
        for path in (self.paths.state, folder.parent, folder):
            if path.exists() or path.is_symlink():
                self.check_regular_path(path)
                if not path.is_dir():
                    raise RuntimeSafetyError('Invalid walk-forward state directory')
        return folder / '.desktop-run-owner.json'

    def _claim_walk_forward(self, reference, job_id):
        """One original desktop writer, even across concurrent managers/restarts.

        Keep the marker after failure or cancellation; it grants no authority
        by itself and must never turn a failed launch into an evaluation retry.
        """
        owner = self._walk_forward_owner_path(reference)
        owner.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(owner, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise RuntimeSafetyError('Walk-forward run already claimed; use read without retry') from exc
        with os.fdopen(fd, 'wb') as stream:
            stream.write(_json_bytes({'kind': 'desktop_walk_forward_owner_v1', 'job_id': job_id, 'reference': reference}))
            stream.flush()
            os.fsync(stream.fileno())
        # A pre-existing writer is never adopted as this worker's descendants.
        if (owner.parent / 'walk_forward.sqlite3').exists():
            raise RuntimeSafetyError('Existing walk-forward journals are read-only; use read')

    def _check_walk_forward_owner(self, job_id, reference):
        owner = self._walk_forward_owner_path(reference)
        try:
            self.check_regular_path(owner)
            value = _read_json(owner)
        except (OSError, RuntimeSafetyError) as exc:
            raise RuntimeSafetyError('Walk-forward original run ownership cannot be verified') from exc
        if value != {'kind': 'desktop_walk_forward_owner_v1', 'job_id': job_id, 'reference': reference}:
            raise RuntimeSafetyError('Walk-forward original run ownership mismatch')
