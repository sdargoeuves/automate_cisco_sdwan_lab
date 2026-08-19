# Development & Release Workflow

## Overview

Two branches for the entire workflow:

- **`main`**: production releases only (tagged with version — users install from these tags)
- **`dev`**: integration branch for testing features before release

## Step 1: Develop & Test Features

Create feature branches from `dev`:

```bash
git checkout dev
git pull origin dev
git checkout -b feature/my-feature
# ... commit work ...
git push origin feature/my-feature
```

Open a PR: base=`dev`, compare=`feature/my-feature`. Once merged to `dev`, the
feature is ready for integration testing.

## Step 2: Test Dev Version

Once features are merged to `dev`, test the dev version before creating a release:

```bash
# Install the dev version from your fork
pip install git+https://github.com/YOUR_USERNAME/automate_cisco_sdwan_lab.git@dev

# Or with uv:
uv pip install git+https://github.com/YOUR_USERNAME/automate_cisco_sdwan_lab.git@dev

# Run your tests
sdwan-automation first-boot
sdwan-automation edges failed --cert
sdwan-automation show devices
```

If issues are found, fix them on `dev` and reinstall:

```bash
pip install --upgrade --force-reinstall git+https://github.com/YOUR_USERNAME/automate_cisco_sdwan_lab.git@dev
```

## Step 3: Merge Dev to Main

Once `dev` is validated and ready to ship, merge it to `main`:

```bash
git checkout main
git pull origin main
git merge dev
git push origin main
```

Or via GitHub: create a PR from `dev` → `main`, and merge via the UI.

## Step 4: Bump Version & Tag

Edit `pyproject.toml` and update the version:

```toml
[project]
version = "X.Y.Z"
```

Commit and tag:

```bash
git commit -am "Bump version to X.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin main
git push origin vX.Y.Z
```

## Step 5: Create GitHub Release

Go to **Releases** > **Create a new release**:

- Select the tag you just pushed (`vX.Y.Z`)
- Title: `Release vX.Y.Z`
- Description: Add release notes (what changed, improvements, fixes)
- Click **Publish release**

GitHub will automatically create a downloadable `.zip` archive. Users can install via:

```bash
pip install git+https://github.com/sdargoeuves/automate_cisco_sdwan_lab.git@vX.Y.Z
```

## Workflow Loop

After a successful release:

- Continue working on `dev` for the next batch of features
- When ready for the next release, repeat from Step 3

## Versioning

Semantic versioning (`MAJOR.MINOR.PATCH`):

- **PATCH** (e.g. `2.1.1`): bug fixes, no behavior changes for users
- **MINOR** (e.g. `2.2.0`): backwards-compatible improvements or new capabilities
  - Example: "More reliable PAYG license serialization"
- **MAJOR** (e.g. `3.0.0`): breaking changes to CLI usage, config format, or supported topologies
  - Example: "Redesigned variables.yml structure"

## Quick Reference

```bash
# Start a feature branch
git checkout dev && git pull
git checkout -b feature/my-feature

# Test dev version locally
pip install --upgrade --force-reinstall git+https://github.com/YOUR_USERNAME/automate_cisco_sdwan_lab.git@dev

# When ready to release: merge dev to main
git checkout main && git pull
git merge dev
git push origin main

# Bump version and tag
# Edit pyproject.toml, change version to X.Y.Z
git commit -am "Bump version to X.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin main vX.Y.Z

# Create GitHub release via the UI with release notes
```
