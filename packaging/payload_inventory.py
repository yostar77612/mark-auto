"""Generate the exact frozen payload inventory embedded by Inno Setup."""
import hashlib
import ctypes
from pathlib import Path
import re
import sys


def reject_alternate_streams(path):
    """NTFS stream names are not returned by rglob; reject hidden payload bytes."""
    if sys.platform != 'win32':
        return
    from ctypes import wintypes
    class StreamData(ctypes.Structure):
        _fields_ = [('size', ctypes.c_longlong), ('name', wintypes.WCHAR * 296)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    first = kernel.FindFirstStreamW
    first.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(StreamData), wintypes.DWORD]
    first.restype = wintypes.HANDLE
    next_stream = kernel.FindNextStreamW
    next_stream.argtypes = [wintypes.HANDLE, ctypes.POINTER(StreamData)]
    next_stream.restype = wintypes.BOOL
    close = kernel.FindClose
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    data = StreamData()
    handle = first(str(path), 0, ctypes.byref(data), 0)
    if handle == ctypes.c_void_p(-1).value:
        if ctypes.get_last_error() == 38:  # ERROR_HANDLE_EOF, directory without streams.
            return
        raise ValueError('Cannot inspect payload alternate streams')
    try:
        while True:
            if data.name != '::$DATA':
                raise ValueError('Alternate stream payload is forbidden')
            if not next_stream(handle, ctypes.byref(data)):
                if ctypes.get_last_error() != 38:
                    raise ValueError('Cannot enumerate payload alternate streams')
                break
    finally:
        close(handle)


def inventory(root):
    root = Path(root)
    if root.is_symlink() or getattr(root.lstat(), 'st_file_attributes', 0) & 0x400:
        raise ValueError('Payload root must not be a reparse point or symlink')
    reject_alternate_streams(root)
    rows = []
    seen = set()
    for path in sorted(root.rglob('*'), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError(f'Reparse/symlink payload is forbidden: {path}')
        reject_alternate_streams(path)
        relative = path.relative_to(root)
        for part in relative.parts:
            if (not part.isascii() or re.search(r'[<>:"/\\|?*\x00-\x1f]', part)
                    or part.endswith((' ', '.')) or part in ('.', '..')
                    or part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                        *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}):
                raise ValueError(f'Unsafe Windows payload name: {path}')
        key = str(relative).replace('/', '\\')
        if key.lower() in seen:
            raise ValueError(f'Case-colliding payload name: {path}')
        seen.add(key.lower())
        if path.is_file():
            with path.open('rb') as stream:
                rows.append((key, hashlib.file_digest(stream, 'sha256').hexdigest()))
        elif not path.is_dir():
            raise ValueError(f'Nonregular payload entry: {path}')
    if not any(name == 'MarkAuto.exe' for name, _ in rows):
        raise ValueError('Frozen MarkAuto.exe is missing')
    if any(name.lower() == 'payload-inventory.txt' for name, _ in rows):
        raise ValueError('Reserved inventory filename exists in payload')
    return rows


def main():
    root, output, include = map(Path, sys.argv[1:])
    content = ''.join(f'{digest}  {name}\r\n' for name, digest in inventory(root)).encode('ascii')
    output.write_bytes(content)
    include.write_text('#define PayloadInventorySHA256 "' + hashlib.sha256(content).hexdigest() + '"\n', encoding='ascii')


if __name__ == '__main__':
    main()
