# ygo Group Timing Design

## Problem

`TelemetryPublisher.register_pool()` currently marks every group as running with the
same timestamp. The monitor therefore starts `ELAPSED` before a group executes and
continues recalculating `ELAPSED` and `RATE` after the group reaches a terminal state.

## Lifecycle

Groups use the lifecycle `pending -> running -> done/error`.

- Registration creates `pending` groups.
- Each worker records monotonic start and finish timestamps around the actual job call.
- The first completed job transitions its group to `running` and supplies the real start.
- The final result transitions the group to `done` or `error` and stores the finish time.

With unordered result delivery, a long-running first job remains `pending` until its first
result arrives. This is intentional: the existing result channel is reused and no extra IPC
or backend-specific hooks are introduced.

## Display Semantics

- `pending`: show `--` for `RATE` and `ELAPSED`.
- `running`: calculate elapsed time from the earliest observed job start to the current time.
- `done/error`: calculate elapsed time from the earliest start to the final finish and keep
  both elapsed time and rate fixed.

The snapshot schema remains version 1. `finished_monotonic` is optional so new readers can
consume old snapshots and old readers can ignore the added JSON field.

## Verification

Regression tests cover pending registration, timestamp propagation, terminal freezing,
JSON compatibility, and pool callback forwarding. The full test suite, Ruff checks, and
package build must pass before release.
