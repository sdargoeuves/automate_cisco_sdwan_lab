# Release process

1. Create a release branch from the tip of the changes to ship:

   ```bash
   git checkout -b release/vX.Y.Z
   ```

2. Bump the `version` field in `pyproject.toml` and commit:

   ```bash
   git commit -am "Bump version to X.Y.Z"
   ```

3. Push the branch (e.g. via the `ggpush` alias), then open a PR in the GitHub UI:

   - Go to the repo on github.com — it should show a banner for the just-pushed
     branch with a **Compare & pull request** button.
   - If not, go to **Pull requests** > **New pull request**, set base = `main`
     and compare = `release/vX.Y.Z`.
   - Title it `Bump version to X.Y.Z`, add release notes to the description,
     and click **Create pull request**.

4. Once CI passes, click **Merge pull request** in the GitHub UI.

5. Tag the resulting merge commit on `main` (not the release branch) and push the tag:

   ```bash
   git checkout main && git pull
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

## Versioning

Semantic versioning (`MAJOR.MINOR.PATCH`):

- **PATCH**: bug fixes, no behavior changes for users.
- **MINOR**: backwards-compatible improvements or new capabilities (e.g. more reliable license generation).
- **MAJOR**: breaking changes to CLI usage, config format, or supported topologies.
