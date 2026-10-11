# AGENTS.md

Instructions for AI coding assistants (Gemini, Claude, Copilot, …) and humans working on this repo.
Gemini users: point Gemini at this file (or symlink it as `GEMINI.md`). Claude reads `AGENTS.md`/`CLAUDE.md`.

## What this is

`aethelnet-node` is the FastAPI daemon around the `LiquidGraph` engine from
[`aethelnet-core`](https://github.com/aethelnet/aethelnet-core). It stores the graph in SQLite
(or PostgreSQL), runs background daemons (sensors, spiders, Ouroboros loop, P2P sync) and exposes
the REST/WebSocket API used by the dashboard and the SDK.

## Layout

| Path | Purpose |
|---|---|
| `aethelnet_node/main.py` | App setup, middleware, router registration |
| `aethelnet_node/security.py` | Token auth middleware, CORS config, code-exec switch, path checks |
| `aethelnet_node/routers/` | API endpoints, one module per area |
| `aethelnet_node/state.py` | Shared in-memory graph, embeddings, peer discovery |
| `aethelnet_node/database.py` | Persistence (SQLite default, PostgreSQL optional) |
| `aethelnet_node/daemons.py` | Background loops started in the app lifespan |
| `aethelnet_node/ontology/` | Investigation schemas, conflict rules, seed data |
| `tests/` | pytest/unittest suite (runs in CI) |

## Setup and tests

The repo expects `aethelnet-core` checked out next to it (`../aethelnet-core`, see `pytest.ini`).

```bash
python -m venv .venv && . .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-dev.txt
pytest -q
```

Without `sentence-transformers` the node uses deterministic SHA-256 embeddings. That is intended for tests.

## Rules

1. **Run `pytest -q` before saying something works**, and paste the summary line in the PR.
   "Cleaned up" or "fixed" without evidence is not done.
2. **No secrets, IPs or personal paths in the repo.** Configuration goes through environment variables
   (see `.env.example`); `.env` is git-ignored. Before committing a cleanup, prove it with
   `git grep -nE "<pattern>"`. Anything ever pushed stays in git history, so leaked keys must be rotated,
   not just deleted.
3. **Security defaults stay on.** Write requests need an agent token (`python -m aethelnet_node.agents add <id>`)
   or `AETHELNET_AUTH_TOKEN` (or come from localhost), NaaS code execution needs `AETHELNET_ALLOW_CODE_EXEC=1`.
   Don't weaken these to make a feature work; send the token instead (`security.auth_headers()`).
   Use your own agent token, never another agent's, so provenance stays true.
4. **New endpoints get a test** in `tests/`. Use `fastapi.testclient.TestClient`.
5. **Keep docs honest.** README claims (complexity, test counts, guarantees) must match the code.
   If you change behavior, update the README in the same PR.
6. **Small PRs, one topic each.** Branch names: `fix/…`, `feat/…`, `security/…`, `docs/…`, `ci/…`, `perf/…`, `chore/…`.
7. Commit messages: imperative summary line (`fix: …`, `feat: …`), body explains *why*.

## Environment variables

See `.env.example` for the full list. The important ones:
`AETHELNET_AGENTS_FILE`, `AETHELNET_AUTH_TOKEN`, `AETHELNET_CORS_ORIGINS`, `AETHELNET_PEERS`, `AETHELNET_PEER_TOKEN`,
`AETHELNET_ALLOW_CODE_EXEC`, `DB_PROVIDER`, `DATABASE_URL`.
