import sqlite3
from quantlab.errors import ERROR_TABLE


def exception_code(exc):
    code = getattr(exc, 'code', None)
    if isinstance(code, str) and code in ERROR_TABLE:
        return code
    if len(exc.args) == 1 and type(exc.args[0]) is str and (exc.args[0] in ERROR_TABLE):
        return exc.args[0]
    if isinstance(exc, (OSError, sqlite3.Error)):
        return 'operation_failed_local'
    if isinstance(exc, ValueError):
        return 'validation_failed'
    return 'operation_failed'
