# Windows native test environment

Run tests with isolated `LOCALAPPDATA`, `APPDATA`, `TEMP` and `TMP`,
`PYTHONUTF8=1` and `QT_QPA_PLATFORM=offscreen`. Keep all existing assertions,
workloads and deadlines. A source run is separate evidence from installer smoke.

## Retained process handles

On the investigated Windows host, `.venv/Scripts/python.exe` is a redirector:
`subprocess.Popen.pid` identifies the redirector while `os.getpid()` inside its
Python child identifies a different process. A handle value published by that
child cannot be duplicated from the redirector's handle table. Connection-probe
parent checks and descendant cleanup also require the actual Python process.

For native handle tests, use that virtual environment's actual base interpreter
and its existing installed packages. Do not bind a replacement process handle
from a reported PID, omit containment checks or relax cleanup assertions.
From the checkout root in PowerShell, after setting isolated directories:

```powershell
$venvPython = 'C:\path\to\checkout\.venv\Scripts\python.exe'
$nativePython = (& $venvPython -c 'import sys; print(sys._base_executable)').Trim()
$sitePackages = (& $venvPython -c 'import sysconfig; print(sysconfig.get_path("purelib"))').Trim()
$env:PYTHONPATH = $sitePackages + ';' + (Get-Location).Path
& $nativePython -m unittest discover -s tests -p test_windows_recovery_feasibility.py -v
& $nativePython -m unittest discover -s tests -p test_paper_diagnostics.py -v
& $nativePython -m unittest discover -s tests -p test_test_group.py -v
```

This selects the existing runtime and dependency files; it does not install or
change Python, SQLite, Windows policy, file permissions or test applicability.
For the complete source smoke suite, child fixtures deliberately replace
`PYTHONPATH` with their isolated network guard and checkout. Preserve dependency
discovery through a separate, explicit test-only user base before launching:

```powershell
$isolatedTestRoot = 'C:\path\to\isolated-test-data'
$env:PYTHONUSERBASE = Join-Path $isolatedTestRoot 'python-dependency-site'
& $nativePython -c 'from pathlib import Path; import site,sys; p=Path(site.getusersitepackages()); p.mkdir(parents=True,exist_ok=True); (p/"markauto-existing-venv.pth").write_text(sys.argv[1]+"\n",encoding="utf-8")' $sitePackages
```

This writes one path-only `.pth` file inside the test directory, pointing to the
same existing venv packages. It does not change the system/user Python profile or
the private base runtime. Keep `PYTHONUSERBASE` scoped to this test process and its
children; the original smoke isolation and network guard remain active. A missing
PySide6 import is an environment failure, never a passing or skipped smoke case.
The full-suite command remains `tools/run_test_group.py --group all --manifest
<isolated-output.json>` with the same interpreter/environment. Verify the child
PID equals the retained `Popen.pid` before treating native handle evidence as valid.

## Distinguish access denial from missing privilege

Synthetic raw `Path.replace` probes reproduced intermittent WinError 5 in both
the checkout and the system temporary directory. The same operation succeeded
milliseconds later without an ACL or attribute change. A controlled native reader
opened without delete sharing produces the same error. Restart Manager detected
that controlled reader, but did not identify an owner for the intermittent
failures; attributing them to a specific antivirus or process is unverified.

Shared atomic writes, reporting, campaign and WFO snapshot promotion retry only the identical rename
on Windows errors 5, 32 or 33, at most seven attempts with a 100 ms retry deadline.
Persistent denial still raises. Serialization, SQLite commits, research, consumed
ranges, cancellation and business deadlines are not retried or reset. Durable
promotion retains `MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH`.

WinError 1314 from creating a synthetic symlink is a different prerequisite
failure. The investigated unelevated token cannot create these links. Do not add
skips, replace native links with mocks, change ACLs, enable Developer Mode, disable
protection or grant permanent privileges to manufacture a pass. Record the failed
cases and use an explicitly authorized Windows test process with the required
privilege, or report them as blocked. Microsoft's [CreateSymbolicLinkW reference](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createsymboliclinkw)
documents the Developer Mode prerequisite for unprivileged link creation.

An AppContainer invocation is also distinct from a normal Windows process.
On the investigated host, a synthetic 0700 directory in the default AppContainer
TEMP refused child-file access while a 0777 directory permitted it; both worked
inside the explicitly allowed checkout. Native tests use a normal Windows process
and an explicitly isolated short TEMP. Do not alter the test's directory modes or
the host's ACLs to compensate for this execution-context restriction.
