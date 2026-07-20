# Ygo Top Monitor Design

## Summary

`ygo` will gain an optional out-of-process monitor inspired by `htop`. A Python
process using `ygo.Pool` publishes aggregate task state to local shared memory,
while a separate `ygo top` command discovers those processes and renders an
interactive terminal dashboard.

The monitor is observational. Failure to create, update, discover, or render
telemetry must never change task execution or results.

## Goals

- Keep application logs separate from the full monitoring interface.
- Update only changed table cells instead of rebuilding the entire screen.
- Discover already-running local `ygo` processes without requiring a launcher.
- Preserve `Pool(show_progress=True)` as the default.
- Monitor processes, pools, and task groups without recording every individual
  job.
- Work on the repository's supported Linux, macOS, and Windows environments.

Durable task history, distributed monitoring, remote control, and changes to
`Pool` result or exception semantics are outside the first release.

## User Interface

The package will expose a `ygo` console command:

```text
ygo top                  interactive dashboard for all live local tasks
ygo ps                   one-time list of live local tasks
ygo show <pool-id>       details for one live pool
ygo errors <pool-id>     current failure summaries for one live pool
ygo run -- <command>     run a command that can be discovered by ygo top
```

`ygo top` uses an alternate terminal screen and a Textual `DataTable`. Its main
view contains stable rows keyed by `(process_id, pool_id, group_id)`:

```text
PID    STATUS   PROGRESS   RATE     FAIL  ELAPSED  GROUP       COMMAND
18432  running  820/1200   18.2/s      2  00:45    quote       python sync.py
18432  running  310/800     6.4/s      0  00:48    financial   python sync.py
```

Rows are divided into active, problem, and recently completed sections. Recent
means completed pools that are still owned by a live process; no persistent
history database is introduced. The first version supports:

- `q`: quit;
- `r`: force discovery and refresh;
- `e`: show the selected pool's error summaries;
- `l`: show its log path when one was registered.

Individual jobs are represented only by counters. Task lists, tracebacks, and
log contents are not copied into shared memory.

## Incremental Rendering

Rich `Live` panels will not be used for `ygo top`. Textual widgets remain
mounted for the lifetime of the application. The monitor keeps its previous
snapshot and applies only structural or cell-level differences:

- add a row for a newly discovered group;
- remove a row after its owning process disappears;
- call `DataTable.update_cell()` only for changed fields;
- move rows only when a group changes section or the user changes sorting.

The shared-memory generation is checked before decoding a payload. If it has
not changed, no data widgets are refreshed. Telemetry is sampled every
100–200 ms, while elapsed time and derived rates are rendered at most twice per
second. Animated spinners are excluded because they make rows permanently
dirty.

## Runtime Discovery

Each producer creates one registry entry in the platform-appropriate private
runtime directory. Registry entries are small JSON files written by atomic
replacement and contain:

- process ID and process start identity;
- schema and package versions;
- shared-memory name and capacity;
- command, working directory, and optional log path.

The runtime directory must be private to the current user. Registry entries do
not contain task arguments, environment variables, or credentials.

`ygo top` scans the directory on startup and once per second thereafter. It
uses `psutil.Process(pid).create_time()` as the process start identity to avoid
attaching to a reused PID. A dead process is removed from the view. Stale
registry files may be deleted by the monitor only after that validation.

`ygo run` is a convenience launcher, not a required supervisor. Directly
executed Python programs using `ygo.Pool` remain discoverable.

## Shared-Memory Protocol

One application parent process is the sole writer for its shared-memory
segment. Joblib workers never write telemetry directly. The segment contains a
small binary header and two fixed-capacity JSON slots:

```text
Header
  magic, schema_version, generation, active_slot,
  payload_length, checksum, heartbeat_monotonic_ns
Slot A
Slot B
```

The writer marks a new generation as in progress, serializes into the inactive
slot, then publishes an even completed generation and switches the active
slot. A reader:

1. reads the header;
2. rejects an in-progress generation;
3. reads the active payload;
4. reads the header again;
5. accepts the snapshot only when both headers agree and the checksum matches.

The JSON snapshot contains process metadata and aggregate pool/group state:

```json
{
  "process": {"pid": 18432, "command": "python sync.py"},
  "pools": [{
    "id": "daily-sync",
    "backend": "threading",
    "n_jobs": 8,
    "groups": [{
      "id": "quote",
      "status": "running",
      "total": 1200,
      "completed": 820,
      "failed": 2,
      "last_error": "HTTP timeout"
    }]
  }]
}
```

Updates are coalesced to at most 10 Hz. A heartbeat is published once per
second even when counters do not change. The default capacity is 1 MiB per
process. If a payload exceeds capacity, optional error details are truncated
and `telemetry_overflow=true` is published; execution continues normally.

JSON is used instead of pickle to avoid arbitrary-code deserialization and
Python object-version coupling.

## Python API and Inline Progress

The existing default remains compatible:

```python
Pool(n_jobs=8, show_progress=True, monitor=True)
```

`monitor` is a new keyword and defaults to `True`. `YGO_MONITOR=0` or
`monitor=False` disables registry and shared-memory publication.

`show_progress=True` continues to print progress in the application terminal,
but the existing multi-row display is replaced by one compact aggregate line:

```text
ygo  820/1200  68.3%  18.2/s  active=8  failed=2  elapsed=00:45
```

`show_progress=False` affects only inline output; it does not disable
telemetry. Ygo-owned logs use the same Rich console as the compact progress
line. Arbitrary third-party writes to stdout cannot be coordinated reliably,
which is why `ygo top` in a separate terminal is the clean monitoring path.

## Lifecycle and Failure Handling

Telemetry is initialized lazily when the first monitored pool is created.
Normal interpreter shutdown closes the segment, removes the registry entry,
and unlinks shared memory. The monitor recognizes abnormal exits through PID,
start identity, and heartbeat.

All telemetry operations are guarded by a no-throw boundary. Initialization
failure disables monitoring for that process and emits at most one warning.
Subsequent serialization or publication failures are rate-limited and do not
escape into `Pool.submit()` or `Pool.do()`.

Schema versions are explicit. A monitor skips incompatible producers and shows
one diagnostic row rather than attempting best-effort deserialization.

## Component Boundaries

- `telemetry/model.py`: typed process, pool, and group snapshots.
- `telemetry/shared.py`: double-buffer encoding, consistency checks, and
  cleanup.
- `telemetry/registry.py`: platform runtime directory and process discovery.
- `telemetry/publisher.py`: coalescing, heartbeat, and no-throw integration.
- `cli.py`: command parsing for `top`, `ps`, `show`, `errors`, and `run`.
- `tui.py`: Textual application and snapshot-to-cell diffing.
- `progress.py`: compact inline renderer only; it does not know about Textual.

`Pool` reports lifecycle events to the publisher through a small internal
interface. It never reaches into TUI or shared-memory implementation details.

Textual and psutil become explicit runtime dependencies: Textual owns the
incremental terminal UI, and psutil provides the same cross-platform process
identity and liveness checks on every supported operating system.

## Verification

Unit tests cover model serialization, alternating slots, torn-read rejection,
checksum failure, overflow truncation, schema mismatch, registry cleanup, PID
reuse, update coalescing, and telemetry failure isolation.

Integration tests launch a producer subprocess and verify that another process
can discover its pools and observe progress transitions. Textual tests verify
that an unchanged generation causes no widget update and that one changed
counter updates only its target cell.

Existing `Pool` tests must run with monitoring both enabled and disabled.
Cross-platform CI covers runtime paths and shared-memory cleanup. A manual
terminal check confirms alternate-screen restoration, resizing, keyboard
navigation, clean application logs, and stable rendering during rapid task
completion.
