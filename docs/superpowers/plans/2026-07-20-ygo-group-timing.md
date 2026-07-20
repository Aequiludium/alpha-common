# ygo Group Timing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task by task.

**Goal:** Start timing a group only when work actually executes and freeze timing metrics
after the group finishes.

**Architecture:** Capture start/finish monotonic timestamps inside `run_job`, pass them
through the existing completion callback, store lifecycle timestamps in telemetry state,
and render state-aware metrics in the Textual table.

**Tech Stack:** Python 3.11+, joblib, Textual, pytest, Ruff, uv.

---

## Task 1: Add regression tests

Extend publisher, model, pool-monitoring, and TUI tests for pending groups, timestamp
forwarding, optional finish-time serialization, and frozen terminal metrics. Run the focused
tests and confirm they fail for the expected missing behavior.

## Task 2: Implement lifecycle timing

Update `run_job` and callback types to forward start/finish timestamps. Change publisher
groups to begin pending, capture the earliest start and latest finish, and expose the optional
finish timestamp in snapshots.

## Task 3: Render state-aware metrics

Show placeholders for pending groups, live values for running groups, and finish-bounded
values for terminal groups.

## Task 4: Verify and release

Run focused and full tests, Ruff checks, and `uv build`. Bump the package to `0.1.14`, push
the verified commit directly to `main`, create the GitHub release, and confirm PyPI publishing.
