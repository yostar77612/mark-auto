"""Explicit client contexts, bounded configuration, and independent host launch.

No SDK or credential resolver is imported here. Opening a broker context starts
its disconnected host; connecting is a separate, explicit UI command.
"""

from dataclasses import dataclass, replace
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from threading import RLock
import time
from uuid import uuid4

from quantlab.trading.application.contracts import ContextOption, UiAction, UiCommand
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError, identity
from .config import RuntimeLaunch, RuntimeProfile, load_profile, read_runtime_document
from .ipc import IpcFacade, read_session

_STARTED: dict[Path, subprocess.Popen] = {}


def _alive(process_id: int) -> bool:
    if process_id <= 0:
        return True  # Unknown metadata is not permission to replace an owner.
    if os.name != 'nt':
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            pass
        return True
    # Read-only process identity probe; never signal, terminate or steal a live
    # process. Access denied stays conservatively alive.
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, process_id)
    if not handle:
        return ctypes.get_last_error() != 87
    try:
        code = wintypes.DWORD()
        return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
    finally:
        kernel.CloseHandle(handle)


class ContextIpcFacade(IpcFacade):
    """Bind each envelope and read model to explicitly configured identity.

    Account selection is client navigation, not a mutation of the shared book.
    It cannot change a strategy/order's explicit account or the host's mode.
    """

    def __init__(self, launch: RuntimeLaunch, configuration_id: str = ''):
        self.launch, self.configuration_id = launch, configuration_id
        super().__init__(launch.root, environment=launch.environment, account_ref=launch.account_ref)

    def request(self, operation, *, command=None, quotes=None):
        self.environment, self.account_ref = self.launch.environment, self.launch.account_ref
        response = super().request(operation, command=command, quotes=quotes)
        if response.state is not None:
            state = response.state
            configured = any(item.account_ref == self.launch.account_ref and item.environment is self.launch.environment for item in state.accounts)
            pending_alias = not state.accounts and not state.financial_facts_verified and state.account_ref == self.launch.account_ref
            if state.environment is not self.launch.environment or not (configured or pending_alias):
                raise DomainError('capability_missing', 'host identity differs from selected context')
            if self.configuration_id and state.configuration_id != self.configuration_id:
                raise DomainError('startup_workspace_incompatible', 'running profile differs from explicitly selected profile')
            response = replace(response, state=replace(state, account_ref=self.launch.account_ref))
        return response


def ensure_engine(root: Path, *, launch: RuntimeLaunch | None = None, configuration_id: str = '') -> IpcFacade:
    root = root.resolve()
    launch = RuntimeLaunch(root) if launch is None else replace(launch, root=launch.root.resolve())
    if launch.root != root:
        raise DomainError('validation_failed', 'runtime context root differs')
    if launch.environment is not Environment.LOCAL and not configuration_id:
        if launch.profile_path is not None:
            profile = load_profile(launch.profile_path, launch.environment)
            if launch.account_ref not in (profile.configuration.stock_account_ref, profile.configuration.futures_account_ref):
                raise DomainError('capability_missing', 'selected account is absent from runtime profile')
            configuration_id = profile.source_sha256
        else:
            configuration_id = 'UNCONFIGURED:' + launch.environment.value + ':' + launch.account_ref
    root.mkdir(parents=True, exist_ok=True)
    facade = ContextIpcFacade(launch, configuration_id)
    try:
        facade.snapshot()
        return facade
    except DomainError:
        # An authenticated wrong-context response is not a failed local launch.
        # Never overwrite its session or fall back to another environment.
        raise
    except (OSError, EOFError):
        try:
            session = read_session(root)
        except FileNotFoundError:
            pass
        else:
            if _alive(session.process_id):
                raise DomainError('startup_workspace_busy', 'existing runtime is alive or cannot be verified') from None
    executable = Path(sys.executable).resolve()
    args = [str(executable)]
    if not getattr(sys, 'frozen', False):
        args.append(str(Path(__file__).resolve().parents[3] / 'desktop.py'))
    args.extend(('--trading-engine', str(root), '--trading-environment', launch.environment.value, '--trading-account', launch.account_ref))
    if launch.profile_path is not None:
        args.extend(('--trading-profile', str(launch.profile_path)))
    with (root / 'engine-startup.log').open('ab') as log:
        process = subprocess.Popen(
            args, stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, close_fds=True
        )
        _STARTED[root] = process
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise DomainError('startup_failed', 'configured runtime did not start; existing data retained')
        try:
            session = read_session(root)
            if session.process_id == process.pid:
                facade.snapshot()
                return facade
        except DomainError as exc:
            if exc.code in ('capability_missing', 'startup_workspace_incompatible'):
                raise
        except (OSError, EOFError, ValueError):
            pass
        time.sleep(0.1)
    raise DomainError('startup_failed', 'runtime startup deadline; inspect the owned process before retry')


@dataclass(frozen=True)
class _Entry:
    context_id: str
    label: str
    launch: RuntimeLaunch
    profile: RuntimeProfile | None = None
    error: str = ''

    def accounts(self) -> tuple[str, ...]:
        if self.profile:
            config = self.profile.configuration
            return tuple(ref for ref in (config.stock_account_ref, config.futures_account_ref) if ref)
        if self.launch.environment is Environment.LOCAL:
            return 'local-stock', 'local-futures'
        return (self.launch.account_ref,)

    def option(self) -> ContextOption:
        return ContextOption(self.context_id, self.label, self.launch.environment, self.accounts(), 'UNAVAILABLE' if self.error else 'CONFIGURED')

    def expected_configuration(self) -> str:
        if self.profile:
            return self.profile.source_sha256
        if self.launch.environment is Environment.LOCAL:
            return ''
        return 'UNCONFIGURED:' + self.launch.environment.value + ':' + self.launch.account_ref


class RuntimeContextManager:
    """File references select isolated hosts; no startup credential discovery."""

    def __init__(self, base_root: Path, registry_path: Path | None = None):
        self.base_root = base_root.resolve()
        self.registry_path = registry_path or self.base_root / 'contexts-v2.json'
        if not self.registry_path.is_absolute():
            raise DomainError('validation_failed', 'absolute context registry required')
        self._entries: dict[str, _Entry] = {}
        self._registry_body: dict | None = None
        self.selected_context, self.selected_account = '', ''
        self._lock = RLock()
        if self.registry_path.exists():
            self._load()
        if not self._entries:
            self._entries['local'] = _Entry('local', '', RuntimeLaunch(self.base_root))
            self.selected_context, self.selected_account = 'local', 'local-stock'
        if not any(entry.launch.environment is Environment.LOCAL for entry in self._entries.values()):
            if len(self._entries) >= 32:
                raise DomainError('validation_failed', 'context registry must leave room for the local lab')
            local_root = self.base_root
            if any(entry.launch.root.resolve() == local_root for entry in self._entries.values()):
                local_root = self.base_root / 'context-engines' / 'local'
            self._entries['local'] = _Entry('local', '', RuntimeLaunch(local_root))

    def _entry(self, context_id: str, label: str, launch: RuntimeLaunch, *, strict: bool = False) -> _Entry:
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', context_id):
            raise DomainError('validation_failed', 'bounded context identity required')
        if context_id == 'local' and launch.environment is not Environment.LOCAL:
            raise DomainError('validation_failed', 'local context identity is reserved for the local lab')
        if label:
            identity(label, 'context label')
        profile, error = None, ''
        if launch.profile_path is not None:
            try:
                profile = load_profile(launch.profile_path, launch.environment)
                if launch.account_ref not in (profile.configuration.stock_account_ref, profile.configuration.futures_account_ref):
                    raise DomainError('capability_missing', 'selected account is not in this profile')
            except DomainError as exc:
                if strict:
                    raise
                error = exc.code
        return _Entry(context_id, label or (profile.profile_alias if profile else ''), launch, profile, error)

    def _load(self) -> None:
        body = read_runtime_document(self.registry_path)
        if (
            set(body) != {'schema_version', 'selected_context', 'selected_account', 'contexts'}
            or type(body['contexts']) is not list
            or not 1 <= len(body['contexts']) <= 32
        ):
            raise DomainError('validation_failed', 'context registry schema')
        entries, roots = {}, set()
        for item in body['contexts']:
            if type(item) is not dict or set(item) != {'context_id', 'label', 'root', 'environment', 'account_ref', 'profile_path'}:
                raise DomainError('validation_failed', 'context record schema')
            if any(type(item[name]) is not str for name in ('context_id', 'label', 'root', 'environment', 'account_ref')) or (
                item['profile_path'] is not None and type(item['profile_path']) is not str
            ):
                raise DomainError('validation_failed', 'context record types')
            try:
                environment = Environment(item['environment'])
            except ValueError as exc:
                raise DomainError('validation_failed', 'unknown configured runtime environment') from exc
            launch = RuntimeLaunch(Path(item['root']), environment, Path(item['profile_path']) if item['profile_path'] else None, item['account_ref'])
            root = launch.root.resolve()
            if item['context_id'] in entries or root in roots:
                raise DomainError('validation_failed', 'contexts must have independent engine directories')
            roots.add(root)
            entry = self._entry(item['context_id'], item['label'], launch)
            entries[entry.context_id] = entry
        selected, account = body['selected_context'], body['selected_account']
        if (
            type(selected) is not str
            or type(account) is not str
            or selected not in entries
            or (account not in entries[selected].accounts() and not entries[selected].error)
        ):
            raise DomainError('validation_failed', 'selected registry context/account is unavailable')
        self._entries, self.selected_context, self.selected_account = entries, selected, account
        self._registry_body = body

    def _save(self, entries: dict[str, _Entry], selected: str, account: str) -> None:
        if not 1 <= len(entries) <= 32:
            raise DomainError('validation_failed', 'context registry capacity exceeded')
        body = {
            'schema_version': 1,
            'selected_context': selected,
            'selected_account': account,
            'contexts': [
                {
                    'context_id': entry.context_id,
                    'label': entry.label,
                    'root': str(entry.launch.root),
                    'environment': entry.launch.environment.value,
                    'account_ref': entry.launch.account_ref,
                    'profile_path': str(entry.launch.profile_path) if entry.launch.profile_path else None,
                }
                for entry in entries.values()
            ],
        }
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        for path in (self.registry_path, *self.registry_path.parents):
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
                raise DomainError('validation_failed', 'redirected registry refused')
        if self.registry_path.exists():
            if self._registry_body is None or read_runtime_document(self.registry_path) != self._registry_body:
                raise DomainError('state_conflict', 'context registry changed in another process')
        temp = self.registry_path.with_name('contexts-' + uuid4().hex + '.tmp')
        try:
            with temp.open('x', encoding='utf-8') as stream:
                stream.write(json.dumps(body, ensure_ascii=True, sort_keys=True))
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(self.registry_path)
            self._registry_body = body
        finally:
            temp.unlink(missing_ok=True)

    def list_contexts(self) -> tuple[ContextOption, ...]:
        with self._lock:
            return tuple(entry.option() for entry in self._entries.values())

    def open_context(self, context_id: str, account_ref: str) -> IpcFacade:
        with self._lock:
            entry = self._entries.get(context_id)
        if entry is None or account_ref not in entry.accounts():
            raise DomainError('capability_missing', 'unknown configured context/account')
        if entry.error:
            raise DomainError(entry.error, 'selected profile is unavailable; current context retained')
        launch = replace(entry.launch, account_ref=account_ref)
        return ensure_engine(launch.root, launch=launch, configuration_id=entry.expected_configuration())

    def register_profile(self, profile_ref: str, environment: Environment) -> ContextOption:
        if environment is Environment.LOCAL:
            raise DomainError('capability_missing', 'local simulation does not consume broker profiles')
        profile = load_profile(Path(profile_ref), environment)
        account = profile.configuration.stock_account_ref or profile.configuration.futures_account_ref
        key = sha256((environment.value + '\0' + str(profile.source_path.resolve())).encode('utf-8')).hexdigest()[:20]
        context_id = environment.value.lower() + '-' + key
        launch = RuntimeLaunch(self.base_root / 'context-engines' / context_id, environment, profile.source_path, account)
        entry = self._entry(context_id, profile.profile_alias, launch, strict=True)
        with self._lock:
            previous = self._entries.get(context_id)
            if previous is not None and previous.expected_configuration() != entry.expected_configuration():
                try:
                    session = read_session(previous.launch.root)
                except FileNotFoundError:
                    pass
                else:
                    if _alive(session.process_id):
                        raise DomainError('startup_workspace_busy', 'close the old configured engine before replacing its profile')
            entries = {**self._entries, context_id: entry}
            self._save(entries, self.selected_context, self.selected_account)
            self._entries = entries
        return entry.option()

    def configure_launch(self, environment: Environment, account_ref: str, profile_path: Path | None) -> str:
        if environment is Environment.LOCAL:
            if profile_path is not None or account_ref not in ('local-stock', 'local-futures'):
                raise DomainError('capability_missing', 'explicit local lab identity required')
            return next(key for key, entry in self._entries.items() if entry.launch.environment is Environment.LOCAL)
        if profile_path is not None:
            option = self.register_profile(str(profile_path), environment)
            if account_ref not in option.account_refs:
                raise DomainError('capability_missing', 'requested account not present in runtime profile')
            return option.context_id
        context_id = environment.value.lower() + '-' + sha256(account_ref.encode('utf-8')).hexdigest()[:20]
        launch = RuntimeLaunch(self.base_root / 'context-engines' / context_id, environment, None, account_ref)
        entry = self._entry(context_id, '', launch)
        with self._lock:
            entries = {**self._entries, context_id: entry}
            self._save(entries, self.selected_context, self.selected_account)
            self._entries = entries
        return context_id

    def persist_selection(self, context_id: str, account_ref: str) -> None:
        with self._lock:
            entry = self._entries.get(context_id)
            if entry is None or account_ref not in entry.accounts():
                raise DomainError('capability_missing', 'selected account is not configured')
            self._save(self._entries, context_id, account_ref)
            self.selected_context, self.selected_account = context_id, account_ref


def shutdown(root: Path, *, launch: RuntimeLaunch | None = None, configuration_id: str = '') -> None:
    launch = RuntimeLaunch(root.resolve()) if launch is None else launch
    facade = ContextIpcFacade(launch, configuration_id)
    state = facade.snapshot()
    receipt = facade.execute(UiCommand(UiAction.SHUTDOWN_ENGINE, state.version))
    if not receipt.accepted:
        raise DomainError(receipt.code)
    process = _STARTED.pop(root.resolve(), None)
    if process is not None and process.wait(timeout=15) != 0:
        raise DomainError('operation_failed', 'owned engine did not exit cleanly')
