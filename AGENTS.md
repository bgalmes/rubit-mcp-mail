# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project

`rubit-mcp-mail` is a provider-agnostic, read-only MCP server for reading mail over IMAP.
Python 3.11+, `src/` layout:

- `src/rubit_mcp_mail/` — package root
- `src/rubit_mcp_mail/backends/` — provider-specific backends
- `src/rubit_mcp_mail/auth/` — auth handling
- `tests/` — test suite
- `website/` — the documentation site (Nuxt 4 + Nuxt UI), deployed to GitHub Pages. It is
  the source of truth for the docs; `README.md` is deliberately the short version.

See the README's "Layout" section for a file-by-file breakdown.

## Dev commands

These are the same checks CI runs (`.github/workflows/ci.yml`):

```sh
ruff check .
ruff format --check .
pyright
pytest -q
```

## Contributing: commit message format

Commit messages on `main` drive automatic versioning via `python-semantic-release`, so they
must follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

| Prefix | Effect on version |
| --- | --- |
| `fix:` | patch (`0.1.0` → `0.1.1`) |
| `feat:` | minor (`0.1.0` → `0.2.0`) |
| `BREAKING CHANGE:` in the footer, or `!` after the type/scope (e.g. `feat!:`) | major (`0.1.0` → `1.0.0`) |

Other common types (`docs:`, `refactor:`, `test:`, `chore:`, `ci:`) don't trigger a release.

**Changes under `website/` must never use `feat:` or `fix:`.** The parser keys on the commit
*type*, not the scope, so `feat(site): ...` bumps the Python package and cuts an installer
release. Use `docs(site):`, `chore(site):` or `ci(site):`.

PRs are squash-merged, so the **squash commit message** is what the release tooling parses —
make sure it follows this format, not just the individual commits on the branch.

Branching model is plain GitHub Flow: branch off `main`, PR back into `main`, delete the
branch after merge. The `release/next` and `release/promote` branches belong to the release
bot — never branch off them or commit to them by hand. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the full branching model and release process (a bot
prepares a release PR, a maintainer merges it to publish the prerelease, then promotes to
stable manually).
