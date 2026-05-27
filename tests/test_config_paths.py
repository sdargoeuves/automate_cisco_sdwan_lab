from pathlib import Path

from utils import config_paths


def test_user_config_dir_honors_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert config_paths.user_config_dir() == tmp_path / "sdwan-automation"
    assert config_paths.user_base_path() == tmp_path / "sdwan-automation" / "base.yml"
    assert (
        config_paths.user_variables_path()
        == tmp_path / "sdwan-automation" / "variables.yml"
    )


def test_user_config_dir_defaults_to_home_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert config_paths.user_config_dir() == tmp_path / ".config" / "sdwan-automation"
