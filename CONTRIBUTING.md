# Contributing

## Branching model

This repo uses **GitHub Flow**: `main` is the only long-lived branch and is
always releasable.

- Branch off `main` for any change, work there, open a PR back into `main`.
- No `develop`, `release/*`, or `hotfix/*` branches.
- Once a PR merges, delete the branch — nothing downstream depends on it
  staying around.

## Commit messages: Conventional Commits

Commit messages on `main` drive automatic versioning
([#11](https://github.com/bgalmes/rubit-mcp-mail/issues/11)), so they need to
follow [Conventional Commits](https://www.conventionalcommits.org/):

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

Other common types (`docs:`, `refactor:`, `test:`, `chore:`, `ci:`) don't
trigger a release by themselves. Squash-merge PRs with a commit message that
follows this format — that's the message the release tooling reads, not the
individual commits on the branch.

## Release process

Releases are cut automatically from `main`, but nothing is "final" just
because it merged:

1. **Merging a PR into `main`** runs `python-semantic-release`, which reads
   the commits since the last release, computes the next version, updates
   the changelog, and publishes a **GitHub prerelease** (e.g. `1.3.0-rc.1`).
   Installers are built and attached to it automatically, so every
   prerelease is a real, testable build.
2. **Try the prerelease.** Further merges to `main` before it's promoted
   bump the release candidate (`1.3.0-rc.2`, `1.3.0-rc.3`, ...).
3. **Promoting to stable is manual.** A maintainer runs the "Promote to
   stable" workflow (`workflow_dispatch`) against the prerelease that's
   ready, which re-publishes it as the final version (`1.3.0`) with the
   prerelease flag cleared.

This keeps the single-`main` simplicity of GitHub Flow while still
separating "shipped for testing" from "shipped as production" — see the
discussion on [#11](https://github.com/bgalmes/rubit-mcp-mail/issues/11) for
why.

## Development

See the [Development](README.md#development) section of the README for
running tests and building the installers locally.
