"""User-facing config paths for sdwan-automation.

Layout under the user config directory (defaults to ``$XDG_CONFIG_HOME/sdwan-automation``
or ``~/.config/sdwan-automation``):

  base.yml        — user-editable template (created by `sdwan-automation init`)
  variables.yml   — output of `generate`, consumed by every other subcommand

The pristine template lives inside the installed package at
``utils/templates/sdwan_base_variables.yml`` and is the source `init` copies from.
"""

import os
import shutil
from importlib.resources import as_file, files
from pathlib import Path

APP_NAME = "sdwan-automation"
BASE_FILENAME = "base.yml"
VARIABLES_FILENAME = "variables.yml"
BUNDLED_TEMPLATE_NAME = "sdwan_base_variables.yml"


def user_config_dir() -> Path:
    """Return the user config directory ($XDG_CONFIG_HOME or ~/.config)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / APP_NAME


def user_base_path() -> Path:
    return user_config_dir() / BASE_FILENAME


def user_variables_path() -> Path:
    return user_config_dir() / VARIABLES_FILENAME


def bundled_template_path() -> Path:
    """Materialize the bundled base template to a real filesystem path."""
    resource = files("utils.templates") / BUNDLED_TEMPLATE_NAME
    with as_file(resource) as p:
        # `as_file` may return a temp path when the package is zipped; for normal
        # installs it's the on-disk file. Either way, callers should read it
        # immediately rather than hold the path.
        return Path(p)


def install_base_template(force: bool = False) -> tuple[Path, bool]:
    """Copy the bundled template into ``user_base_path()``.

    Returns (destination_path, created) where ``created`` is True if a new file
    was written, False if the file already existed and ``force`` was False.
    """
    dest = user_base_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        return dest, False

    resource = files("utils.templates") / BUNDLED_TEMPLATE_NAME
    with as_file(resource) as src:
        shutil.copyfile(src, dest)
    return dest, True
