"""Single pinned executable adapter, run only inside the isolated desktop worker.

JobManager assigns that worker to its kill-on-close Windows Job Object before
opening its start gate. All server descendants inherit that object. No service
is adopted from a PID file or an occupied port; only this Popen handle is used.
"""
import os
import ctypes
from contextlib import contextmanager
from pathlib import Path
import platform
import subprocess
import sys
import re
import time

from quantlab.local_ai import (LocalAIError, MODEL, PORT, ensure_port_free,
                              health, verify_install, manifest, verify_file, safe_path, process_creation_time, verify_owner, SESSION_TOKEN_ENV)


def system_directories():
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    result = []
    for name in ('GetWindowsDirectoryW', 'GetSystemDirectoryW'):
        function = getattr(kernel, name)
        function.argtypes = [w.LPWSTR, w.UINT]; function.restype = w.UINT
        buffer = ctypes.create_unicode_buffer(32768)
        length = function(buffer, len(buffer))
        if not length or length >= len(buffer): raise LocalAIError('dependency')
        result.append(buffer.value)
    return tuple(result)


@contextmanager
def locked_runtime(paths):
    """Pin files against writes/replacement, and ancestry against renames.

    Directory handles deny delete but permit ordinary directory metadata access;
    file handles deny write/delete. Open reparse points themselves and reject
    them from handle metadata before rehashing every pinned byte under the locks.
    All handles close on process exit, including forced worker cancellation.
    """
    from ctypes import wintypes as w
    from quantlab.local_ai import cache_root
    server, model = verify_install(paths)
    dependencies = server.parent
    spec = manifest()
    root = cache_root(paths)
    files = [root/'runtime'/name for name in spec['runtime_members']]
    files += [model] + [root/'licenses'/name for name in spec['licenses']]
    files += [dependencies/name for name in spec['support_dlls']]
    directories = sorted({parent for file in files for parent in file.parents}, key=lambda p:len(p.parts))
    class FileTime(ctypes.Structure):
        _fields_ = [('low',ctypes.c_uint32),('high',ctypes.c_uint32)]
    class Information(ctypes.Structure):
        _fields_ = [('attributes',ctypes.c_uint32),('created',FileTime),('accessed',FileTime),('written',FileTime),
                    ('volume',ctypes.c_uint32),('size_high',ctypes.c_uint32),('size_low',ctypes.c_uint32),
                    ('links',ctypes.c_uint32),('index_high',ctypes.c_uint32),('index_low',ctypes.c_uint32)]
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
    kernel.CreateFileW.restype=w.HANDLE
    kernel.GetFileInformationByHandle.argtypes=[w.HANDLE,ctypes.POINTER(Information)]
    kernel.CloseHandle.argtypes=[w.HANDLE]
    handles=[]
    try:
        for path,is_directory in [(p,True) for p in directories]+[(p,False) for p in files]:
            safe_path(path,file=not is_directory)
            handle=kernel.CreateFileW(str(path),0x80 if is_directory else 0x80000000,
                3 if is_directory else 1,None,3,0x00200000 | (0x02000000 if is_directory else 0x80),None)
            if handle in (None,ctypes.c_void_p(-1).value): raise LocalAIError('unsafe_path')
            handles.append(handle)
            info=Information()
            if (not kernel.GetFileInformationByHandle(handle,ctypes.byref(info)) or info.attributes & 0x400
                or bool(info.attributes & 0x10) != is_directory or (not is_directory and info.links != 1)):
                raise LocalAIError('unsafe_path')
        # Rehash only after all paths and known dependency bytes are held.
        if verify_install(paths) != (server,model):
            raise LocalAIError('artifact')
        yield server,model,dependencies
    finally:
        for handle in reversed(handles): kernel.CloseHandle(handle)


def clear_inherited_dll_directory():
    from ctypes import wintypes as w
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.SetDllDirectoryW.argtypes=[w.LPCWSTR];kernel.SetDllDirectoryW.restype=w.BOOL
    if not kernel.SetDllDirectoryW(None): raise LocalAIError('dependency')


def serve(paths, emit):
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise LocalAIError('platform')
    with locked_runtime(paths) as (server,model,dependencies):
        return _serve_locked(server,model,dependencies,emit)


def _serve_locked(server,model,dependencies,emit):
    ensure_port_free()
    clear_inherited_dll_directory()
    # Strip inherited loader/plugin/Python configuration and executable search
    # paths. Windows system DLLs and the complete verified distribution suffice.
    windows, system = system_directories()
    environment = {key: value for key, value in os.environ.items() if key.upper() in {'TEMP', 'TMP'}}
    environment.update(SYSTEMROOT=windows, WINDIR=windows, PATH=str(dependencies) + os.pathsep + system)
    token = os.environ.get(SESSION_TOKEN_ENV, '')
    if re.fullmatch(r'[A-Za-z0-9_-]{43}', token) is None: raise LocalAIError('ownership')
    environment['LLAMA_API_KEY'] = token
    command = [str(server), '-m', str(model), '--host', '127.0.0.1', '--port', str(PORT),
               '--alias', MODEL, '-t', '2', '-tb', '2', '-c', '4096', '-np', '1', '-ngl', '0',
               '--seed', '7', '--temp', '0', '--no-webui', '--no-agent', '--no-slots', '--no-cors-credentials', '--cors-origins', 'http://127.0.0.1:18765']
    process = subprocess.Popen(command, shell=False, cwd=str(server.parent), env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        created = process_creation_time(process.pid)
        deadline = time.monotonic() + 120
        while process.poll() is None:
            if health() and process.poll() is None:
                verify_owner(process.pid, created)
                emit('progress', message='本機模型已就緒；尚未驗證策略或績效。', progress=100, local_ai_ready=True, local_ai_owner={'pid':process.pid, 'created':created})
                break
            if time.monotonic() >= deadline: raise LocalAIError('loading')
            time.sleep(.2)
        else:
            raise LocalAIError('loading')
        # Lifetime is also bounded by JobManager's independent parent deadline.
        end = time.monotonic() + 8 * 60 * 60
        while process.poll() is None and time.monotonic() < end:
            time.sleep(.2)
        if process.poll() is not None: raise LocalAIError('loading')
        return {'status': 'stopped_after_eight_hours'}
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
