# Contributing to aethelnet-node

Thanks for helping out! 🙌

## Workflow

1. Open an issue (or comment on an existing one) so we agree on the approach first.
2. Create a branch: `fix/…`, `feat/…`, `security/…`, `docs/…`, `ci/…`, `perf/…` or `chore/…`.
3. Keep the PR focused on one topic. Small PRs get reviewed and merged faster.
4. Make sure `pytest -q` passes locally (setup in [AGENTS.md](AGENTS.md)) and CI is green.
5. Fill in the PR template, including what you tested.

## Code style

- Follow the style of the surrounding code.
- Configuration comes from environment variables, never from hard-coded values. Add new ones to `.env.example`.
- New endpoints need a test in `tests/`.

## Security

Please don't report vulnerabilities in public issues. See [SECURITY.md](SECURITY.md).

## AI assistants

AI-generated contributions are welcome. The same rules apply as for humans; see [AGENTS.md](AGENTS.md).
In particular: show test output, don't just claim it works.
