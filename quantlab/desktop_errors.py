"""Fixed desktop error catalogue. Exception values never become display/log text."""

import sqlite3
from .errors import ErrorCode as ErrorCode, ErrorText as ErrorText, ERROR_LABELS as ERROR_LABELS, ERROR_TABLE


def error_message(code):
    code = code if isinstance(code, str) and code in ERROR_TABLE else 'operation_failed'
    text = ERROR_TABLE[code]
    return f'{text.explanation} {text.action}（錯誤代碼：{code}）'


def exception_code(exc):
    # Only exact allowlisted constants may be inspected; never call str/repr.
    code = getattr(exc, 'code', None)
    if isinstance(code, str) and code in ERROR_TABLE:
        return code
    if len(exc.args) == 1 and type(exc.args[0]) is str and exc.args[0] in ERROR_TABLE:
        return exc.args[0]
    if isinstance(exc, (OSError, sqlite3.Error)):
        return 'operation_failed_local'
    if isinstance(exc, ValueError):
        return 'validation_failed'
    return 'operation_failed'


def startup_error_code(exc):
    # Keep the shared safety type local to startup classification.
    from .runtime_support import RuntimeSafetyError

    if isinstance(exc, RuntimeSafetyError) and len(exc.args) == 1 and type(exc.args[0]) is str:
        return {
            'This workspace requires a WAL-safe SQLite runtime (3.51.3 or newer)': 'startup_sqlite_old',
            'Unsupported workspace version; original preserved': 'startup_workspace_incompatible',
            'Unsupported workspace pointer; original preserved': 'startup_workspace_incompatible',
            'Another MarkAuto instance is using this installation': 'startup_workspace_busy',
        }.get(exc.args[0], 'startup_failed')
    return 'startup_failed'
