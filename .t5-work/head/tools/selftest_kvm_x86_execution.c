/* A bounded, explicitly opt-in KVM execution diagnostic, separate from the app.
 *
 * Compile only, without privilege:
 *   cc -std=c11 -O2 -Wall -Wextra -Werror -Wpedantic \
 *     tools/selftest_kvm_x86_execution.c -o build/selftest-kvm-x86
 * If separately authorized to run on an ephemeral Linux x86_64 CI host, the
 * caller MUST enforce an external process timeout. The internal alarm cannot
 * guarantee interruption of every kernel operation. Fixed invocation only:
 *   timeout --kill-after=2s 10s sudo -n ./build/selftest-kvm-x86 \
 *     --run-kvm-self-test > dist/validation/kvm-execution-self-test.json
 * Stdout redirection belongs to the unprivileged caller. No arbitrary input,
 * output path, guest binary, device, resource size or ioctl is accepted.
 *
 * Uses the installed Linux UAPI declarations, not copied structure layouts:
 * https://www.kernel.org/doc/html/latest/virt/kvm/api.html
 * https://github.com/torvalds/linux/blob/master/include/uapi/linux/kvm.h
 * https://github.com/torvalds/linux/blob/master/arch/x86/include/uapi/asm/kvm.h
 * Device identity: include/uapi/linux/major.h and include/linux/miscdevice.h.
 *
 * Only five self-authored real-mode bytes run, in a transient single-vCPU VM.
 * No OS, firmware, disk, network, IRQ controller, host setting, permissions,
 * module, Windows media or legal agreement is installed or changed. A result
 * proves this tiny execution only, not x64 Windows, UEFI, TPM or Secure Boot.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <string.h>

struct evidence {
    const char *status;
    const char *stage;
    int error_number;
    int cleanup_error;
    int vm_created;
    int execution_attempted;
    int payload_observed;
    int halt_observed;
    unsigned int run_calls;
};

static int emit_report(const struct evidence *result)
{
    const int success = strcmp(result->status, "expected_io_and_halt_observed") == 0
                        && result->cleanup_error == 0;
    /* All strings are fixed source literals; no exception text or host identity. */
    const int written = printf("{\"schema_version\":1,\"diagnostic_only\":true,"
           "\"windows_client_acceptance\":\"NOT_RUN\",\"os_image_used\":false,"
           "\"status\":\"%s\",\"stage\":\"%s\",\"errno\":%d,"
           "\"vm_created\":%s,\"execution_attempted\":%s,"
           "\"payload_observed\":%s,\"halt_observed\":%s,\"kvm_run_calls\":%u,"
           "\"cleanup_complete\":%s,\"cleanup_errno\":%d,"
           "\"limits\":\"Five-byte real-mode test only; not Windows or guest OS acceptance.\"}\n",
           result->status, result->stage, result->error_number,
           result->vm_created ? "true" : "false",
           result->execution_attempted ? "true" : "false",
           result->payload_observed ? "true" : "false",
           result->halt_observed ? "true" : "false", result->run_calls,
           result->cleanup_error == 0 ? "true" : "false", result->cleanup_error);
    if (written < 0 || fflush(stdout) == EOF)
        return 1;
    return success ? 0 : 1;
}

#if defined(__linux__) && defined(__x86_64__)
#include <errno.h>
#include <fcntl.h>
#include <linux/kvm.h>
#include <signal.h>
#include <stdint.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/time.h>
#include <unistd.h>

#define GUEST_RAM_BYTES 4096U
#define GUEST_CODE_ADDRESS 0x1000U
#define MAX_RUN_MAPPING_BYTES 65536U
#define DEADLINE_SECONDS 3
#define MARKER_PORT 0xe9U
#define MARKER_BYTE 42U

/* mov al,42; out 0xe9,al; hlt. The OUT is intercepted, never host port I/O. */
static const unsigned char guest_code[] = {0xb0, 0x2a, 0xe6, 0xe9, 0xf4};
static volatile sig_atomic_t deadline_expired;

static void on_alarm(int signal_number)
{
    (void)signal_number;
    deadline_expired = 1;
}

static void note_cleanup_failure(struct evidence *result)
{
    if (result->cleanup_error == 0)
        result->cleanup_error = errno != 0 ? errno : EIO;
}

#define CHECK_CALL(expression, operation) do { \
    result.stage = (operation); \
    if (deadline_expired) { result.status = "timeout"; goto cleanup; } \
    if ((expression) < 0) { \
        result.error_number = errno; \
        if (deadline_expired) result.status = "timeout"; \
        goto cleanup; \
    } \
} while (0)

static int run_self_test(void)
{
    struct evidence result = {.status = "syscall_failed", .stage = "prepare"};
    int kvm_fd = -1, vm_fd = -1, vcpu_fd = -1;
    int signal_installed = 0, timer_armed = 0;
    int api_version = -1, extension = -1, run_mapping_bytes = -1;
    long page_size = -1;
    void *guest_ram = MAP_FAILED;
    struct kvm_run *run = MAP_FAILED;
    struct stat device;
    struct sigaction alarm_action, previous_alarm;
    struct itimerval timer = {.it_value = {.tv_sec = DEADLINE_SECONDS}};
    struct itimerval no_timer = {0};
    struct kvm_userspace_memory_region region = {0};
    struct kvm_sregs sregs;
    struct kvm_regs regs = {0};
    unsigned int index;

    deadline_expired = 0;
    memset(&alarm_action, 0, sizeof(alarm_action));
    alarm_action.sa_handler = on_alarm;
    CHECK_CALL(sigemptyset(&alarm_action.sa_mask), "signal_mask");
    /* No SA_RESTART: an alarm must interrupt KVM_RUN rather than retry it. */
    CHECK_CALL(sigaction(SIGALRM, &alarm_action, &previous_alarm), "signal_handler");
    signal_installed = 1;
    CHECK_CALL(setitimer(ITIMER_REAL, &timer, NULL), "arm_deadline");
    timer_armed = 1;
    CHECK_CALL(page_size = sysconf(_SC_PAGESIZE), "page_size");
    if (page_size != GUEST_RAM_BYTES) {
        result.status = "unsupported_page_size";
        goto cleanup;
    }
    CHECK_CALL(kvm_fd = open("/dev/kvm", O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK),
               "open_device");
    CHECK_CALL(fstat(kvm_fd, &device), "device_identity");
    if (!S_ISCHR(device.st_mode) || major(device.st_rdev) != 10 || minor(device.st_rdev) != 232) {
        result.status = "unexpected_device";
        goto cleanup;
    }
    CHECK_CALL(api_version = ioctl(kvm_fd, KVM_GET_API_VERSION, 0UL), "api_version");
    if (api_version != KVM_API_VERSION) {
        result.status = "unsupported_api_version";
        goto cleanup;
    }
    CHECK_CALL(extension = ioctl(kvm_fd, KVM_CHECK_EXTENSION, (unsigned long)KVM_CAP_USER_MEMORY),
               "user_memory_capability");
    if (extension == 0) {
        result.status = "user_memory_unavailable";
        goto cleanup;
    }
    CHECK_CALL(run_mapping_bytes = ioctl(kvm_fd, KVM_GET_VCPU_MMAP_SIZE, 0UL),
               "run_mapping_size");
    if (run_mapping_bytes < (int)sizeof(struct kvm_run)
            || run_mapping_bytes > (int)MAX_RUN_MAPPING_BYTES
            || run_mapping_bytes % GUEST_RAM_BYTES != 0) {
        result.status = "unsupported_run_mapping_size";
        goto cleanup;
    }
    CHECK_CALL(vm_fd = ioctl(kvm_fd, KVM_CREATE_VM, 0UL), "create_vm");
    result.vm_created = 1;
    result.stage = "map_guest_ram";
    guest_ram = mmap(NULL, GUEST_RAM_BYTES, PROT_READ | PROT_WRITE,
                     MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (guest_ram == MAP_FAILED) { result.error_number = errno; goto cleanup; }
    memcpy(guest_ram, guest_code, sizeof(guest_code));
    region.slot = 0;
    region.guest_phys_addr = GUEST_CODE_ADDRESS;
    region.memory_size = GUEST_RAM_BYTES;
    region.userspace_addr = (uint64_t)(uintptr_t)guest_ram;
    CHECK_CALL(ioctl(vm_fd, KVM_SET_USER_MEMORY_REGION, &region), "register_guest_ram");
    CHECK_CALL(vcpu_fd = ioctl(vm_fd, KVM_CREATE_VCPU, 0UL), "create_vcpu");
    result.stage = "map_run_state";
    run = mmap(NULL, (size_t)run_mapping_bytes, PROT_READ | PROT_WRITE,
               MAP_SHARED, vcpu_fd, 0);
    if (run == MAP_FAILED) { result.error_number = errno; goto cleanup; }
    CHECK_CALL(ioctl(vcpu_fd, KVM_GET_SREGS, &sregs), "get_special_registers");
    sregs.cs.base = 0;
    sregs.cs.selector = 0;
    CHECK_CALL(ioctl(vcpu_fd, KVM_SET_SREGS, &sregs), "set_special_registers");
    regs.rip = GUEST_CODE_ADDRESS;
    regs.rflags = 2;  /* Architectural reserved bit; maskable interrupts disabled. */
    CHECK_CALL(ioctl(vcpu_fd, KVM_SET_REGS, &regs), "set_registers");
    for (index = 0; index < 2; ++index) {
        result.stage = index == 0 ? "run_to_io" : "run_to_halt";
        if (deadline_expired) { result.status = "timeout"; goto cleanup; }
        result.execution_attempted = 1;
        ++result.run_calls;
        if (ioctl(vcpu_fd, KVM_RUN, 0UL) < 0) {
            result.error_number = errno;
            if (deadline_expired) result.status = "timeout";
            goto cleanup;
        }
        if (deadline_expired) { result.status = "timeout"; goto cleanup; }
        if (index == 0) {
            if (run->exit_reason != KVM_EXIT_IO) {
                result.status = "unexpected_exit";
                goto cleanup;
            }
            if (run->io.direction != KVM_EXIT_IO_OUT || run->io.size != 1
                    || run->io.port != MARKER_PORT || run->io.count != 1
                    || run->io.data_offset < sizeof(struct kvm_run)
                    || run->io.data_offset >= (uint64_t)run_mapping_bytes) {
                result.status = "invalid_io_exit";
                goto cleanup;
            }
            if (*((unsigned char *)run + run->io.data_offset) != MARKER_BYTE) {
                result.status = "unexpected_marker";
                goto cleanup;
            }
            result.payload_observed = 1;
            /* KVM documents that re-entry is required to complete port I/O. */
        } else {
            if (run->exit_reason != KVM_EXIT_HLT) {
                result.status = "unexpected_exit";
                goto cleanup;
            }
            result.halt_observed = 1;
        }
    }
    result.status = "expected_io_and_halt_observed";
    result.stage = "complete";

cleanup:
    /* No retries: close may already release an fd even if it reports EINTR. */
    if (timer_armed && setitimer(ITIMER_REAL, &no_timer, NULL) < 0)
        note_cleanup_failure(&result);
    if (run != MAP_FAILED && munmap(run, (size_t)run_mapping_bytes) < 0)
        note_cleanup_failure(&result);
    if (vcpu_fd >= 0 && close(vcpu_fd) < 0)
        note_cleanup_failure(&result);
    if (vm_fd >= 0 && close(vm_fd) < 0)
        note_cleanup_failure(&result);
    /* Release VM references before unmapping its one anonymous memory page. */
    if (guest_ram != MAP_FAILED && munmap(guest_ram, GUEST_RAM_BYTES) < 0)
        note_cleanup_failure(&result);
    if (kvm_fd >= 0 && close(kvm_fd) < 0)
        note_cleanup_failure(&result);
    if (signal_installed && sigaction(SIGALRM, &previous_alarm, NULL) < 0)
        note_cleanup_failure(&result);
    if (result.cleanup_error != 0 && strcmp(result.status, "expected_io_and_halt_observed") == 0)
        result.status = "cleanup_failed";
    return emit_report(&result);
}
#endif

int main(int argc, char **argv)
{
    struct evidence result = {.status = "invalid_arguments", .stage = "arguments"};
    if (argc != 2 || strcmp(argv[1], "--run-kvm-self-test") != 0)
        return emit_report(&result);
#if defined(__linux__) && defined(__x86_64__)
    return run_self_test();
#else
    result.status = "unsupported_platform";
    result.stage = "platform";
    return emit_report(&result);
#endif
}
