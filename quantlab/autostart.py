"""Explicit, current-user Windows startup registration for the installed app.

The registration launches only the executable, with no trading or resume flags.
An existing opt-in follows the executable after an update or a manual move.
"""

from pathlib import Path
import sys

from quantlab.errors import AutostartError

try:
    import winreg
except ImportError:
    winreg = None


RUN_KEY_PATH = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_VALUE_NAME = 'MarkAuto'


class RunAutostart:
    """Own exactly one HKCU value; tests supply a private key path."""

    def __init__(self, executable: Path, *, key_path: str = RUN_KEY_PATH):
        self.executable = executable.resolve()
        self.key_path = key_path

    @property
    def command(self) -> str:
        return f'"{self.executable}"'

    def _stored_value(self) -> tuple | None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key_path, 0, winreg.KEY_QUERY_VALUE) as key:
                return winreg.QueryValueEx(key, RUN_VALUE_NAME)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise AutostartError('autostart_read_failed') from exc

    def enabled(self) -> bool:
        return self._stored_value() is not None

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            try:
                with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.key_path, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, self.command)
            except OSError as exc:
                raise AutostartError('autostart_write_failed') from exc
        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key_path, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
            except FileNotFoundError:
                return
            except OSError as exc:
                raise AutostartError('autostart_remove_failed') from exc

    def repair_enabled(self) -> bool:
        """Correct an existing opt-in, without creating a default registration."""
        stored = self._stored_value()
        if stored is None:
            return False
        if stored != (self.command, winreg.REG_SZ):
            self.set_enabled(True)
        return True


def installed_autostart() -> RunAutostart | None:
    """Source runs and non-Windows previews must never register the interpreter."""
    if winreg is None or not getattr(sys, 'frozen', False):
        return None
    executable = Path(sys.executable)
    if executable.name.casefold() != 'markauto.exe':
        return None
    return RunAutostart(executable)


def repair_autostart() -> str | None:
    """Run once at app startup; expose a fixed error code without blocking startup."""
    controller = installed_autostart()
    if controller is not None:
        try:
            controller.repair_enabled()
        except AutostartError as exc:
            return exc.code
    return None
