# ygo top Resource Tracker Fix Design

## Problem

On POSIX with Python 3.11 or 3.12, `ygo top` first opens shared memory after
Textual has redirected standard streams. Starting `multiprocessing`'s resource
tracker at that point can fail with `ValueError: bad value(s) in fds_to_keep`.
The monitor treats the open failure as a missing segment, so the dashboard
shows zero groups while `ygo ps` still works.

## Design

Add `prepare_reader_process()` to `ygo.telemetry.shared`. On POSIX with Python
older than 3.13 it starts the resource tracker before Textual takes over the
terminal. It is a no-op on Windows and Python 3.13+, where readers use
`SharedMemory(track=False)`.

The `top` CLI path calls this helper immediately before constructing and
running `YgoTopApp`. Other commands and the shared-memory wire format remain
unchanged.

## Verification

Tests will verify platform/version gating and that preparation happens before
the Textual application runs. The original real-TTY reproduction must show a
live group in `ygo top`, followed by the complete test, lint, and build suite.

