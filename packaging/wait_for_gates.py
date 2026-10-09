"""Fail closed until the exact release SHA passes every quantlab workflow job."""
import json
import os
import subprocess
import time


def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', path], text=True))


def main():
    repository, sha = os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_SHA']
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
                if any(job['conclusion'] != 'success' for job in jobs['jobs']):
                    raise RuntimeError('Every Quantlab job must pass; release refused')
                print(f"Exact-head gates verified: {run['html_url']} ({sha})")
                return
        print('Waiting for exact-head Quantlab gates; publication remains blocked.', flush=True)
        time.sleep(30)
    raise RuntimeError('Exact-head Quantlab gates missing/incomplete after 20 minutes; release refused')


if __name__ == '__main__':
    main()
