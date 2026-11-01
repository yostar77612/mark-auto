# M2-0 incomplete retry: execution-context diagnosis

The second attempt used the same clean source `97e2a8b` and exact complete
unittest command but was launched in the restricted execution context by the
coordinator. It stopped making visible progress after 14:00:52 on 2026-11-01.
This attempt is **INCOMPLETE** and is excluded from passing or full-suite counts.

Read-only process samples identified its exact native interpreter PID 232672,
wrapper 234748, original creation time 13:59:56, four threads and a continuously
busy main thread. There was sufficient free physical memory (about 12 GB).
Two narrowly scoped native stack captures suspended only that original main
thread for 4.269 and 6.5772 ms; both resumed successfully in `finally`. They
showed Windows file/directory calls from Python, not a Qt-native stack. An early
Qt destruction hypothesis was withdrawn when this evidence contradicted it.

The official PyPI py-spy 0.4.2 Windows wheel was downloaded to ignored scratch,
verified against SHA256
`8b06a353c177677e4e1701b288d8c58e2f8d4208ee81a8048d9f72ba800918f8`, and only
its portable executable was extracted. It was not installed and changed no
project dependency. A stack-only `dump --pid 232672` (no locals, heap dump or
subprocess scan) identified this exact call chain:

```text
tempfile._mkstemp_inner:263
tempfile.mkstemp:358
packaging/fetch_baseline.py:fetch:32
test_baseline_download.py:test_changed_or_oversized_download_never_promotes_partial:35
```

The local Python 3.13.11 source at line 263 is the Windows PermissionError
retry branch. Its original `TMP_MAX` is 2,147,483,647. Thus the busy loop was
repeated failure to create a synthetic temporary file, not a failing market
request, broker login or product execution path. PowerShell line buffering
explains why the next test's starting text was not visible until termination.

Under the normal user execution context, the unchanged three-case
`test_baseline_download` module passed in 0.018 s. No test, timeout, skip,
filesystem ACL, Windows policy, Python source or dependency was changed.

A fresh census found no descendants of the original runner. The coordinator
retained its process handle, checked its creation FILETIME
134379863962840032 and parent identity again, terminated only that unfinished
QA runner with code 137, and verified both it and its wrapper exited. No
desktop engine, user application or user data was stopped/deleted. The strict
wrapper then reported `complete: false`; its generic closing message is not
completion evidence.

The third complete attempt started at 14:15:26 in the normal user context,
with identical source and command. It passed the previously stuck case during
full discovery. Its eventual full result is separate evidence; starting or
advancing this run does not establish completion. Subsequent full suites use
the same normal execution context to avoid this harness mistake.

Local diagnostic artifacts remain in ignored `.tmp-m2-qa/`; the incomplete
full log is `.tmp-m2-policy-retry-full.log`, and the independent complete retry
log is `.tmp-m2-policy-isolated-full.log`.
