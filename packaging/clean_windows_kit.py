"""Maintainer-only kit assembly. The resulting Windows kit needs no Python/Git."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

ENGINE = ('core.py', 'data.py', 'strategies.py', 'backtest.py', 'research.py', 'provider.py')


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def release(folder, version):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Numeric release version required')
    folder = Path(folder)
    manifest_path = folder / 'build-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    installer = folder / f'MarkAuto-{version}-windows-x64-setup.exe'
    if digest(installer) != manifest['artifacts_sha256'][installer.name]:
        raise ValueError('Installer digest differs from build manifest')
    if not re.fullmatch(r'[a-f0-9]{40}', manifest['source_commit']):
        raise ValueError('Exact source commit required')
    inputs = {key.replace('\\', '/'): value for key, value in manifest['inputs_sha256'].items()}
    for name in ENGINE:
        if not re.fullmatch(r'[a-f0-9]{64}', inputs['quantlab/' + name]):
            raise ValueError('Engine source digest missing or invalid')
    return installer, manifest_path, manifest


def assemble(baseline, candidate, baseline_version, version, output):
    old = release(baseline, baseline_version)
    new = release(candidate, version)
    if baseline_version == '0.0.0' or tuple(map(int, baseline_version.split('.'))) >= tuple(map(int, version.split('.'))):
        raise ValueError('Historical baseline must be a real, strictly older release')
    if old[2]['source_commit'] == new[2]['source_commit'] or digest(old[0]) == digest(new[0]):
        raise ValueError('Historical upgrade needs distinct commits and installers')
    output = Path(output)
    if output.exists():
        raise FileExistsError('Refusing to overwrite an existing kit or evidence')
    output.mkdir(parents=True)
    (output / 'packaging').mkdir()
    (output / 'dist/installers').mkdir(parents=True)
    here = Path(__file__).resolve().parent
    for name in ('test_installer.ps1', 'clean_windows_acceptance.ps1', 'clean_windows_README.md'):
        shutil.copyfile(here / name, output / 'packaging' / name)
    for label, data in (('baseline', old), ('candidate', new)):
        shutil.copyfile(data[0], output / 'dist/installers' / data[0].name)
        shutil.copyfile(data[1], output / f'{label}-manifest.json')
    files = {p.relative_to(output).as_posix(): digest(p) for p in sorted(output.rglob('*')) if p.is_file()}
    descriptor = {'schema_version': 1, 'baseline_version': baseline_version, 'version': version,
                  'baseline_commit': old[2]['source_commit'], 'candidate_commit': new[2]['source_commit'],
                  'files_sha256': files, 'full_acceptance': 'EXTERNAL BLOCKED'}
    (output / 'kit.json').write_text(json.dumps(descriptor, indent=2) + '\n', encoding='utf-8')
    return descriptor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'candidate', 'baseline-version', 'version', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    assemble(args.baseline, args.candidate, args.baseline_version, args.version, args.output)


if __name__ == '__main__':
    main()
