"""Observe potential VM host resources without installing or enabling anything.

This is availability evidence only. The default report never opens /dev/kvm.
The explicit --query-kvm-api mode opens only that fixed device and issues fixed
read-only system queries. Neither mode creates or starts a guest, changes
permissions, inspects credentials, or establishes Windows acceptance.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import tempfile

try:
    import fcntl
except ImportError:  # The ordinary availability report also runs on Windows.
    fcntl = None


# Linux x86_64 UAPI constants. No callers can supply paths, ioctl numbers,
# capability IDs, or a VM fd. System queries do not create a VM or enable KVM.
# https://www.kernel.org/doc/html/latest/virt/kvm/api.html
# https://github.com/torvalds/linux/blob/master/include/uapi/linux/kvm.h
KVM_GET_API_VERSION = 0xAE00
KVM_CHECK_EXTENSION = 0xAE03
KVM_API_VERSION = 12
KVM_QUERY_CAPABILITIES = (
    ('KVM_CAP_IRQCHIP', 0), ('KVM_CAP_USER_MEMORY', 3),
    ('KVM_CAP_NR_VCPUS', 9), ('KVM_CAP_MAX_VCPUS', 66),
)


def query_kvm_api():
    """Explicit opt-in: fixed control-device queries only, never a guest."""
    result = {'status': 'not_queried', 'stage': 'platform', 'errno': None,
              'api_version': None, 'extensions': {},
              'close_status': 'not_opened', 'close_errno': None}
    if platform.system() != 'Linux':
        result['status'] = 'unsupported_platform'
        return result
    # The numeric ioctl encoding here is verified for Linux x86_64 only.
    if platform.machine().lower() not in ('x86_64', 'amd64'):
        result['status'] = 'unsupported_architecture'
        return result
    if fcntl is None or not all(hasattr(os, flag) for flag in (
            'O_CLOEXEC', 'O_NOFOLLOW', 'O_NONBLOCK')):
        result['status'] = 'query_support_unavailable'
        return result
    fd = None
    try:
        result['stage'] = 'open'
        # O_RDWR follows the KVM API opening convention. Only observation
        # ioctls below are allowed; no write, mmap, VM, VCPU or RUN operation.
        fd = os.open('/dev/kvm', os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW
                     | os.O_NONBLOCK)
        result['stage'] = 'fstat'
        device = os.fstat(fd)
        if not stat.S_ISCHR(device.st_mode):
            result['status'] = 'not_character_device'
            return result
        # KVM is the fixed Linux misc character device 10:232. Refuse an
        # unrelated character device even if it appears at the fixed path.
        # include/uapi/linux/major.h and include/linux/miscdevice.h
        if (os.major(device.st_rdev), os.minor(device.st_rdev)) != (10, 232):
            result['status'] = 'unexpected_device'
            return result
        result['stage'] = 'api_version'
        version = fcntl.ioctl(fd, KVM_GET_API_VERSION, 0)
        result['api_version'] = version
        if version != KVM_API_VERSION:
            result['status'] = 'unsupported_api_version'
            return result
        result['status'] = 'api_available'
        result['stage'] = 'extensions'
        for name, capability in KVM_QUERY_CAPABILITIES:
            try:
                value = fcntl.ioctl(fd, KVM_CHECK_EXTENSION, capability)
                result['extensions'][name] = {
                    'status': ('supported' if value > 0 else
                               'unsupported' if value == 0 else 'invalid_result'),
                    'value': value, 'errno': None}
            except OSError as error:
                result['extensions'][name] = {
                    'status': 'query_failed', 'value': None, 'errno': error.errno}
        result['stage'] = 'complete'
    except OSError as error:
        result['errno'] = error.errno
        if error.errno in (errno.EACCES, errno.EPERM):
            result['status'] = 'permission_denied'
        elif result['stage'] == 'open' and error.errno == errno.ENOENT:
            result['status'] = 'device_missing'
        elif result['stage'] == 'open' and error.errno == errno.ELOOP:
            result['status'] = 'symlink_refused'
        else:
            result['status'] = 'query_failed'
    finally:
        if fd is not None:
            try:
                os.close(fd)
                result['close_status'] = 'closed'
            except OSError as error:
                # Do not retry close: Linux may already have released this fd.
                result['close_status'] = 'close_failed'
                result['close_errno'] = error.errno
    return result


def collect_kvm_api_report():
    return {
        'schema_version': 1,
        'observation_only': True,
        'windows_client_acceptance': 'NOT_RUN',
        'guest_started': False,
        'kvm_api': query_kvm_api(),
        'limits': [
            'KVM API access does not establish nested guest execution or Windows acceptance.',
            'No VM, VCPU, guest memory, image, license, TPM or Secure Boot was created or verified.',
            'Host availability is diagnostic evidence, not a product acceptance gate.',
        ],
    }


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
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--output', type=Path, help='Write the no-open availability report.')
    mode.add_argument('--query-kvm-api', action='store_true',
                      help='Opt in to fixed /dev/kvm query ioctls; JSON to stdout only.')
    args = parser.parse_args(argv)
    if args.query_kvm_api:
        # The unprivileged caller owns stdout redirection. This mode does not
        # accept an output path or write any host/repository file as root.
        print(json.dumps(collect_kvm_api_report(), indent=2, sort_keys=True))
        return 0  # Unavailable KVM is evidence, never a failed product test.
    write_report(args.output, collect_report(Path.cwd()))
    print('Host availability report written; Windows client acceptance remains NOT_RUN.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
