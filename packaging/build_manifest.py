"""Record exact inputs, environment and artifact digests; no bit-identical claim."""
import hashlib
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    inputs = [p for pattern in ('packaging/*', 'requirements-desktop.*', 'desktop*.py', 'desktop_chatgpt_dependency_manifest.json', 'packaging/third_party/*', 'tools/quality_gate.py',
                               'quantlab/*.py', 'examples/*', '.github/workflows/windows-desktop.yml')
              for p in root.glob(pattern) if p.is_file()]
    artifacts = list((root / 'dist/installers').glob('*.exe')) + list((root / 'dist').glob('MarkAuto-*-clean-windows-acceptance.zip'))
    result = {
        'source_commit': os.environ.get('GITHUB_SHA') or subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'python': sys.version, 'python_executable_sha256': sha256(sys.executable), 'os': platform.platform(), 'architecture': platform.machine(),
        'runner_image': os.environ.get('ImageOS'), 'runner_image_version': os.environ.get('ImageVersion'),
        'dependencies': sorted(f"{d.metadata['Name']}=={d.version}" for d in distributions()),
        'inputs_sha256': {str(p.relative_to(root)): sha256(p) for p in sorted(inputs)},
        'artifacts_sha256': {p.name: sha256(p) for p in sorted(artifacts)},
        'repeatability': 'Pinned input recipe; PE/compiler timestamps mean bit-identical output is not promised.',
        'signing': 'UNSIGNED: no signing certificate or security-warning bypass',
        'windows_10_22h2_clean_acceptance': 'BLOCKED', 'windows_11_clean_acceptance': 'BLOCKED',
    }
    (root / 'dist/build-manifest.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    (root / 'dist/SHA256SUMS.txt').write_text(''.join(f'{sha256(p)}  {p.name}\n' for p in sorted(artifacts)), encoding='ascii')


if __name__ == '__main__':
    main()
