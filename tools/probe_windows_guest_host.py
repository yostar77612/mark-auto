"""Observe potential VM host resources without installing or enabling anything.

This is availability evidence only. It never starts a guest, opens /dev/kvm,
changes permissions, inspects credentials, or establishes Windows acceptance.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import tempfile


def cpu_virtualization_flags(path=Path('/proc/cpuinfo')):
    """Return only allowed flags; never include CPU IDs or raw host metadata."""
    try:
        with path.open(encoding='utf-8', errors='replace') as stream:
            flags = set()
            for line in stream:
                name, separator, value = line.partition(':')
                if separator and name.strip() in ('flags', 'Features'):
                    flags.update(set(value.split()) & {'vmx', 'svm'})
        return {'readable': True, 'flags': sorted(flags)}
    except OSError:
        return {'readable': False, 'flags': []}


def kvm_availability(path=Path('/dev/kvm')):
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        return {'exists': False, 'character_device': False,
                'readable': False, 'writable': False, 'stat_available': True}
    except OSError:
        return {'exists': None, 'character_device': None,
                'readable': False, 'writable': False, 'stat_available': False}
    return {'exists': True, 'character_device': stat.S_ISCHR(mode),
            'readable': os.access(path, os.R_OK),
            'writable': os.access(path, os.W_OK), 'stat_available': True}


def disk_capacity(path):
    try:
        usage = shutil.disk_usage(path)
        return {'available': True, 'total_bytes': usage.total,
                'free_bytes': usage.free}
    except OSError:
        return {'available': False, 'total_bytes': None, 'free_bytes': None}


def collect_report(workspace):
    return {
        'schema_version': 1,
        'observation_only': True,
        'windows_client_acceptance': 'NOT_RUN',
        'guest_started': False,
        'os': {'system': platform.system(), 'release': platform.release(),
               'architecture': platform.machine()},
        'kvm': kvm_availability(),
        'cpu_virtualization': cpu_virtualization_flags(),
        'disk': {'workspace': disk_capacity(workspace),
                 'temporary': disk_capacity(tempfile.gettempdir())},
        'tools_on_path': {name: shutil.which(name) is not None for name in (
            'qemu-system-x86_64', 'qemu-img', 'swtpm')},
        'limits': [
            'Device access flags do not establish usable KVM or nested virtualization.',
            'No OS image, guest license, TPM, Secure Boot, or clean-client test was verified.',
        ],
    }


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic output; a failed write cannot leave a partially valid JSON report.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write('\n')
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    write_report(args.output, collect_report(Path.cwd()))
    print('Host availability report written; Windows client acceptance remains NOT_RUN.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
