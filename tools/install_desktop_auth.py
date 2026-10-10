"""CI-only auth wheel installer; derive one native hash lock from shipped manifest.

Uses pip's resolver (including PyJWT's crypto extra), permits wheels only, and
forces reinstall so even preinstalled packages produce verified artifact evidence.
No account, credential, endpoint, or application smoke operations are performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from desktop_chatgpt_provider import _dependency_manifest, _dependency_target, implementation_provenance


def requirements_text(manifest, target):
    """Input manifest must pass the provider's strict validator first."""
    lines = []
    for item in manifest['targets'][target]['dependencies']:
        name = item['distribution']
        if name == 'PyJWT':
            name += '[crypto]'
        lines.append(f"{name}=={item['version']} --hash=sha256:{item['wheel_sha256']}")
    return '\n'.join(lines) + '\n'


def validate_install_report(report, dependencies):
    """Require the exact closure and downloaded hashes; versions alone cannot pass."""
    def canonical(name):
        return re.sub(r'[-_.]+', '-', name).lower()
    expected = {canonical(item['distribution']): item for item in dependencies}
    installed = report.get('install')
    if not isinstance(installed, list) or len(installed) != len(expected):
        raise ValueError('auth_install_report_closure_mismatch')
    seen = set()
    for entry in installed:
        metadata = entry['metadata']
        name = canonical(metadata['name'])
        if name not in expected or name in seen or metadata['version'] != expected[name]['version']:
            raise ValueError('auth_install_report_dependency_mismatch')
        download = entry['download_info']
        if (not urlsplit(download['url']).path.endswith('.whl')
                or download['archive_info']['hashes'].get('sha256') != expected[name]['wheel_sha256']):
            raise ValueError('auth_install_report_artifact_mismatch')
        seen.add(name)


def install(report_path, wheelhouse=None):
    raw, manifest, _ = _dependency_manifest()
    target = _dependency_target()
    with tempfile.TemporaryDirectory(prefix='markauto-auth-install-') as directory:
        lock = Path(directory) / 'requirements.lock'
        pip_report = Path(directory) / 'pip-report.json'
        lock.write_text(requirements_text(manifest, target), encoding='utf-8')
        command = [sys.executable, '-m', 'pip', '--isolated', '--disable-pip-version-check',
                   'install', '--require-hashes', '--only-binary=:all:', '--force-reinstall',
                   '--no-cache-dir', '--report', str(pip_report), '-r', str(lock)]
        if wheelhouse is None:
            command.extend(['--index-url', 'https://pypi.org/simple'])
        else:
            command.extend(['--no-index', '--find-links', str(wheelhouse.resolve())])
        subprocess.run(command, check=True)
        report = json.loads(pip_report.read_text(encoding='utf-8'))
    validate_install_report(report, manifest['targets'][target]['dependencies'])
    provenance = implementation_provenance()
    digest = hashlib.sha256(raw).hexdigest()
    if provenance['dependency_target'] != target or provenance['dependency_manifest_sha256'] != digest:
        raise ValueError('auth_install_manifest_changed')
    report['markauto_auth'] = {'dependency_target': target, 'dependency_manifest_sha256': digest,
                              'hash_locked_install_verified': True, 'provenance': provenance}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(report['markauto_auth'], sort_keys=True))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=Path('dist/validation/desktop-auth-install.json'))
    parser.add_argument('--wheelhouse', type=Path, help='Use only a local wheelhouse, still enforcing all hashes')
    args = parser.parse_args()
    install(args.report, args.wheelhouse)


if __name__ == '__main__':
    main()
