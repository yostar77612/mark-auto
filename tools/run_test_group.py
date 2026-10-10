"""Run exact, module-granularity partitions of the ordinary unittest discovery.

Windows timings from the 12e088f full-suite run put saved-pool/research and
walk-forward integration in a separate job. New modules default to core; no
case is excluded. Module boundaries preserve unittest module/class fixtures.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import sys
import unittest

# Running this file directly must have the same application import path as
# `python -m unittest discover -s tests`.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESEARCH_MODULES = frozenset({
    "test_saved_candidate_pool", "test_desktop_saved_candidate_pool",
    "test_research", "test_walk_forward", "test_desktop_walk_forward",
    "test_desktop_walk_forward_runtime", "test_desktop_walk_forward_smoke",
    "test_desktop_walk_forward_terminal", "test_result_reference_layers",
})
GROUPS = ("all", "core", "research")


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def partition(suite):
    """Validate exact coverage before execution; retain discovery order."""
    discovered = list(cases(suite))
    ids = [case.id() for case in discovered]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Discovery must be nonempty with unique test IDs")
    selected = {"core": [], "research": []}
    for case in discovered:
        group = "research" if type(case).__module__ in RESEARCH_MODULES else "core"
        selected[group].append(case)
    core = {case.id() for case in selected["core"]}
    research = {case.id() for case in selected["research"]}
    if not core or not research or core & research or core | research != set(ids):
        raise ValueError("Core/research must be nonempty, disjoint, and cover discovery exactly")
    return {"all": suite, **{name: unittest.TestSuite(items) for name, items in selected.items()}}


class RecordingResult(unittest.TextTestResult):
    """Record actual starts separately: failed fixtures can prevent starts."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started_ids = []

    def startTest(self, test):
        self.started_ids.append(test.id())
        super().startTest(test)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=GROUPS, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--start-directory", default="tests")
    args = parser.parse_args(argv)
    loader = unittest.TestLoader()
    suite = loader.discover(args.start_directory)
    manifest = {
        "head_sha": os.environ.get("GITHUB_SHA"),
        "python": platform.python_version(), "platform": sys.platform,
        "group": args.group, "discovered_ids": [case.id() for case in cases(suite)],
        "selected_ids": [], "partitions": {}, "discovery_errors": list(loader.errors),
        "run_completed": False, "started_ids": [],
    }
    try:
        if loader.errors:
            raise ValueError("Discovery failed:\n" + "\n".join(loader.errors))
        groups = partition(suite)
        manifest["partitions"] = {
            name: [case.id() for case in cases(groups[name])] for name in ("core", "research")
        }
        manifest["selected_ids"] = [case.id() for case in cases(groups[args.group])]
    except ValueError as error:
        manifest["selection_error"] = str(error)
        print(error, file=sys.stderr)
        status = 2
    else:
        status = None
    # Written before running tests so a failure/cancellation still has inventory.
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if status is not None:
        return status
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(groups[args.group])
    manifest.update({
        "run_completed": True, "started_ids": result.started_ids,
        "tests_run": result.testsRun, "successful": result.wasSuccessful(),
        "failures": [test.id() for test, _ in result.failures],
        "errors": [test.id() for test, _ in result.errors],
        "skipped": [{"id": test.id(), "reason": reason} for test, reason in result.skipped],
        "expected_failures": [test.id() for test, _ in result.expectedFailures],
        "unexpected_successes": [test.id() for test in result.unexpectedSuccesses],
    })
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
