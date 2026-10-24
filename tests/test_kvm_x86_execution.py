"""Compile-only production check and syscall-mocked KVM diagnostic tests.

The executable used by these tests cannot open a real device or create a VM:
its open/fstat/ioctl/mmap/munmap/close/signal/timer interfaces are replaced before
including the production source. No sudo, VM, image or external download runs.
"""

import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tools/selftest_kvm_x86_execution.c'
STRICT_FLAGS = ['-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-Wpedantic']
NATIVE_TESTS_SUPPORTED = platform.system() == 'Linux' and platform.machine().lower() in ('x86_64', 'amd64') and shutil.which('cc') is not None


HARNESS = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/kvm.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/time.h>
#include <unistd.h>

static int fake_open(const char *, int, ...);
static int fake_fstat(int, struct stat *);
static int fake_ioctl(int, unsigned long, ...);
static void *fake_mmap(void *, size_t, int, int, int, off_t);
static int fake_munmap(void *, size_t);
static int fake_close(int);
static int fake_sigaction(int, const struct sigaction *, struct sigaction *);
static int fake_setitimer(__itimer_which_t, const struct itimerval *, struct itimerval *);
static long fake_sysconf(int);
#define main diagnostic_main
#define open fake_open
#define fstat fake_fstat
#define ioctl fake_ioctl
#define mmap fake_mmap
#define munmap fake_munmap
#define close fake_close
#define sigaction(...) fake_sigaction(__VA_ARGS__)
#define setitimer fake_setitimer
#define sysconf fake_sysconf
#include "PRODUCTION_SOURCE"
#undef main
#undef open
#undef fstat
#undef ioctl
#undef mmap
#undef munmap
#undef close
#undef sigaction
#undef setitimer
#undef sysconf

static const char *scenario;
static const char *failure_target;
static unsigned int runs, calls;
static int live_fds[3], signal_active, timer_active;
static unsigned char *memory;
static struct kvm_run *run_state;
static char trace[4096];
static void (*alarm_handler)(int);

static int step(const char *name)
{
    assert(strlen(trace) + strlen(name) + 2 < sizeof(trace));
    strcat(trace, name);
    strcat(trace, ",");
    ++calls;
    if (strcmp(name, failure_target) == 0) {
        errno = EIO;
        return -1;
    }
    return 0;
}

static int fake_sigaction(int number, const struct sigaction *action, struct sigaction *previous)
{
    assert(number == SIGALRM && action != NULL);
    if (previous != NULL) {
        if (step("signal_install") < 0) return -1;
        assert(action->sa_flags == 0);
        memset(previous, 0, sizeof(*previous));
        alarm_handler = action->sa_handler;
        signal_active = 1;
    } else {
        if (step("signal_restore") < 0) return -1;
        signal_active = 0;
    }
    return 0;
}

static int fake_setitimer(__itimer_which_t which, const struct itimerval *timer,
                         struct itimerval *previous)
{
    assert(which == ITIMER_REAL && previous == NULL);
    assert(timer->it_interval.tv_sec == 0 && timer->it_interval.tv_usec == 0);
    assert(timer->it_value.tv_usec == 0);
    if (timer->it_value.tv_sec != 0) {
        assert(timer->it_value.tv_sec == 3 && signal_active);
        if (step("timer_arm") < 0) return -1;
        timer_active = 1;
    } else {
        if (step("timer_disarm") < 0) return -1;
        timer_active = 0;
    }
    return 0;
}

static long fake_sysconf(int name)
{
    assert(name == _SC_PAGESIZE);
    if (step("page_size") < 0) return -1;
    return strcmp(scenario, "page_size_wrong") == 0 ? 65536 : 4096;
}

static int fake_open(const char *path, int flags, ...)
{
    assert(strcmp(path, "/dev/kvm") == 0);
    assert(flags == (O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK));
    if (step("open_device") < 0) return -1;
    if (strcmp(scenario, "device_missing") == 0) { errno = ENOENT; return -1; }
    if (strcmp(scenario, "device_denied") == 0) { errno = EACCES; return -1; }
    if (strcmp(scenario, "device_symlink") == 0) { errno = ELOOP; return -1; }
    live_fds[0] = 1;
    return 100;
}

static int fake_fstat(int fd, struct stat *device)
{
    assert(fd == 100 && live_fds[0]);
    if (step("device_identity") < 0) return -1;
    memset(device, 0, sizeof(*device));
    device->st_mode = strcmp(scenario, "device_regular") == 0 ? S_IFREG : S_IFCHR;
    device->st_rdev = strcmp(scenario, "device_wrong_id") == 0 ? makedev(1, 3) : makedev(10, 232);
    return 0;
}

static int fake_ioctl(int fd, unsigned long request, ...)
{
    va_list args;
    va_start(args, request);
    if (request == KVM_SET_USER_MEMORY_REGION) {
        const struct kvm_userspace_memory_region *region = va_arg(args, const struct kvm_userspace_memory_region *);
        assert(fd == 101 && live_fds[1]);
        assert(region->slot == 0 && region->flags == 0);
        assert(region->guest_phys_addr == 0x1000 && region->memory_size == 4096);
        assert(region->userspace_addr == (uint64_t)(uintptr_t)memory);
        assert(memcmp(memory, "\xb0\x2a\xe6\xe9\xf4", 5) == 0);
        for (size_t i = 5; i < 4096; ++i) assert(memory[i] == 0);
        va_end(args);
        return step("register_memory");
    }
    if (request == KVM_GET_SREGS || request == KVM_SET_SREGS) {
        struct kvm_sregs *sregs = va_arg(args, struct kvm_sregs *);
        assert(fd == 102 && live_fds[2]);
        if (request == KVM_GET_SREGS) {
            memset(sregs, 0, sizeof(*sregs));
            sregs->cs.base = 0xffff0000;
            sregs->cs.selector = 0xf000;
            sregs->cr0 = 0x60000010;
        } else {
            assert(sregs->cs.base == 0 && sregs->cs.selector == 0);
            assert(sregs->cr0 == 0x60000010);
        }
        va_end(args);
        return step(request == KVM_GET_SREGS ? "get_sregs" : "set_sregs");
    }
    if (request == KVM_SET_REGS) {
        const struct kvm_regs *regs = va_arg(args, const struct kvm_regs *);
        struct kvm_regs expected = {.rip = 0x1000, .rflags = 2};
        assert(fd == 102 && live_fds[2]);
        assert(memcmp(regs, &expected, sizeof(expected)) == 0);
        va_end(args);
        return step("set_regs");
    }
    unsigned long argument = va_arg(args, unsigned long);
    va_end(args);
    switch (request) {
    case KVM_GET_API_VERSION:
        assert(fd == 100 && live_fds[0] && argument == 0);
        if (step("api_version") < 0) return -1;
        return strcmp(scenario, "api_wrong") == 0 ? 11 : 12;
    case KVM_CHECK_EXTENSION:
        assert(fd == 100 && live_fds[0] && argument == KVM_CAP_USER_MEMORY);
        if (step("memory_capability") < 0) return -1;
        return strcmp(scenario, "memory_unsupported") == 0 ? 0 : 1;
    case KVM_GET_VCPU_MMAP_SIZE:
        assert(fd == 100 && live_fds[0] && argument == 0);
        if (step("run_mapping_size") < 0) return -1;
        if (strcmp(scenario, "map_size_small") == 0) return 1;
        if (strcmp(scenario, "map_size_large") == 0) return 65536 + 4096;
        if (strcmp(scenario, "map_size_unaligned") == 0) return 12287;
        return 12288;
    case KVM_CREATE_VM:
        assert(fd == 100 && live_fds[0] && argument == 0 && !live_fds[1]);
        if (step("create_vm") < 0) return -1;
        live_fds[1] = 1;
        return 101;
    case KVM_CREATE_VCPU:
        assert(fd == 101 && live_fds[1] && argument == 0 && !live_fds[2]);
        if (step("create_vcpu") < 0) return -1;
        live_fds[2] = 1;
        return 102;
    case KVM_RUN:
        assert(fd == 102 && live_fds[2] && argument == 0 && run_state && memory);
        ++runs;
        assert(runs <= 2);
        if (step(runs == 1 ? "run_first" : "run_second") < 0) return -1;
        if (strcmp(scenario, "timeout_first") == 0 ||
                (runs == 2 && strcmp(scenario, "timeout_second") == 0)) {
            alarm_handler(SIGALRM);
            errno = EINTR;
            return -1;
        }
        if (strcmp(scenario, "timeout_after_exit") == 0) alarm_handler(SIGALRM);
        if (runs == 2) {
            run_state->exit_reason = strcmp(scenario, "halt_wrong") == 0 ? KVM_EXIT_IO : KVM_EXIT_HLT;
            return 0;
        }
        run_state->exit_reason = strcmp(scenario, "first_exit_wrong") == 0 ? KVM_EXIT_HLT : KVM_EXIT_IO;
        run_state->io.direction = KVM_EXIT_IO_OUT;
        run_state->io.size = 1;
        run_state->io.port = 0xe9;
        run_state->io.count = 1;
        run_state->io.data_offset = 4096;
        ((unsigned char *)run_state)[4096] = strcmp(scenario, "marker_wrong") == 0 ? 43 : 42;
        if (strcmp(scenario, "io_in") == 0) run_state->io.direction = KVM_EXIT_IO_IN;
        if (strcmp(scenario, "io_size") == 0) run_state->io.size = 2;
        if (strcmp(scenario, "io_port") == 0) run_state->io.port = 0xea;
        if (strcmp(scenario, "io_count") == 0) run_state->io.count = 2;
        if (strcmp(scenario, "io_header_offset") == 0) run_state->io.data_offset = 1;
        if (strcmp(scenario, "io_end_offset") == 0) run_state->io.data_offset = 12288;
        if (strcmp(scenario, "io_overflow_offset") == 0) run_state->io.data_offset = UINT64_MAX;
        return 0;
    default:
        /* A new or unexpected ioctl is forbidden, including host/device setup. */
        assert(!"non-allowlisted ioctl");
        return -1;
    }
}

static void *fake_mmap(void *address, size_t length, int protection, int flags, int fd, off_t offset)
{
    assert(address == NULL && offset == 0 && protection == (PROT_READ | PROT_WRITE));
    if (fd == -1) {
        assert(length == 4096 && flags == (MAP_PRIVATE | MAP_ANONYMOUS) && !memory);
        if (step("map_memory") < 0) return MAP_FAILED;
        memory = aligned_alloc(4096, length);
        assert(memory != NULL);
        memset(memory, 0, length);
        return memory;
    }
    assert(fd == 102 && live_fds[2] && length == 12288 && flags == MAP_SHARED && !run_state);
    if (step("map_run") < 0) return MAP_FAILED;
    run_state = calloc(1, length);
    assert(run_state != NULL);
    return run_state;
}

static int fake_munmap(void *address, size_t length)
{
    if (address == run_state) {
        assert(length == 12288);
        if (step("unmap_run") < 0) return -1;
        free(run_state);
        run_state = NULL;
    } else {
        assert(address == memory && length == 4096 && !live_fds[1] && !live_fds[2]);
        if (step("unmap_memory") < 0) return -1;
        free(memory);
        memory = NULL;
    }
    return 0;
}

static int fake_close(int fd)
{
    assert(fd >= 100 && fd <= 102 && live_fds[fd - 100]);
    live_fds[fd - 100] = 0;  /* close can release an fd even on EINTR. */
    return step(fd == 102 ? "close_vcpu" : fd == 101 ? "close_vm" : "close_kvm");
}

int main(int argc, char **argv)
{
    assert(argc == 3);
    scenario = argv[1];
    failure_target = argv[2];
    char *diagnostic_args[] = {"selftest", "--run-kvm-self-test", NULL};
    int result;
    if (strcmp(scenario, "no_arguments") == 0)
        result = diagnostic_main(1, diagnostic_args);
    else if (strcmp(scenario, "extra_arguments") == 0) {
        char *extra[] = {"selftest", "--run-kvm-self-test", "/private/payload", NULL};
        result = diagnostic_main(3, extra);
    } else if (strcmp(scenario, "arbitrary_payload") == 0) {
        char *extra[] = {"selftest", "--payload=/private/payload", NULL};
        result = diagnostic_main(2, extra);
    } else
        result = diagnostic_main(2, diagnostic_args);
    fprintf(stderr, "{\"trace\":\"%s\",\"calls\":%u,\"runs\":%u,"
            "\"live_fds\":%d,\"live_maps\":%d,\"signal_active\":%d,\"timer_active\":%d}\n",
            trace, calls, runs, live_fds[0] + live_fds[1] + live_fds[2],
            (memory != NULL) + (run_state != NULL), signal_active, timer_active);
    /* Release test allocations retained by injected munmap failures. */
    free(memory);
    free(run_state);
    return result;
}
'''


class KvmExecutionSourceContractTests(unittest.TestCase):
    def test_explicit_mode_and_mandatory_caller_timeout_are_documented(self):
        source = SOURCE.read_text(encoding='utf-8')
        self.assertIn('caller MUST enforce an external process timeout', source)
        self.assertIn('timeout --kill-after=2s 10s sudo -n', source)
        self.assertIn('argc != 2 || strcmp(argv[1], "--run-kvm-self-test") != 0', source)
        self.assertIn('#include <linux/kvm.h>', source)
        self.assertNotRegex(source, r'struct kvm_\w+\s*\{')
        self.assertIn('https://www.kernel.org/doc/html/latest/virt/kvm/api.html', source)
        self.assertIn('NOT_RUN', source)

    def test_resource_and_ioctl_surface_stays_fixed(self):
        source = SOURCE.read_text(encoding='utf-8')
        self.assertIn('{0xb0, 0x2a, 0xe6, 0xe9, 0xf4}', source)
        self.assertIn('#define GUEST_RAM_BYTES 4096U', source)
        self.assertIn('#define MAX_RUN_MAPPING_BYTES 65536U', source)
        self.assertIn('index < 2', source)
        self.assertEqual(
            set(re.findall(r'ioctl\([^,]+,\s*(KVM_\w+)', source)),
            {
                'KVM_GET_API_VERSION',
                'KVM_CHECK_EXTENSION',
                'KVM_GET_VCPU_MMAP_SIZE',
                'KVM_CREATE_VM',
                'KVM_SET_USER_MEMORY_REGION',
                'KVM_CREATE_VCPU',
                'KVM_GET_SREGS',
                'KVM_SET_SREGS',
                'KVM_SET_REGS',
                'KVM_RUN',
            },
        )
        for prohibited in (
            'system(',
            'execve(',
            'popen(',
            'socket(',
            'chmod(',
            'chown(',
            'KVM_CREATE_IRQCHIP',
            'KVM_SET_TSS_ADDR',
            'KVM_CREATE_DEVICE',
            'PROT_EXEC',
            '/proc/',
            '/sys/',
        ):
            self.assertNotIn(prohibited, source)


@unittest.skipUnless(NATIVE_TESTS_SUPPORTED, 'Linux x86_64 C harness requires the host C compiler')
class KvmExecutionMockedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        cls.executable = directory / 'mock-kvm-selftest'
        harness = directory / 'harness.c'
        harness.write_text(HARNESS.replace('PRODUCTION_SOURCE', str(SOURCE)), encoding='utf-8')
        # Production is compile-checked, never executed.
        subprocess.run(['cc', *STRICT_FLAGS, str(SOURCE), '-o', str(directory / 'production')], check=True, capture_output=True, text=True, timeout=30)
        subprocess.run(['cc', *STRICT_FLAGS, str(harness), '-o', str(cls.executable)], check=True, capture_output=True, text=True, timeout=30)

    def run_mock(self, scenario='success', failure='none'):
        completed = subprocess.run([str(self.executable), scenario, failure], capture_output=True, text=True, timeout=5)
        self.assertIn(completed.returncode, (0, 1), completed.stderr)
        report = json.loads(completed.stdout)
        trace = json.loads(completed.stderr)
        self.assertEqual(report['windows_client_acceptance'], 'NOT_RUN')
        self.assertTrue(report['diagnostic_only'])
        self.assertFalse(report['os_image_used'])
        self.assertLessEqual(report['kvm_run_calls'], 2)
        self.assertNotIn('/private', completed.stdout)
        self.assertEqual(trace['live_fds'], 0)
        if not failure.startswith(('unmap_', 'signal_restore', 'timer_disarm')):
            self.assertEqual(trace['live_maps'], 0)
            self.assertEqual(trace['signal_active'], 0)
            self.assertEqual(trace['timer_active'], 0)
        return completed.returncode, report, trace

    def test_success_requires_expected_out_then_halt_and_complete_cleanup(self):
        code, report, trace = self.run_mock()
        self.assertEqual(code, 0)
        self.assertEqual(report['status'], 'expected_io_and_halt_observed')
        self.assertTrue(report['vm_created'])
        self.assertTrue(report['execution_attempted'])
        self.assertTrue(report['payload_observed'])
        self.assertTrue(report['halt_observed'])
        self.assertTrue(report['cleanup_complete'])
        self.assertEqual(report['kvm_run_calls'], 2)
        self.assertTrue(trace['trace'].endswith('timer_disarm,unmap_run,close_vcpu,close_vm,unmap_memory,close_kvm,signal_restore,'))

    def test_no_or_arbitrary_arguments_never_touch_host(self):
        for scenario in ('no_arguments', 'extra_arguments', 'arbitrary_payload'):
            with self.subTest(scenario=scenario):
                code, report, trace = self.run_mock(scenario)
                self.assertEqual(code, 1)
                self.assertEqual(report['status'], 'invalid_arguments')
                self.assertEqual(trace['calls'], 0)

    def test_missing_denied_or_symlink_device_are_sanitized(self):
        for scenario, number in (('device_missing', 2), ('device_denied', 13), ('device_symlink', 40)):
            with self.subTest(scenario=scenario):
                code, report, trace = self.run_mock(scenario)
                self.assertEqual(code, 1)
                self.assertEqual(report['stage'], 'open_device')
                self.assertEqual(report['errno'], number)
                self.assertFalse(report['vm_created'])
                self.assertNotIn('create_vm', trace['trace'])

    def test_preflight_rejections_never_create_vm(self):
        for scenario, status in (
            ('page_size_wrong', 'unsupported_page_size'),
            ('device_regular', 'unexpected_device'),
            ('device_wrong_id', 'unexpected_device'),
            ('api_wrong', 'unsupported_api_version'),
            ('memory_unsupported', 'user_memory_unavailable'),
            ('map_size_small', 'unsupported_run_mapping_size'),
            ('map_size_large', 'unsupported_run_mapping_size'),
            ('map_size_unaligned', 'unsupported_run_mapping_size'),
        ):
            with self.subTest(scenario=scenario):
                code, report, trace = self.run_mock(scenario)
                self.assertEqual(code, 1)
                self.assertEqual(report['status'], status)
                self.assertNotIn('create_vm', trace['trace'])

    def test_every_setup_and_run_failure_closes_all_acquired_resources(self):
        for failure in (
            'signal_install',
            'timer_arm',
            'page_size',
            'open_device',
            'device_identity',
            'api_version',
            'memory_capability',
            'run_mapping_size',
            'create_vm',
            'map_memory',
            'register_memory',
            'create_vcpu',
            'map_run',
            'get_sregs',
            'set_sregs',
            'set_regs',
            'run_first',
            'run_second',
        ):
            with self.subTest(failure=failure):
                code, report, trace = self.run_mock(failure=failure)
                self.assertEqual(code, 1)
                self.assertNotEqual(report['status'], 'expected_io_and_halt_observed')
                self.assertTrue(report['cleanup_complete'])
                self.assertEqual(report['errno'], 5)
                self.assertEqual(trace['trace'].split(',').count(failure), 1)

    def test_malformed_io_metadata_and_marker_never_resume_guest(self):
        for scenario in (
            'io_in',
            'io_size',
            'io_port',
            'io_count',
            'io_header_offset',
            'io_end_offset',
            'io_overflow_offset',
            'marker_wrong',
            'first_exit_wrong',
        ):
            with self.subTest(scenario=scenario):
                code, report, trace = self.run_mock(scenario)
                self.assertEqual(code, 1)
                self.assertIn(report['status'], ('invalid_io_exit', 'unexpected_marker', 'unexpected_exit'))
                self.assertFalse(report['payload_observed'])
                self.assertFalse(report['halt_observed'])
                self.assertEqual(report['kvm_run_calls'], 1)
                self.assertNotIn('run_second', trace['trace'])

    def test_io_alone_is_insufficient_if_second_exit_is_not_halt(self):
        code, report, _ = self.run_mock('halt_wrong')
        self.assertEqual(code, 1)
        self.assertEqual(report['status'], 'unexpected_exit')
        self.assertTrue(report['payload_observed'])
        self.assertFalse(report['halt_observed'])
        self.assertEqual(report['kvm_run_calls'], 2)

    def test_timeout_fails_without_retry_and_cleans_up(self):
        for scenario in ('timeout_first', 'timeout_second', 'timeout_after_exit'):
            with self.subTest(scenario=scenario):
                code, report, _ = self.run_mock(scenario)
                self.assertEqual(code, 1)
                self.assertEqual(report['status'], 'timeout')
                self.assertFalse(report['halt_observed'])
                self.assertTrue(report['cleanup_complete'])

    def test_cleanup_failures_invalidate_success_and_remaining_cleanup_is_attempted(self):
        expected = ('timer_disarm', 'unmap_run', 'close_vcpu', 'close_vm', 'unmap_memory', 'close_kvm', 'signal_restore')
        for failure in expected:
            with self.subTest(failure=failure):
                code, report, trace = self.run_mock(failure=failure)
                self.assertEqual(code, 1)
                self.assertEqual(report['status'], 'cleanup_failed')
                self.assertFalse(report['cleanup_complete'])
                self.assertEqual(report['cleanup_errno'], 5)
                for operation in expected:
                    self.assertEqual(trace['trace'].split(',').count(operation), 1)


class KvmExecutionWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (ROOT / '.github/workflows/quantlab.yml').read_text(encoding='utf-8')
        match = re.search(r'(?ms)^  guest-execution-diagnostic:\n(.*?)(?=^  [a-z][a-z0-9_-]*:\n|\Z)', cls.workflow)
        if match is None:
            raise AssertionError('Missing separate infrastructure diagnostic job')
        cls.job = match.group(0)
        script = re.search(
            r'(?ms)      - name: Execute fixed five-byte KVM diagnostic[^\n]*\n'
            r'        shell: bash\n        run: \|\n(.*?)^      - name: Preserve KVM',
            cls.job,
        )
        if script is None:
            raise AssertionError('Missing bounded diagnostic command step')
        cls.script = textwrap.dedent(script.group(1))

    def test_job_is_explicit_infrastructure_only_with_no_windows_consent(self):
        self.assertIn('name: KVM execution diagnostic (infrastructure only)', self.job)
        self.assertIn('runs-on: ubuntu-latest', self.job)
        self.assertIn('timeout-minutes: 3', self.job)
        self.assertIn('No Windows media or terms are used or accepted', self.job)
        self.assertIn('client acceptance is NOT_RUN', self.job)
        self.assertIn('actions/checkout@11d5960a326750d5838078e36cf38b85af677262', self.job)
        self.assertIn('persist-credentials: false', self.job)

    def test_only_system_tools_mocked_tests_and_strict_unprivileged_compile(self):
        self.assertIn('run: /usr/bin/python3 -m unittest discover -s tests -p test_kvm_x86_execution.py -v', self.job)
        expected = '/usr/bin/cc -std=c11 -O2 -Wall -Wextra -Werror -Wpedantic tools/selftest_kvm_x86_execution.c -o build/selftest-kvm-x86'
        self.assertIn(expected, self.job)
        self.assertEqual(self.job.count('sudo '), 1)
        for prohibited in (
            'setup-python',
            'pip install',
            'apt-get',
            'curl ',
            'wget ',
            'chmod',
            'chown',
            'usermod',
            'modprobe',
            'sysctl',
            'setfacl',
            'sudo cc',
            'sudo /usr/bin/cc',
            'sudo sh',
            'sudo bash',
            'sudo tee',
        ):
            self.assertNotIn(prohibited, self.job)

    def test_execution_is_fixed_bounded_and_preserves_separate_reports(self):
        expected = (
            'if timeout --kill-after=2s 10s sudo -n ./build/selftest-kvm-x86 '
            '--run-kvm-self-test > dist/validation/kvm-execution-self-test.json '
            '2>/dev/null; then'
        )
        self.assertIn(expected, self.script)
        self.assertEqual(self.script.count('> dist/validation/kvm-execution-self-test.json'), 1)
        self.assertEqual(self.script.count('> dist/validation/kvm-execution-command.json'), 1)
        self.assertIn('command_status=$?', self.script)
        self.assertIn('124) outcome=command_timed_out', self.script)
        self.assertIn('137) outcome=command_killed', self.script)
        self.assertIn('"guest_execution_state":"UNKNOWN"', self.script)
        self.assertNotIn('"guest_started":false', self.script)
        self.assertNotIn('"execution_attempted":false', self.script)
        self.assertNotIn('eval ', self.script)
        self.assertNotIn('|| true', self.script)

    def test_both_reports_upload_even_if_diagnostic_is_unavailable(self):
        upload = self.job.split('      - name: Preserve KVM', 1)[1]
        self.assertIn('if: always()', upload)
        self.assertIn('actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02', upload)
        self.assertIn('name: kvm-execution-infrastructure-diagnostic', upload)
        self.assertIn('path: |\n            dist/validation/kvm-execution-self-test.json\n            dist/validation/kvm-execution-command.json', upload)
        self.assertIn('retention-days: 7', upload)

    def test_quality_remains_read_only_and_product_jobs_do_not_depend_on_diagnostic(self):
        other_jobs = self.workflow.replace(self.job, '')
        quality = re.search(r'(?ms)^  quality:\n(.*?)(?=^  [a-z][a-z0-9_-]*:\n|\Z)', other_jobs).group(0)
        self.assertEqual(quality.count('sudo '), 1)
        self.assertIn('--query-kvm-api', quality)
        self.assertNotIn('--run-kvm-self-test', quality)
        self.assertNotIn('guest-execution-diagnostic', other_jobs)
        self.assertNotIn('continue-on-error', self.workflow)
        self.assertIn('run: python tools/run_test_group.py --group ${{ matrix.group }}', other_jobs)
        ui_producers = re.search(r'(?ms)^  ui-tests:\n(.*?)(?=^  [a-z][a-z0-9_-]*:\n|\Z)', other_jobs).group(0)
        ui_aggregate = re.search(r'(?ms)^  ui:\n(.*?)(?=^  [a-z][a-z0-9_-]*:\n|\Z)', other_jobs).group(0)
        self.assertIn('group: [core, research]', ui_producers)
        self.assertIn('timeout-minutes: 15', ui_producers)
        self.assertIn('run: python tools/ui_test_gate.py --group ${{ matrix.group }} --manifest dist/validation/ui-test-inventory.json', ui_producers)
        self.assertIn('needs: [changes, ui-tests]', ui_aggregate)
        self.assertIn('run: python tools/ui_test_gate.py --reports dist/validation/ui-groups --manifest dist/validation/ui-coverage.json', ui_aggregate)
        self.assertIn('- run: python tools/quality_gate.py --history', quality)

    @unittest.skipUnless(NATIVE_TESTS_SUPPORTED and shutil.which('bash'), 'Hosted Linux shell contract requires bash')
    def test_mocked_wrapper_preserves_complete_partial_and_empty_stdout(self):
        # A shell function replaces timeout itself: sudo and the production
        # executable are only arguments to the stub and are never executed.
        for code, diagnostic, outcome in (
            (0, '{"status":"expected_io_and_halt_observed"}\n', 'command_completed'),
            (1, '{"execution_attempted":true,"status":"syscall_failed"}\n', 'command_failed'),
            (124, '{"payload_observed":true', 'command_timed_out'),
            (137, '', 'command_killed'),
            (126, '', 'command_failed'),
        ):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'dist/validation').mkdir(parents=True)
                payload = root / 'mock-stdout'
                payload.write_text(diagnostic, encoding='utf-8')
                stub = (
                    'timeout() {\n'
                    '  test "$*" = "--kill-after=2s 10s sudo -n ./build/selftest-kvm-x86 --run-kvm-self-test" || return 99\n'
                    '  cat mock-stdout\n'
                    f'  return {code}\n'
                    '}\n'
                )
                completed = subprocess.run(
                    [shutil.which('bash'), '-euo', 'pipefail', '-c', stub + self.script], cwd=root, capture_output=True, text=True, timeout=5
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual((root / 'dist/validation/kvm-execution-self-test.json').read_text(), diagnostic)
                report = json.loads((root / 'dist/validation/kvm-execution-command.json').read_text())
                self.assertEqual(
                    report,
                    {
                        'schema_version': 1,
                        'diagnostic_only': True,
                        'windows_client_acceptance': 'NOT_RUN',
                        'status': outcome,
                        'command_exit_code': code,
                        'guest_execution_state': 'UNKNOWN',
                        'diagnostic_report': 'kvm-execution-self-test.json',
                    },
                )


if __name__ == '__main__':
    unittest.main()
