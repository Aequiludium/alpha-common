# ygo top Resource Tracker Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ygo top` discover shared-memory tasks on POSIX Python 3.11 and
3.12 after Textual takes control of the terminal.

**Architecture:** Centralize reader-process preparation in
`ygo.telemetry.shared`, gated by platform and Python version. Invoke it before
the Textual application starts; do not change shared-memory data or lifecycle.

**Tech Stack:** Python 3.11+, multiprocessing shared memory, Textual, pytest,
Ruff, uv.

---

### Task 1: Lock down tracker startup

**Files:**
- Modify: `tests/ygo/test_shared.py`
- Modify: `tests/ygo/test_cli.py`
- Modify: `src/ygo/telemetry/shared.py`
- Modify: `src/ygo/cli.py`

- [ ] **Step 1: Write failing tests**

Add tests that monkeypatch platform/version state and assert
`prepare_reader_process()` starts the tracker only for legacy POSIX readers.
Add a CLI test recording that preparation occurs before `YgoTopApp.run()`.

- [ ] **Step 2: Verify the tests fail**

Run:

```bash
uv run pytest tests/ygo/test_shared.py tests/ygo/test_cli.py -q
```

Expected: collection fails because `prepare_reader_process` does not exist.

- [ ] **Step 3: Implement the minimal fix**

Add:

```python
def prepare_reader_process() -> None:
    if os.name != "nt" and sys.version_info < (3, 13):
        resource_tracker.ensure_running()
```

Call it in the `top` CLI branch immediately before `YgoTopApp().run()`.

- [ ] **Step 4: Verify focused tests**

Run:

```bash
uv run pytest tests/ygo/test_shared.py tests/ygo/test_cli.py -q
```

Expected: all focused tests pass.

### Task 2: Verify the original symptom and prepare release

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Run the real-TTY reproduction**

Start a monitored blocking pool, run `ygo top` in a pseudo-terminal, and assert
the captured incremental output contains `1 groups` and the group name.

- [ ] **Step 2: Bump the package version**

Change the project version from `0.1.12` to `0.1.13`, then run:

```bash
uv lock
```

- [ ] **Step 3: Run complete verification**

```bash
uv sync
uv run ruff format --check .
uv run ruff check .
uv run pytest tests/
uv build
```

Expected: Ruff, all tests, and package build pass; wheel metadata reports
`0.1.13`.

- [ ] **Step 4: Commit and publish directly**

Commit the tested fix and release bump, then push the resulting HEAD directly
to `origin/main`. Create GitHub Release `v0.1.13`, wait for `publish.yml`, and
verify PyPI JSON plus a clean installation expose version `0.1.13`.

