# Release process

1. Create a release branch from the tip of the changes to ship:
   ```
   git checkout -b release/vX.Y.Z
   ```
2. Bump the `version` field in `pyproject.toml` and commit:
   ```
   git commit -am "Bump version to X.Y.Z"
   ```
3. Push the branch (e.g. via the `ggpush` alias) and open a PR into `main`:
   ```
   gh pr create --title "Bump version to X.Y.Z" --body "Release vX.Y.Z" --base main
   ```
4. Once CI passes, merge the PR.
5. Tag the resulting merge commit on `main` (not the release branch) and push the tag:
   ```
   git checkout main && git pull
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

## Versioning

Semantic versioning (`MAJOR.MINOR.PATCH`):
- **PATCH**: bug fixes, no behavior changes for users.
- **MINOR**: backwards-compatible improvements or new capabilities (e.g. more reliable license generation).
- **MAJOR**: breaking changes to CLI usage, config format, or supported topologies.
