# Public History Checklist

This checklist is safe for a public repository. It names only credential categories and process
steps. Findings and private rotation evidence stay in the operator's private records.

## Sweep

1. Enumerate files ever added to history:

   ```bash
   git log --all --diff-filter=A --name-only
   ```

2. Review the output for credential-shaped files and configuration files that could have carried
   secrets.
3. Run a full-history scanner from a fresh clone:

   ```bash
   gitleaks detect --no-banner
   ```

   If another approved scanner is used, record the tool name and version in the private notes.
4. For each credential category the pre-extraction code could have referenced, confirm in private
   notes that every live credential was rotated on or after publication, or rotate it now:

   - OAuth client configs
   - API tokens
   - service-account keys

5. Never post findings, secret names, account names, project names, or private links in an issue,
   PR, or public commit.

## Ongoing Guard

CI runs a PR-diff gitleaks scan so newly introduced leaks fail before merge. Full-history sweeps
remain an operator-run release checklist item because they depend on private rotation records.

## Completion Log

- 2026-06-11 - Repo-side checklist and CI guard added; private full-history sweep and rotation
  confirmation remain operator TODO.
