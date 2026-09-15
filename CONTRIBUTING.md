# Contributing

## Branching model

This repo uses **GitHub Flow**: `main` is the only long-lived branch and is
always releasable.

- Branch off `main` for any change, work there, open a PR back into `main`.
- No `develop` or `hotfix/*` branches. The only `release/*` branches are
  `release/next` and `release/promote`, which the release bot creates, force-
  pushes and reuses — never branch off them or commit to them by hand.
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

Releases are prepared automatically from `main`, but nothing ships until a
maintainer merges the release PR, and nothing is "final" just because it
merged:

1. **Merging a PR into `main`** runs `python-semantic-release`, which reads
   the commits since the last release, computes the next version, and opens
   (or rewrites) a **release PR** from `release/next` carrying just the
   version bump and the changelog entry.
2. **Merging that release PR** tags the merge commit and publishes it as a
   **GitHub prerelease** (e.g. `1.3.0-rc.1`), with installers built and
   attached, so every prerelease is a real, testable build. Nothing
   auto-merges it: a PR merged by the bot would fire no event and nothing
   would get published. Merging it is the one manual step per release
   candidate.
3. **Try the prerelease.** Further merges to `main` before it's promoted
   bump the release candidate (`1.3.0-rc.2`, `1.3.0-rc.3`, ...).
4. **Promoting to stable is manual.** A maintainer runs the "Promote to
   stable" workflow (`workflow_dispatch`), which opens a `release/promote`
   PR carrying the same version without the `-rc.N` suffix; merging it
   publishes the final release (`1.3.0`) with the prerelease flag cleared.

This keeps the single-`main` simplicity of GitHub Flow while still
separating "shipped for testing" from "shipped as production" — see the
discussion on [#11](https://github.com/bgalmes/rubit-mcp-mail/issues/11) for
why.

## Development

See the [Development](README.md#development) section of the README for
running tests and building the installers locally.
