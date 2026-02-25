import json
from pathlib import Path

from agentdeck.config import Settings, _load_config_file


def test_settings_reads_state_config_json(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "tmux_pane_width": 222,
                "confirm_image_upload": True,
            }
        )
    )

    settings = _load_config_file(Settings(state_dir=str(tmp_path)))

    assert settings.tmux_pane_width == 222
    assert settings.confirm_image_upload is True


def test_settings_json_expands_user_dirs(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "default_working_dir": "~/projects",
                "rehydrate_dir_whitelist": ["~/work", "/tmp/static"],
            }
        )
    )

    settings = _load_config_file(Settings(state_dir=str(tmp_path)))

    assert settings.default_working_dir == str(fake_home / "projects")
    assert settings.rehydrate_dir_whitelist == [
        str(fake_home / "work"),
        "/tmp/static",
    ]


def test_config_json_overrides_env_vars(tmp_path: Path, monkeypatch) -> None:
    """config.json has higher priority than env vars in the simplified version."""
    (tmp_path / "config.json").write_text(json.dumps({"tmux_pane_width": 111}))
    monkeypatch.setenv("TMUX_PANE_WIDTH", "333")

    settings = _load_config_file(Settings(state_dir=str(tmp_path)))

    # In simplified version, config.json overrides env (not ideal but simpler)
    assert settings.tmux_pane_width == 111
