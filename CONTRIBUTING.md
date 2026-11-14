# Contributing

## Branch policy

- `main` is the only maintained branch.
- There is no long-lived development branch.
- Open pull requests against `main`.
- Releases are cut from `main`.

## Commit messages

This project uses [Conventional Commits](https://www.conventionalcommits.org/). Pull request titles must follow the same format, because squash merges use the pull request title as the commit message.

| Type | Use for |
| --- | --- |
| `feat` | A new user-facing feature or entity. |
| `fix` | A bug fix. |
| `docs` | Documentation only. |
| `refactor` | A code change that neither fixes a bug nor adds a feature. |
| `test` | Adding or updating tests. |
| `ci` | Workflows and automation. |
| `chore` | Maintenance, dependencies and release bookkeeping. |
| `perf` | Performance improvements. |

Examples:

```text
feat(sensor): add alert count and latest alert
fix(coordinator): reconnect once after a 403 response
docs: clarify the single admin session limitation
chore(release): 1.4.1
```

- Use an optional scope in parentheses when it helps: `fix(client): ...`.
- Use the imperative mood and a lowercase subject without a trailing period.
- Keep the subject line short; explain the reason in the body for non-trivial changes.
- Mark a breaking change with `!` after the type or scope, or with a `BREAKING CHANGE:` footer:

```text
feat(config)!: replace the version field

BREAKING CHANGE: existing entries must be recreated.
```

## Semantic Versioning

Releases follow [Semantic Versioning 2.0.0](https://semver.org/): `MAJOR.MINOR.PATCH`.

- **MAJOR** — breaking changes for users or integrations. Examples: renaming or removing entity unique IDs, changing device identifiers, removing a platform or entity, changing config entry data without a migration, or raising the minimum Home Assistant version beyond the previously supported range.
- **MINOR** — new backwards-compatible features. Examples: new sensors, binary sensors, options or platforms.
- **PATCH** — backwards-compatible fixes and maintenance. Examples: bug fixes, documentation, CI changes and dependency updates that do not change behavior.
- Pre-releases use a suffix such as `1.4.0-beta.1`.

Entity IDs and unique IDs are part of the public interface. Changing them can break dashboards, automations and long-term statistics, so treat such changes as breaking.

## Release process

1. Update the version in `custom_components/mycloud/manifest.json`.
2. Move the `Unreleased` entries in `CHANGELOG.md` under the new version and date.
3. Run the checks:

   ```bash
   ruff check custom_components tests
   ruff format --check custom_components tests
   pytest
   ```

4. Commit the release bookkeeping with `chore(release): X.Y.Z`.
5. Create the tag `vX.Y.Z` from `main` and publish a GitHub release targeting `main`.
6. Verify that the release workflow succeeded and that the release asset `mycloud.zip` contains `manifest.json` at the root with a version matching the release tag.

HACS installs the integration from the release asset, so the ZIP layout is part of the release contract.
