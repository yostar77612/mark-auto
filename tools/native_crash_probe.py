"""Windows-only diagnostic: name the native module and offset of an access violation.

faulthandler shows only Python frames, so the intermittent CI access violation
surfaced at unrelated lines (wherever corrupted memory was next touched). This
vectored handler records the faulting instruction as module+offset, the address
that was read or written, and the module return addresses found on the
faulting thread's stack, then lets the exception continue to faulthandler.
It only reads process memory and writes to stderr; it never handles the fault.
"""

import ctypes
import os
import sys
from ctypes import wintypes

_ACCESS_VIOLATION = 0xC0000005
_FROM_ADDRESS = 0x4 | 0x2  # GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | UNCHANGED_REFCOUNT
_RSP, _RIP = 0x98, 0xF8  # x64 CONTEXT offsets
_reports = 0
_handler = None


class _Record(ctypes.Structure):
    _fields_ = [
        ('code', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('record', ctypes.c_void_p),
        ('address', ctypes.c_void_p),
        ('count', wintypes.DWORD),
        ('information', ctypes.c_size_t * 15),
    ]


class _Pointers(ctypes.Structure):
    _fields_ = [('record', ctypes.POINTER(_Record)), ('context', ctypes.c_void_p)]


def _module(kernel, address):
    handle = wintypes.HMODULE()
    if not address or not kernel.GetModuleHandleExW(_FROM_ADDRESS, ctypes.c_void_p(address), ctypes.byref(handle)):
        return None
    name = ctypes.create_unicode_buffer(260)
    kernel.GetModuleFileNameW(handle, name, 260)
    return os.path.basename(name.value) + '+0x%x' % (address - handle.value)


def install(stream=None):
    """Install once on Windows x64; elsewhere this is a no-op."""
    global _handler
    if os.name != 'nt' or ctypes.sizeof(ctypes.c_void_p) != 8 or _handler is not None:
        return
    stream = stream or sys.stderr
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetModuleHandleExW.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.HMODULE)]
    kernel.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetCurrentThreadStackLimits.argtypes = [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
    kernel.AddVectoredExceptionHandler.argtypes = [wintypes.ULONG, ctypes.c_void_p]
    kernel.AddVectoredExceptionHandler.restype = ctypes.c_void_p
    callback = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.POINTER(_Pointers))

    def handle(pointers):
        global _reports
        record = pointers.contents.record.contents
        if record.code != _ACCESS_VIOLATION or _reports >= 3:
            return 0  # EXCEPTION_CONTINUE_SEARCH
        _reports += 1
        context = pointers.contents.context
        rip = ctypes.c_uint64.from_address(context + _RIP).value
        rsp = ctypes.c_uint64.from_address(context + _RSP).value
        low, high = ctypes.c_size_t(), ctypes.c_size_t()
        kernel.GetCurrentThreadStackLimits(ctypes.byref(low), ctypes.byref(high))
        lines = [
            'native access violation #%d: %s at %s, %s address 0x%x'
            % (_reports, 'write' if record.information[0] == 1 else 'read', _module(kernel, rip) or hex(rip), 'accessing', record.information[1])
        ]
        frames = []
        if low.value <= rsp < high.value:
            stop = min(high.value, rsp + 0x6000)
            for slot in range(rsp, stop, 8):
                name = _module(kernel, ctypes.c_uint64.from_address(slot).value)
                if name is not None:
                    frames.append(name)
                if len(frames) >= 64:
                    break
        lines.extend('  stack ' + frame for frame in frames)
        stream.write('\n'.join(lines) + '\n')
        stream.flush()
        return 0

    _handler = callback(handle)
    kernel.AddVectoredExceptionHandler(1, ctypes.cast(_handler, ctypes.c_void_p))
