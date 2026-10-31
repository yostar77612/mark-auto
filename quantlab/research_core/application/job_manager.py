"""Runtime responsibility extracted with safety ordering preserved."""

from __future__ import annotations

import importlib
import time
import uuid
from quantlab.shared.runtime_errors import RuntimeSafetyError
from quantlab.research_core.ports.jobs import JobProcessPort, JobStoragePort, JobEventLogPort
from quantlab.research_core.domain.job_protocol import DEFAULT_JOB_PORT_FACTORY, OPERATIONS, UI_OPERATIONS, ANALYSIS_OPERATIONS, WALK_FORWARD_OPERATIONS


class JobManager:
    """One spawned bounded-IPC task at a time; no arbitrary callable execution."""

    def __init__(
        self,
        paths,
        *,
        process_port: JobProcessPort | None = None,
        storage_port: JobStoragePort | None = None,
        event_log: JobEventLogPort | None = None,
        default_factory=DEFAULT_JOB_PORT_FACTORY,
    ):
        self.paths = paths.ensure()
        if process_port is None or storage_port is None or event_log is None:
            module, name = default_factory.split(':')
            defaults = getattr(importlib.import_module(module), name)(self.paths)
            process_port = defaults[0] if process_port is None else process_port
            storage_port = defaults[1] if storage_port is None else storage_port
            event_log = defaults[2] if event_log is None else event_log
        self.process_port, self.storage_port = process_port, storage_port
        self.process = self.receiver = self.tree = None
        self.job_id = None
        self._terminal = False
        self._pipe_eof = False
        self._pending = []
        self._deferred = []
        self.event_log = event_log
        self._operation = None
        self.logging_enabled = True
        self._deadline = None
        self._auth_request_id = None
        self._requires_tree_quiescence = False
        self._subscription_job = False
        self._quiesced_subscription_id = None
        self._analysis_job_identity = None
        self._analysis_result_reference = None
        self._quiesced_analysis = None
        # This proof is deliberately process-local. An on-disk running journal,
        # a caller-provided flag, or a restarted manager cannot establish it.
        self._walk_forward_reference = None
        self._walk_forward_result_reference = None
        self._quiesced_walk_forward = None
        self._tree_quiesced = False

    def _log(self, event_type, *, error_code=None):
        if not self.logging_enabled:
            return
        if event_type == 'error':
            # Normalize untrusted IPC metadata without inspecting exception text.
            from quantlab.errors import ERROR_TABLE

            if type(error_code) is not str or error_code not in ERROR_TABLE:
                error_code = 'operation_failed'
        try:
            self.event_log.append(self._operation, event_type, error_code=error_code)
        except (OSError, RuntimeSafetyError):
            pass  # Diagnostic storage cannot break cancellation or task completion.

    @property
    def active(self):
        # A completed child still needs its IPC/result drained before another job.
        return self.process is not None

    def _walk_forward_owner_path(self, reference):
        return self._job_port('storage_port')._walk_forward_owner_path(self.paths, reference)

    def _claim_walk_forward(self, reference, job_id):
        return self._job_port('storage_port')._claim_walk_forward(self.paths, reference, job_id)

    def _check_walk_forward_owner(self, job_id, reference):
        return self._job_port('storage_port')._check_walk_forward_owner(self.paths, job_id, reference)

    def _validate_job_request(self, operation, payload):
        if operation not in OPERATIONS or not isinstance(payload, dict):
            raise RuntimeSafetyError('Unsupported operation')
        self._job_port('storage_port').validate_payload(payload)
        # Keep operation-specific dependencies out of module startup.
        from quantlab.analysis_recovery import require_operation

        require_operation(self.paths, operation)
        if operation == 'ui_campaign' and (
            not isinstance(payload.get('provider'), dict) or payload['provider'].get('mode') not in ('fixture', 'manual', 'chatgpt_plan')
        ):
            raise RuntimeSafetyError('Unsupported model provider; local models and paid API fallback are disabled')
        if operation not in UI_OPERATIONS:
            allowed = {'demo': {'bars'}, 'backtest': {'dataset', 'family'}, 'campaign': {'dataset'}}[operation]
            if set(payload) - allowed:
                raise RuntimeSafetyError('Unsupported job parameters')
            if operation == 'demo' and (type(payload.get('bars', 240)) is not int or not 20 <= payload.get('bars', 240) <= 10000):
                raise RuntimeSafetyError('Demo bars must be 20..10000')

    def _prepare_walk_forward_job(self, operation, payload):
        # Defer the adapter until this operation runs in its owning process.
        from quantlab.research_core.application import job_requests

        return job_requests._prepare_walk_forward_job(self, operation, payload)

    def _prepare_analysis_job(self, operation, payload):
        # Defer the adapter until this operation runs in its owning process.
        from quantlab.research_core.application import job_requests

        return job_requests._prepare_analysis_job(self, operation, payload)

    def _prepare_other_job(self, operation, payload):
        # Defer the adapter until this operation runs in its owning process.
        from quantlab.research_core.application import job_requests

        return job_requests._prepare_other_job(self, operation, payload)

    def _job_port(self, name):
        port = getattr(self, name, None)
        if port is None:
            module, factory = DEFAULT_JOB_PORT_FACTORY.split(':')
            defaults = getattr(importlib.import_module(module), factory)()
            port = defaults[0 if name == 'process_port' else 1]
        return port

    def _launch_job_process(self, operation, payload, job_id, reconciliation_admitted, helper_nonce, approved_analysis_plan, request):
        return self._job_port('process_port').launch(self, operation, payload, job_id, reconciliation_admitted, helper_nonce, approved_analysis_plan, request)

    def _join_descendants(self, pid):
        return self._job_port('process_port').join_descendants(self, pid)

    def start(self, operation, payload):
        if self.active:
            raise RuntimeSafetyError('A job is already running')
        self._validate_job_request(operation, payload)
        deadline = None
        auth_request_id = None
        reconciliation_admitted = False
        analysis_job_identity = None
        analysis_result_reference = None
        walk_forward_reference = None
        walk_forward_result_reference = None
        approved_analysis_plan = None
        helper_nonce = None
        request = None
        if operation in WALK_FORWARD_OPERATIONS:
            deadline, walk_forward_reference, walk_forward_result_reference, reconciliation_admitted = self._prepare_walk_forward_job(operation, payload)
        elif operation in ANALYSIS_OPERATIONS:
            (deadline, analysis_job_identity, analysis_result_reference, approved_analysis_plan, helper_nonce, reconciliation_admitted, request) = (
                self._prepare_analysis_job(operation, payload)
            )
        else:
            deadline, auth_request_id, reconciliation_admitted = self._prepare_other_job(operation, payload)
        job_id = uuid.uuid4().hex
        if walk_forward_reference is not None:
            self.paths.require_walk_forward_wal()
            self._claim_walk_forward(walk_forward_reference, job_id)
        self._analysis_job_identity = analysis_job_identity
        self._analysis_result_reference = analysis_result_reference
        if analysis_job_identity is not None:
            self._quiesced_analysis = None
        self._subscription_job = operation == 'ui_campaign' and payload.get('provider', {}).get('mode') == 'chatgpt_plan'
        if self._subscription_job:
            self._quiesced_subscription_id = None
        self._walk_forward_reference = walk_forward_reference
        self._walk_forward_result_reference = walk_forward_result_reference
        if walk_forward_reference is not None:
            self._quiesced_walk_forward = None
        self._tree_quiesced = False
        self._requires_tree_quiescence = (
            operation in WALK_FORWARD_OPERATIONS
            or operation in ANALYSIS_OPERATIONS
            or operation in ('ui_chatgpt_auth', 'ui_chatgpt_usage', 'ui_chatgpt_reconcile', 'ui_idea_research')
            or self._subscription_job
        )
        self._operation = operation
        self._deadline = deadline
        self._auth_request_id = auth_request_id
        self._launch_job_process(operation, payload, job_id, reconciliation_admitted, helper_nonce, approved_analysis_plan, request)
        return self.job_id

    def poll(self):
        events, self._pending = self._pending, []
        if not self.active:
            return events

        try:
            self._job_port('process_port').drain(self, events)
            exited = not self.process.is_alive()
            if not exited and self._deadline is not None and time.monotonic() >= self._deadline:
                terminal = self._terminal
                self.cancel()  # Stops/joins the whole tree before releasing the slot.
                pending, self._pending = self._pending, []
                events.extend(event for event in pending if event.get('type') != 'cancelled')
                if not terminal:
                    events.append(
                        {
                            'job_id': self.job_id,
                            'type': 'error',
                            'message': '背景作業超過期限並已停止；遠端完成／額度可能未知，禁止自動重送或退還。',
                            'error_type': 'DeadlineExceeded',
                        }
                    )
                return events
            if exited:
                self.process.join()
                # The child can send and exit between initial poll and liveness
                # check. Drain once more before classifying an incomplete stream.
                self._job_port('process_port').drain(self, events)
        except (OSError, ValueError):
            self.cancel()
            events.append({'job_id': self.job_id, 'type': 'error', 'message': 'Worker response rejected'})
            return events
        if exited:
            if self._requires_tree_quiescence:
                self._join_descendants(self.process.pid)
                self._tree_quiesced = True
            if not self._terminal:
                self._log('error')
                events.append({'job_id': self.job_id, 'type': 'error', 'message': 'Worker stopped unexpectedly; incomplete output retained as partial'})
            self._release()
            events.extend(self._deferred)
            self._deferred = []
        return events

    def _release(self):
        ownership_error = None
        if self._walk_forward_reference is not None and self._tree_quiesced:
            try:
                self._check_walk_forward_owner(self.job_id, self._walk_forward_reference)
            except Exception as exc:
                # The subtree is already joined. Release its handles even when
                # journal ownership is corrupt, but never grant recovery proof.
                ownership_error = exc
        if self.tree:
            self.tree.close()
        self.tree = None
        if self.receiver:
            self.receiver.close()
        self.receiver = None
        if self.process:
            self.process.close()
        self.process = None
        self._gate = None
        self._deadline = None
        self._auth_request_id = None
        if self._analysis_job_identity is not None and self._tree_quiesced:
            self._quiesced_analysis = (self.job_id, *self._analysis_job_identity)
        if self._subscription_job:
            self._quiesced_subscription_id = self.job_id
        if self._walk_forward_reference is not None and self._tree_quiesced and ownership_error is None:
            self._quiesced_walk_forward = (self.job_id, self._walk_forward_reference)
        if self._operation == 'ui_backup_restore':
            self._job_port('storage_port').recover(self.paths)
        if ownership_error is not None:
            raise ownership_error

    def cancel(self):
        if not self.active:
            return
        proc = self.process
        self._job_port('process_port').stop(self)
        if self._requires_tree_quiescence:
            self._join_descendants(proc.pid)
            self._tree_quiesced = True
        if self._terminal:
            # A terminal outcome already received is authoritative even if the
            # process still needed cleanup. Never relabel a failure as cancelled.
            self._pending.extend(self._deferred)
            self._deferred = []
        else:
            self._log('cancelled')
            self._pending.append({'job_id': self.job_id, 'type': 'cancelled', 'message': 'Cancelled; completed durable records are preserved'})
        self._release()

    def close(self):
        self.cancel()
