# Release Rules

## Local PAT Storage Rule

- Keep real credentials in `.git/version-release-auth.env` only.
- Use `local-auth.example.env` as a template reference.
- Do not commit any file containing real PAT.

## Version Preparation Rule (Before Commit)

Fetch tags, then prepare the next version without committing, tagging, or pushing:

```powershell
powershell -ExecutionPolicy Bypass -File .codex/skills/version-release/scripts/git-auth.ps1 fetch origin --tags
powershell -ExecutionPolicy Bypass -File .codex/skills/version-release/scripts/prepare-next-version.ps1
```

Expected behavior:

- Compute the next tag in strict format `vX.0.Y`.
- Run `npm version X.0.Y --no-git-tag-version` so `package.json` and `package-lock.json` stay synchronized.
- Do not modify Android `versionName` or `versionCode` directly; Gradle reads `package.json` dynamically.
- Run `npm run verify:version` after the bump.
- Write text as UTF-8 without BOM and fail on invalid replacement/control characters.
- Never commit, create a tag, or push automatically.

## Version and Android Code Rules

- `package.json` `version` is the only source of truth.
- Version format: `X.0.Y`.
- Release tag format: `vX.0.Y`.
- Android `versionCode = major * 1000000 + patch`.

## Commit Template

Use repository `.gitmessage` structure exactly and fill unavailable sections with `N/A`.

## Local Commit Execution Rule

Save the message in UTF-8 without BOM and run:

```powershell
powershell -ExecutionPolicy Bypass -File .codex/skills/version-release/scripts/commit-local-with-check.ps1 -MessageFile .git/COMMIT_MSG.txt
```

## Release Tag Rule

- Required format: `vX.0.Y`.
- Tag must match the version already written into `package.json`.
- Prefer ASCII-only annotation text when possible.

## Remote Command Rule

Use auth wrapper for every remote operation; never print or store PAT in tracked files.
