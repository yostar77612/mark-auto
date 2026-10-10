"""Fail closed until the exact release SHA passes every quantlab workflow job."""
import json
import os
import subprocess
import time


def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', path], text=True))


REQUIRED_JOBS = frozenset({
    "Static quality and credential gate", "Dependency audit (ui)", "ui",
    "offline (ubuntu-latest, 3.11)", "offline (ubuntu-latest, 3.12)",
    "offline (windows-latest, 3.11)", "offline (windows-latest, 3.12)",
})


def require_main_ancestry(repository, sha):
    comparison = api(f"repos/{repository}/compare/{sha}...main")
    if comparison.get("merge_base_commit", {}).get("sha") != sha or comparison.get("status") not in {"identical", "ahead"}:
        raise RuntimeError("Release SHA is not reachable from main; publication refused")


def main():
    repository, sha = os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_SHA']
    require_main_ancestry(repository, sha)
    deadline = time.monotonic() + 20 * 60
    while time.monotonic() < deadline:
        result = api(f'repos/{repository}/actions/workflows/quantlab.yml/runs?head_sha={sha}&per_page=100')
        runs = [run for run in result['workflow_runs'] if run['head_sha'] == sha
                and run['event'] in ('push', 'workflow_dispatch')]
        if runs:
            run = max(runs, key=lambda item: (item['run_number'], item['run_attempt']))
            if run['status'] == 'completed':
                if run['conclusion'] != 'success':
                    raise RuntimeError('Exact-head Quantlab gates failed; release refused')
                jobs = api(f"repos/{repository}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100")
                if not jobs['jobs'] or jobs['total_count'] != len(jobs['jobs']):
                    raise RuntimeError('Missing or incomplete job evidence; release refused')
                names = [job.get('name') for job in jobs['jobs']]
                if not REQUIRED_JOBS <= set(names) or len(names) != len(set(names)):
                    raise RuntimeError('Required named jobs missing or ambiguous; release refused')
                if any(job['conclusion'] != 'success' for job in jobs['jobs']):
                    raise RuntimeError('Every Quantlab job must pass; release refused')
                require_main_ancestry(repository, sha)  # Recheck after waiting; no stale tag provenance.
                print(f"Exact-head gates verified: {run['html_url']} ({sha})")
                return
        print('Waiting for exact-head Quantlab gates; publication remains blocked.', flush=True)
        time.sleep(30)
    raise RuntimeError('Exact-head Quantlab gates missing/incomplete after 20 minutes; release refused')


if __name__ == '__main__':
    main()
