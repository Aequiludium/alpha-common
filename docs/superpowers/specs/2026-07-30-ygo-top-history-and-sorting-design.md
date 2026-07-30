# ygo Top History and Sorting Design

## Summary

Upgrade `ygo top` with an actual group start-time column, interactive column
sorting, newest-first default ordering, and persistent history for the latest
100 completed task groups. A task remains the existing aggregate row identified
by `(process start identity, pool ID, group ID, group registration time)`;
individual jobs are not stored.

## User Interface

Add a `STARTED` column formatted in the machine's local timezone as
`YYYY-MM-DD HH:MM:SS`. A group remains `--` while pending because the existing
worker-result channel does not reveal its actual start until the first result
returns. An internal registration timestamp still places a new pending group at
the top.

The default order is newest first. Selecting a column header sorts by that
field; selecting the same header again toggles ascending and descending order.
Sorting uses typed values rather than rendered text:

- `PID`, `FAIL`, and `ELAPSED` use numeric values;
- `PROGRESS` uses the completion ratio;
- `RATE` uses the numeric rate;
- `STARTED` uses the actual start timestamp, falling back to registration time
  only for ordering pending groups;
- `STATUS`, `GROUP`, and `COMMAND` use case-insensitive text.

The table remains mounted. Snapshot reconciliation still updates individual
cells, and Textual's in-place `DataTable.sort()` handles row movement.

## Time Model

Worker execution records both monotonic and Unix timestamps. Monotonic values
continue to drive elapsed time and rate calculations. Unix timestamps provide
portable wall-clock start and finish values for display and persisted history.

The telemetry JSON schema stays backward compatible: new timestamp fields are
optional when decoding old snapshots. Pending groups have a registration
timestamp but no actual start timestamp.

## Persistent History

Create a small history store under the platform state directory, normally
`~/.local/state/ygo/history/` on Linux. Each completed task group is stored as a
separate JSON record written through atomic replacement. Unique files avoid a
shared writable index and cross-process locking.

The record contains the stable task key, PID and process start identity, pool and
group IDs, command, status, counters, error, registration/start/finish
timestamps, and frozen elapsed/rate values. It contains no arguments,
environment variables, or log contents beyond metadata already exposed by
telemetry. Process start identity prevents PID reuse collisions, while group
registration time distinguishes repeated executions of the same `Pool`.
The publisher advances equal or backward registration readings minimally so
each execution keeps a distinct identity and newest-first order.

On terminal transition, the producer writes the completed group immediately.
Normal process cleanup still removes the runtime registry and shared memory but
does not remove history. Malformed records are ignored. Storage failures remain
inside the telemetry no-throw boundary and cannot affect task results.

The store retains the latest 100 completed groups globally, ordered by finish
time. Appending and reading both prune excess records, making occasional
concurrent cleanup races harmless. Files and directories use the same private
permissions as the runtime registry.

## Merging Live and Historical Rows

`ygo top` displays every live group plus up to 100 completed historical groups.
Live rows win when the same stable key is present in both sources, so a group
that has completed but whose process remains alive appears only once. Historical
rows remain after the producer exits.

History is scoped to `ygo top`. The existing `ygo ps`, `ygo show`, and
`ygo errors` commands continue to mean live state only.

An abruptly terminated group that never reached a terminal transition is not
written to history. A completed group already persisted remains visible even if
the producer later exits abnormally.

## Component Boundaries

- `telemetry/model.py`: optional wall-clock timestamps and compatible decoding.
- `telemetry/history.py`: atomic per-group JSON persistence, read, deduplicate,
  and prune operations.
- `telemetry/publisher.py`: registration timestamps and terminal history writes.
- `_pool.py`: worker monotonic and Unix timestamp capture.
- `monitor.py`: combine live snapshots with persistent completed records.
- `tui.py`: typed row values, start-time rendering, default order, and header
  sort state.

## Verification

Tests cover old-snapshot compatibility, actual start-time propagation, atomic
history round trips, retention at 100 records, malformed files, live/history
deduplication, persistence after registry cleanup, local-time formatting,
newest-first ordering, typed sorting, direction toggling, and incremental cell
updates. The full pytest suite, both Ruff checks, a package build, and a manual
terminal smoke test are required before release.
