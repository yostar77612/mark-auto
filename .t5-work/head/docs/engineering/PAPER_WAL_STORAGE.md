# Durable replay storage candidate

## Scope and predeclared acceptance

The shipping desktop replay explicitly selects `wal_full`. Direct callers retain
`rollback_full` compatibility. Both require patched SQLite >= 3.51.3 and a local
filesystem before opening a replay ledger, because a legacy caller can encounter
an already migrated WAL database. The broker remains DELETE/FULL. No workload,
timeout, transaction boundary, replay identity, broker verification, or existing
test was changed.

Acceptance requires the original 960-bar / 30-second native Windows test and
full native suites on the exact integrated build, in addition to the regression
coverage below. Linux timing is not Windows release evidence. Runtime provenance
and old-version workspace refusal are separate integration prerequisites; this
module alone does not make an old application safe to run on migrated state.

## Design

A local handle belongs to one `step` invocation. The existing replay mutex still
excludes a second step. `_db(connection)` commits or rolls back at each original
boundary; there is no enclosing transaction, implicit instance connection cache,
or cached account/control state. Every bar reads the cursor and broker snapshot.
Public snapshot/start/stop use independent connections, including on the same
object in another thread. Broker calls occur after the plan commit.

Each connection sets and verifies FULL synchronization. WAL connections verify
actual WAL mode after initialization. Automatic checkpoints remain enabled at
1000 pages. No manual truncation, sidecar deletion, or busy-checkpoint retry is
introduced. Closing a step handle permits SQLite's normal last-close checkpoint;
a concurrent reader may delay checkpointing without invalidating durable commits.
A close/checkpoint is not used as the per-bar durability boundary.

Migration first validates the original binding and commits the existing schema,
then asks SQLite to switch to WAL and verifies success. Existing hot rollback
journals are recovered through SQLite before conversion. Binding, cursor, active
flag, pending plan, and stable order IDs are preserved. Failures propagate; there
is no performance-mode fallback. Existing WAL databases are not converted back
by legacy callers.

The production module never raw-reads a database header: closing a separately
opened file descriptor can invalidate process-wide POSIX advisory locks.

## Backups, failures, and tests

The existing quiescent backup copies all state files, including DB/WAL/SHM,
without opening SQLite first. New crash tests assert nonempty WAL and SHM files
actually exist, verify archive and restored bytes before opening SQLite, and
resume at the identical absolute path exactly once. Additional tests force an
uncommitted WAL tail to spill beyond the committed WAL size, kill the process,
and verify it is discarded after restore. The original hot-journal test remains
unchanged, with extra coverage for recovery followed by WAL conversion.

Coverage also includes the original replay behavioral corpus using real WAL,
per-bar COMMIT counts/FULL/no-open-transaction witnesses, failed commit cleanup,
wrong FULL readback, external mode changes, unsafe-runtime refusal before opening,
Windows mapped-network drive rejection, Linux network-mount rejection, and both
same-object and separate-object concurrent control access.

Local Linux mounts are classified through the longest mount in mountinfo.
An overlay filesystem is accepted for the container test environment; this does
not prove that an arbitrary overlay's underlying storage is local or durable.
Production Windows uses GetDriveTypeW and rejects UNC/unavailable/network drives.
This test evidence does not certify power-loss behavior of the host hardware.

## Alternatives and references

Connection reuse alone cannot address the observed >30 seconds spent in 960 FULL
cursor commits. DELETE/TRUNCATE/PERSIST calibration showed no consistent clear
benefit. Batching commits or NORMAL/OFF synchronization would weaken guarantees
and is excluded. A custom append log would require a larger new recovery protocol.

SQLite documents WAL/FULL as ACID, with a WAL sync for each committed transaction:
https://www.sqlite.org/pragma.html#pragma_synchronous

WAL uses a persistent sidecar, requires same-host shared memory, and has a
WAL-reset race in older runtimes. This candidate requires 3.51.3 or newer rather
than selecting individual older backports:
https://www.sqlite.org/wal.html

The raw-file-descriptor locking hazard:
https://www.sqlite.org/howtocorrupt.html#_posix_advisory_locks_canceled_by_a_separate_thread_doing_close_
