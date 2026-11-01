# Verified broker SDK build contract

The default `packaging/build.ps1` now includes the existing verified broker
flavor. It downloads only the official wheel allowed by
`requirements-shioaji-v2.lock`, installs it in the private SQLite interpreter,
and calls `installed_sdk` to verify every package/metadata file before tests and
again before PyInstaller collection. The desktop dependency lock and SQLite gate
remain intact. Installing Shioaji into another Python environment does **not**
add it to an existing frozen MarkAuto executable; rebuild/install the candidate.

The former opt-in portable recipe below remains available for a separate local
ZIP. Both outputs use `broker_package.py` and the same wheel/native pins,
not separate SDK collection implementations.

## Pinned inputs and isolation

- Windows x64 CPython 3.13.16 and the existing private SQLite 3.54.0 interpreter.
- All existing desktop dependencies from its reviewed private builder.
- `requirements-shioaji-v2.lock`: official Shioaji 1.7.9 Windows abi3 wheel,
  SHA256 `77c864aa5bcd0f873746cb10a55a484c7a38723df432a7778f328d5fb7f57be4`.
- Native `_core.pyd` SHA256
  `7844fb48ca1116fed793a03ab556c92049a243f9637062a4624a71590412de76`.
- Official metadata: <https://pypi.org/pypi/shioaji/1.7.9/json>. This wheel declares
  no mandatory Windows dependencies; non-Windows speed and test extras are not
  selected. Every installed SDK package/metadata file is checked against the
  hash-verified wheel, with exact package-file coverage.

The portable builder clones the supplied private interpreter to `build/broker-python` and
installs the SDK there using `--require-hashes --only-binary=:all: --no-index`.
It never installs globally, changes the registry or PATH globally, runs an
installer, publishes an artifact or creates a broker SDK client. Existing
different runtimes/artifacts are preserved rather than overwritten.

From the worktree root, prepare only while source validation is in progress:

```powershell
& "<pinned-private-python.exe>" -X utf8 packaging/build_broker_portable.py --base-python "<pinned-private-python.exe>" --sdk-wheel "<absolute-shioaji-1.7.9-wheel>" --prepare-only
```

After the engineering gates pass and reviewed source is committed locally:

```powershell
& "<pinned-private-python.exe>" -X utf8 packaging/build_broker_portable.py --base-python "<pinned-private-python.exe>" --sdk-wheel "<absolute-shioaji-1.7.9-wheel>" --freeze-reviewed-source
```

No PowerShell script execution-policy bypass is required. The explicit source
review flag is required for a full build; a dirty checkout is rejected. Merely
preparing dependencies does not count as a frozen artifact or desktop QA.

## Verified collection

During PyInstaller execution, the default builder sets `MARKAUTO_BROKER_BUILD=1`
and the exact `MARKAUTO_BROKER_WHEEL` path, restoring prior values afterward.
`broker_package.py` refuses missing/disabled flags, missing wheel paths,
unverified wheels or changed installed files before Analysis runs. Removing
`shioaji` from the spec exclusions therefore cannot collect an arbitrary
developer-installed SDK. The portable builder selects the same verification.
The resulting Analysis TOCs are checked as well: SDK Python/native sources must
come from that verified package and still match the wheel hashes. A shadow
module in a freezer search path, changed input or missing native core fails.

The SDK package/native extension, metadata and supplied SBOM are collected.
The wheel's `.data/scripts` standalone Shioaji CLI/server executable is not
collected or run. This application never starts its HTTP server. Existing
`trader`/`archives` exclusions, v1 permanent execution prohibitions, SQLite-first
and multiprocessing-before-Qt runtime-hook ordering remain in force.

The native SDK library necessarily contains its vendor's exported capabilities;
packaging it does not arm any trading operation. UI startup, profile loading and
readiness remain metadata-only. Read-only login is still a separate explicit
operation. This task performs no real SDK client construction, login, CA, order,
amendment, cancellation or position-changing test.

## No-login proof and provenance

Both packages support the existing dedicated early diagnostic:

```powershell
& "<broker-enabled-payload>/MarkAuto.exe" --broker-sdk-probe "<fresh-absolute-report.json>"
```

The SQLite startup gate runs first. The probe imports the actual bundled SDK
native module, requires its module and distribution versions to be 1.7.9,
requires both modules to load within this package, checks the native hash and
real method/enum shape, and actively denies SDK client construction while
checking the inert adapter factory. It creates no GUI, uses no broker reference
or credential resolver, and refuses an existing report. Normal parent and
multiprocessing arguments leave the diagnostic hook passive.

An explicit `broker_probe.py --source-runtime` preflight is also available; its
report states `frozen: false` and **cannot substitute for the actual EXE proof**.

The default installer CI runs this diagnostic through the actual installed
executable after candidate upgrade, with developer tools removed from PATH.
Missing SDK, wrong `__version__`, wrong native hash, non-frozen evidence or client
construction fails CI. Evidence is `validation/broker-sdk-installed-no-login.json`.
No SDK login, CA, order or network call is made. The standard `build-manifest.json`
records verified wheel/package hashes and independently hashes the bundled
`_core.pyd`; an unexpected standalone CLI is a build failure.

The portable build retains `broker-build.json`, metadata/SBOM/notice files under
`licenses/shioaji`, a payload inventory, Qt license audit, the actual frozen
probe report and `broker-build-manifest.json`. The latter records flavor,
source commit, SDK/wheel/native hashes and every payload file hash. It produces
a separate local portable ZIP, not an installer or publication. Private prepare
results and failed diagnostics must not be presented as completed native QA.

The official `shioaji-1.7.9-cp37-abi3-win_amd64.whl` METADATA does not declare an
SDK license (no License/License-Expression/License-File fields or license
classifier). It identifies the documentation/homepage as
<https://sinotrade.github.io/> and repository as
<https://github.com/Sinotrade/Shioaji>. The supplied native SBOM and metadata are
retained exactly under `_internal/licenses/shioaji`; absence of a declaration
does not establish redistribution clearance. The SDK does not inherit
MarkAuto's Apache-2.0 license. These facts were read from the hash-verified wheel,
not inferred from repository badges or package-index summaries.

When changing between offline and broker-enabled executables, close the old
selected engine normally before reopening its isolated v2 root. An existing
authenticated host is preserved rather than silently replaced. No original v1
workspace, data or credential store needs to be moved.
