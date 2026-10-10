"""Pinned, explicit local-AI setup and bounded provider; inert on import.

The model is cache data, never a backup/state payload. No executable is selected
by the user: only the two exact publisher archives in the packaged manifest are
accepted. The process adapter owns execution separately.
"""
from pathlib import Path, PurePosixPath
from contextlib import closing
import hashlib
import ctypes
from dataclasses import dataclass
import sys
import http.client
import json
import os
import shutil
import socket
import sqlite3
import ssl
import stat
import time
import threading
import urllib.request
from urllib.parse import urlsplit
import uuid
import zipfile

from .core import ValidationError, content_hash, to_dict
from .provider import HTTPTransport
from .research import CompatibleProvider, validate_dsl

PORT = 18765
ENDPOINT = f'http://127.0.0.1:{PORT}/v1/chat/completions'
MODEL = 'Qwen/Qwen2.5-1.5B-Instruct-GGUF'
PROFILE = 'llamacpp-b11429-qwen15-v1'
SESSION_TOKEN_ENV = 'MARKAUTO_LOCAL_AI_SESSION_TOKEN'
MANIFEST_SHA256 = '1e832cc1c4c6adb42b004499cac139f085350c0e05387afe5948317dcefbaee6'
MAX_CALLS = 100
MAX_TOKENS = 1000000
ERROR_MESSAGES = {
    'platform': '此固定本機套件僅支援 Windows x64；其他系統仍可使用原有相容 HTTP 模式。',
    'unsafe_path': '檔案路徑含連結、重新解析點或非一般檔案，已拒絕。',
    'artifact': '檔案大小或 SHA-256 不符官方固定版本；未執行。',
    'archive': '模型執行環境封存檔內容不符合固定清單；未執行。',
    'missing': '尚未完成本機模型設定，請下載官方檔案或選取相同版本的 ZIP 與 GGUF。',
    'network': '官方下載失敗或逾時；沒有啟動模型，可明確重試或選取已下載檔案。',
    'consent': '請先明確同意本次操作。',
    'occupied': '本機連接埠 18765 已使用；不會接管或停止其他服務。',
    'loading': '模型未在期限內就緒，或服務提前退出；未進行研究。',
    'probe': '本機結構化推論檢查未通過；若已發送，呼叫額度仍保留。',
    'request': '不支援的本機 AI 操作。',
    'ownership': '本機服務不屬於本程式啟動的程序，或身分已變更；禁止傳送研究內容與消耗新額度。',
    'dependency': '應用程式附帶的固定 Windows 執行階段 DLL 遺失或不符；請使用完整官方安裝版本，不需自行安裝開發工具。',
}


class LocalAIError(ValidationError):
    def __init__(self, code):
        self.code = code if code in ERROR_MESSAGES else 'request'
        super().__init__(ERROR_MESSAGES[self.code])


def resources():
    return Path(__file__).resolve().parent.parent / 'packaging' / 'local_ai'


def manifest():
    raw = (resources() / 'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise LocalAIError('artifact')
    value = json.loads(raw)
    if value.get('profile') != PROFILE:
        raise LocalAIError('artifact')
    return value


def cache_root(paths):
    return (Path(paths.bootstrap) if paths.bootstrap else Path(paths.root)) / 'cache' / 'local-ai' / PROFILE


def safe_path(path, *, file=False):
    path = Path(path)
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise LocalAIError('unsafe_path')
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise LocalAIError('unsafe_path')
    if file:
        try:
            info = path.stat()
        except FileNotFoundError:
            raise LocalAIError('missing') from None
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise LocalAIError('unsafe_path')
    return path


def digest(path):
    safe_path(path, file=True)
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def verify_file(path, artifact):
    path = safe_path(path, file=True)
    if path.stat().st_size != artifact['bytes'] or digest(path) != artifact['sha256']:
        raise LocalAIError('artifact')
    return path


def _members(archive, expected):
    infos = archive.infolist()
    if len(infos) != len(expected):
        raise LocalAIError('archive')
    names = set()
    for info in infos:
        name = info.filename
        p = PurePosixPath(name)
        mode = info.external_attr >> 16
        if (p.is_absolute() or len(p.parts) != 1 or name in ('.', '..') or '\\' in name or ':' in name
            or '\x00' in info.orig_filename or info.is_dir() or name.casefold() in names
            or name not in expected or stat.S_ISLNK(mode) or info.flag_bits & 1
            or info.file_size != expected[name]['bytes']):
            raise LocalAIError('archive')
        names.add(name.casefold())
    return infos


def application_dependencies():
    if getattr(sys, 'frozen', False):
        folder = Path(sys._MEIPASS) / 'local-ai-dependencies'
    else:
        from importlib.util import find_spec
        package = find_spec('shiboken6')
        if package is None or package.origin is None: raise LocalAIError('dependency')
        folder = Path(package.origin).parent
    try:
        safe_path(folder)
        for name, item in manifest()['support_dlls'].items(): verify_file(folder/name,item)
    except Exception:
        raise LocalAIError('dependency') from None
    return folder


def verify_install(paths):
    """Full pins, including all DLLs and no extra runtime files, before execution."""
    root = safe_path(cache_root(paths))
    spec = manifest()
    model = verify_file(root / spec['model']['filename'], spec['model'])
    runtime = safe_path(root / 'runtime')
    if not runtime.is_dir():
        raise LocalAIError('missing')
    members = {**spec['runtime_members'], **spec.get('support_dlls', {})}
    if {p.name for p in runtime.iterdir()} != set(members):
        raise LocalAIError('archive')
    for name, item in members.items():
        verify_file(runtime / name, item)
    notices = safe_path(root / 'licenses')
    if not notices.is_dir() or {p.name for p in notices.iterdir()} != set(spec['licenses']):
        raise LocalAIError('artifact')
    for name, item in spec['licenses'].items():
        verify_file(notices / name, item)
    return runtime / 'llama-server.exe', model


def _copy_verified(source, destination, artifact):
    verify_file(source, artifact)
    safe_path(destination)
    with Path(source).open('rb') as incoming, Path(destination).open('xb') as outgoing:
        shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
    verify_file(destination, artifact)


def install(paths, runtime_archive, model_file):
    """Only called by an explicitly requested isolated setup worker."""
    spec = manifest()
    verify_file(runtime_archive, spec['runtime'])
    verify_file(model_file, spec['model'])
    root = safe_path(cache_root(paths))
    if root.exists():
        verify_install(paths)  # Never replace an existing mismatched installation.
        return {'status': 'installed', 'reused': True}
    root.parent.mkdir(parents=True, exist_ok=True)
    stage = safe_path(root.parent / (PROFILE + '.partial-' + uuid.uuid4().hex))
    stage.mkdir()
    try:
        runtime = stage / 'runtime'; runtime.mkdir()
        with zipfile.ZipFile(runtime_archive) as archive:
            for info in _members(archive, spec['runtime_members']):
                target = runtime / info.filename
                with archive.open(info) as incoming, target.open('xb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                verify_file(target, spec['runtime_members'][info.filename])
        if spec.get('support_dlls'):
            dependencies = application_dependencies()
            for name, item in spec['support_dlls'].items():
                _copy_verified(dependencies/name, runtime/name, item)
        _copy_verified(model_file, stage / spec['model']['filename'], spec['model'])
        notices = stage / 'licenses'; notices.mkdir()
        for name, item in spec['licenses'].items():
            _copy_verified(resources() / name, notices / name, item)
        safe_path(root)
        if root.exists(): raise LocalAIError('artifact')
        stage.rename(root)
    finally:
        if stage.exists(): shutil.rmtree(stage)
    return {'status': 'installed', 'reused': False}


_DOWNLOAD_HOSTS = frozenset({'github.com', 'release-assets.githubusercontent.com',
    'huggingface.co', 'cdn-lfs.huggingface.co', 'cdn-lfs.hf.co', 'cas-bridge.xethub.hf.co'})


def _download_url(url):
    try:
        p = urlsplit(url)
        if p.scheme != 'https' or p.hostname not in _DOWNLOAD_HOSTS or p.username or p.password or p.port not in (None, 443) or p.fragment:
            raise ValueError()
    except (ValueError, TypeError):
        raise LocalAIError('network') from None
    return url


class _PinnedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(artifact, destination, progress=None):
    """Bounded publisher download; final digest, not redirect hostname, is authority."""
    _download_url(artifact['url'])
    destination = safe_path(destination)
    if destination.exists():
        verify_file(destination, artifact)
        return destination
    temporary = safe_path(destination.with_suffix(destination.suffix + '.partial'))
    if temporary.exists(): safe_path(temporary, file=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _PinnedRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    start = time.monotonic()
    try:
        req = urllib.request.Request(artifact['url'], headers={'Accept-Encoding': 'identity', 'User-Agent': 'MarkAuto-local-setup/1'})
        with opener.open(req, timeout=20) as response, temporary.open('wb') as output:
            _download_url(response.geturl())
            if response.status != 200 or response.headers.get('Content-Encoding', 'identity') != 'identity':
                raise LocalAIError('network')
            declared = response.headers.get('Content-Length')
            if declared is not None and declared != str(artifact['bytes']): raise LocalAIError('artifact')
            total = 0
            while True:
                if time.monotonic() - start > 900: raise LocalAIError('network')
                chunk = response.read1(min(65536, artifact['bytes'] + 1 - total))
                if not chunk: break
                total += len(chunk)
                if total > artifact['bytes']: raise LocalAIError('artifact')
                output.write(chunk)
                if progress: progress(total, artifact['bytes'])
        verify_file(temporary, artifact)
        temporary.rename(destination)
        return destination
    except LocalAIError:
        raise
    except Exception:
        raise LocalAIError('network') from None


def setup(paths, payload, emit=None):
    if not isinstance(payload, dict) or payload.get('action') not in ('install', 'download'): raise LocalAIError('request')
    if payload.get('consent') is not True: raise LocalAIError('consent')
    spec = manifest()
    if payload['action'] == 'install':
        if set(payload) != {'action', 'consent', 'runtime_archive', 'model_file'}: raise LocalAIError('request')
        return install(paths, Path(payload['runtime_archive']), Path(payload['model_file']))
    if set(payload) != {'action', 'consent'} or payload['action'] != 'download': raise LocalAIError('request')
    root = safe_path(cache_root(paths))
    if root.exists():
        verify_install(paths)
        return {'status': 'installed', 'reused': True}
    downloads = safe_path(root.parent / 'downloads'); downloads.mkdir(parents=True, exist_ok=True)
    paths_to_use = {}
    for name in ('runtime', 'model'):
        artifact = spec[name]
        last = [-1]
        def progress(done, total):
            percent = int(done * 100 / total)
            if emit and percent != last[0]:
                emit('progress', message='下載官方固定版本（' + name + '）', progress=percent)
                last[0] = percent
        paths_to_use[name] = download(artifact, downloads / artifact['filename'], progress)
    result = install(paths, paths_to_use['runtime'], paths_to_use['model'])
    # Drop only our own duplicate, hash-verified downloads after successful install.
    for name in ('runtime', 'model'):
        verify_file(paths_to_use[name], spec[name]); paths_to_use[name].unlink()
    return result


def validate_local_endpoint(endpoint):
    if endpoint != ENDPOINT: raise LocalAIError('request')
    return endpoint


def ensure_port_free():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try: sock.bind(('127.0.0.1', PORT))
        except OSError: raise LocalAIError('occupied') from None


def health(endpoint=ENDPOINT):
    validate_local_endpoint(endpoint)
    connection = http.client.HTTPConnection('127.0.0.1', PORT, timeout=2)
    def interrupt():
        sock = connection.sock
        if sock is not None:
            try: sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            sock.close()
    timer = threading.Timer(2, interrupt); timer.daemon = True; timer.start()
    try:
        connection.request('GET', '/health', headers={'Accept': 'application/json'})
        response = connection.getresponse()
        deadline = time.monotonic() + 2
        chunks = []; total = 0
        while True:
            if time.monotonic() >= deadline: return False
            chunk = response.read1(min(4097 - total, 4096))
            if not chunk: break
            chunks.append(chunk); total += len(chunk)
            if total > 4096: return False
        raw = b''.join(chunks)
        if response.status != 200: return False
        return json.loads(raw).get('status') == 'ok'
    except (OSError, ValueError, http.client.HTTPException, AttributeError):
        return False
    finally:
        timer.cancel(); connection.close()


def process_creation_time(pid):
    if sys.platform != 'win32' or type(pid) is not int or pid <= 0:
        raise LocalAIError('ownership')
    from ctypes import wintypes as w
    class FileTime(ctypes.Structure):
        _fields_ = [('low', ctypes.c_uint32), ('high', ctypes.c_uint32)]
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]; k.OpenProcess.restype = w.HANDLE
    k.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(FileTime)] * 4
    k.CloseHandle.argtypes = [w.HANDLE]
    handle = k.OpenProcess(0x1000, False, pid)
    if not handle: raise LocalAIError('ownership')
    try:
        created, exited, kernel, user = (FileTime() for _ in range(4))
        if not k.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            raise LocalAIError('ownership')
        return (created.high << 32) | created.low
    finally: k.CloseHandle(handle)


def _tcp_owners():
    if sys.platform != 'win32': raise LocalAIError('ownership')
    api = ctypes.WinDLL('iphlpapi', use_last_error=True)
    api.GetExtendedTcpTable.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_int,
                                       ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
    api.GetExtendedTcpTable.restype = ctypes.c_uint32
    size = ctypes.c_uint32(0)
    status = api.GetExtendedTcpTable(None, ctypes.byref(size), False, socket.AF_INET, 5, 0)
    if status != 122 or not 4 <= size.value <= 1024*1024: raise LocalAIError('ownership')
    for _ in range(3):
        buffer = ctypes.create_string_buffer(size.value)
        status = api.GetExtendedTcpTable(buffer, ctypes.byref(size), False, socket.AF_INET, 5, 0)
        if status == 122 and 4 <= size.value <= 1024*1024: continue
        if status != 0 or size.value > len(buffer): raise LocalAIError('ownership')
        count = ctypes.c_uint32.from_buffer_copy(buffer.raw[:4]).value
        if 4 + count * 24 > size.value: raise LocalAIError('ownership')
        rows = []
        for index in range(count):
            values = (ctypes.c_uint32 * 6).from_buffer_copy(buffer.raw[4+index*24:4+(index+1)*24])
            state, local_addr, local_port, remote_addr, remote_port, pid = values
            rows.append((state, socket.inet_ntoa(int(local_addr).to_bytes(4,'little')),
                socket.ntohs(local_port & 65535), socket.inet_ntoa(int(remote_addr).to_bytes(4,'little')),
                socket.ntohs(remote_port & 65535), pid))
        return rows
    raise LocalAIError('ownership')


def verify_owner(pid, created, sock=None):
    """Check the live listener, or the *connected peer* before sending content.

    Checking the established server-side tuple closes the port-rebind gap:
    merely finding a same-port listener after connect would not identify its peer.
    Process creation time prevents accepting a recycled PID.
    """
    if type(created) is not int or created <= 0 or process_creation_time(pid) != created:
        raise LocalAIError('ownership')
    if sock is None:
        expected = (2, '127.0.0.1', PORT)  # MIB_TCP_STATE_LISTEN
        found = any(row[:3] == expected and row[5] == pid for row in _tcp_owners())
    else:
        if sock.getpeername() != ('127.0.0.1', PORT): raise LocalAIError('ownership')
        local = sock.getsockname()
        expected = (5, '127.0.0.1', PORT, local[0], local[1], pid)  # ESTABLISHED peer
        found = expected in _tcp_owners()
    if not found or process_creation_time(pid) != created: raise LocalAIError('ownership')


@dataclass(frozen=True)
class OwnedPeerVerifier:
    pid: int
    created: int

    def __call__(self, sock):
        verify_owner(self.pid, self.created, sock)


class LocalCompatibleProvider(CompatibleProvider):
    def __init__(self, *, owner, **kwargs):
        super().__init__(**kwargs)
        self.owner = owner

    def generate(self, context):
        # Refuse stale/foreign listeners before the existing durable reservation.
        verify_owner(self.owner.pid, self.owner.created)
        return super().generate(context)


def provider(controls, owner=None):
    """One fixed lifetime ledger for this profile, probes and campaigns together."""
    if not isinstance(owner, dict) or set(owner) != {'pid','created'}:
        raise LocalAIError('ownership')
    peer = OwnedPeerVerifier(owner['pid'], owner['created'])
    safe_path(Path(controls))
    ledger = Path(controls) / 'local-ai-v1.sqlite3'
    if ledger.exists() or ledger.is_symlink(): safe_path(ledger, file=True)
    return LocalCompatibleProvider(owner=peer, model=MODEL, endpoint=ENDPOINT,
        transport=HTTPTransport(allow_network=True, api_key_env=SESSION_TOKEN_ENV, connection_verifier=peer),
        budget_path=Path(controls) / 'local-ai-v1.sqlite3', network_opt_in=True,
        max_calls=MAX_CALLS, max_tokens=MAX_TOKENS, max_spend='0', cost_per_token='0',
        tokens_per_call=1024, timeout_seconds=120, output_mode='registry_json_schema')


def usage(controls):
    path = Path(controls) / 'local-ai-v1.sqlite3'
    if not path.exists(): return {'calls': 0, 'tokens': 0, 'max_calls': MAX_CALLS, 'max_tokens': MAX_TOKENS}
    safe_path(path, file=True)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        row = db.execute('SELECT calls,tokens FROM budget').fetchone()
    return {'calls': row[0] if row else 0, 'tokens': row[1] if row else 0, 'max_calls': MAX_CALLS, 'max_tokens': MAX_TOKENS}


def probe(controls, owner=None):
    if not isinstance(owner, dict) or set(owner) != {'pid', 'created'}: raise LocalAIError('ownership')
    verify_owner(owner['pid'], owner['created'])
    if not health(): raise LocalAIError('loading')
    try:
        generator = provider(controls, owner)
        candidate = generator.generate({'family': 'trend', 'task': 'technical_schema_probe',
            'training': {'bar_count': 240}, 'instruction': 'Return one valid built-in trend parameter proposal. No market data is supplied; no performance claim.'})
        spec = validate_dsl(candidate)
        if spec.family != 'trend' or spec.rules: raise LocalAIError('probe')
    except Exception:
        raise LocalAIError('probe') from None
    return {'status': 'schema_probe_pass', 'real_model_status': 'not_verified',
        'research_evaluations': 0, 'usage': usage(controls),
        'candidate_hash': content_hash(to_dict(spec)),
        'response_hash': generator.receipts[-1]['response_hash']}


def loaded_support_modules(pid, created, directory):
    """Native validation proof of actual loader paths, not just supplied files."""
    if process_creation_time(pid) != created: raise LocalAIError('ownership')
    from ctypes import wintypes as w
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    psapi=ctypes.WinDLL('psapi',use_last_error=True)
    kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
    kernel.CloseHandle.argtypes=[w.HANDLE]
    psapi.EnumProcessModulesEx.argtypes=[w.HANDLE,ctypes.POINTER(w.HMODULE),w.DWORD,ctypes.POINTER(w.DWORD),w.DWORD]
    psapi.GetModuleFileNameExW.argtypes=[w.HANDLE,w.HMODULE,w.LPWSTR,w.DWORD]
    psapi.GetModuleFileNameExW.restype=w.DWORD
    handle=kernel.OpenProcess(0x0410,False,pid)
    if not handle:raise LocalAIError('ownership')
    try:
        modules=(w.HMODULE*1024)();needed=w.DWORD()
        if not psapi.EnumProcessModulesEx(handle,modules,ctypes.sizeof(modules),ctypes.byref(needed),3) or needed.value>ctypes.sizeof(modules):
            raise LocalAIError('dependency')
        observed={}
        for module in modules[:needed.value//ctypes.sizeof(w.HMODULE)]:
            buffer=ctypes.create_unicode_buffer(32768)
            length=psapi.GetModuleFileNameExW(handle,module,buffer,len(buffer))
            if not length or length>=len(buffer):raise LocalAIError('dependency')
            path=Path(buffer.value)
            if path.name.casefold() in manifest()['support_dlls']:
                observed[path.name.casefold()]=path
        proofs=[]
        for name,pin in manifest()['support_dlls'].items():
            path=observed.get(name)
            if path is None or str(path.resolve()).casefold()!=str((Path(directory)/name).resolve()).casefold():
                raise LocalAIError('dependency')
            verify_file(path,pin)
            proofs.append({'filename':name,'sha256':pin['sha256'],'loaded_from':'pinned_app_local_runtime'})
        if process_creation_time(pid)!=created:raise LocalAIError('ownership')
        return proofs
    finally:kernel.CloseHandle(handle)


def collect_support_binaries():
    """Strict actual freezer boundary; structural spec tests mock this call only."""
    if sys.platform != 'win32': raise LocalAIError('platform')
    folder = application_dependencies()
    return [(str(folder/name), 'local-ai-dependencies') for name in manifest()['support_dlls']]
