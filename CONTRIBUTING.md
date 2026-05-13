# Contributing Guide

Thanks for your interest in contributing to alpha-common!

## Development Setup

```bash
uv sync
```

## Code Style

We use Ruff for linting and formatting:

```bash
ruff check . --fix
ruff format .
```

## Testing

```bash
pytest tests/
```

## Commit Convention

We use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation only
- `refactor:` — code restructuring
- `test:` — add or fix tests
- `chore:` — build/tooling changes

## Pull Request Process

1. Create a feature branch from `main`
2. Ensure tests pass and code is formatted
3. Open a PR targeting `main`
4. Wait for review and approval before merging
