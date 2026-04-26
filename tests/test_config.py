from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from soil_tiller_calculator.config import (
    AppSettings,
    ConfigError,
    active_config_path,
    default_config_path,
    load_settings,
    merge_imported_settings,
    move_settings_to_default_path,
    move_settings_to_path,
    settings_from_dict,
    settings_from_json,
    settings_to_json,
)
from soil_tiller_calculator.models import ReferencePoint, ToolProfile


def make_tool(tool_id: str = "custom") -> ToolProfile:
    return ToolProfile(
        id=tool_id,
        name="Custom",
        width_m=0.45,
        base_depth_cm=10,
        reference_points=(ReferencePoint(6, 300), ReferencePoint(10, 420)),
        color="#00aa00",
    )


def test_settings_roundtrip_json() -> None:
    settings = AppSettings(
        language="en",
        custom_tools=[make_tool()],
        selected_tool_ids=["custom"],
        custom_speed_limits_enabled=True,
        speed_min_kmh=3.0,
        speed_max_kmh=14.0,
        custom_depth_limits_enabled=True,
        depth_min_cm=4.0,
        depth_max_cm=30.0,
        speed_step_kmh=0.25,
        last_seen_changelog_version="0.2.4",
        pretty_interface_enabled=True,
        startup_instruction_dismissed=True,
        inline_help_enabled=False,
    )
    loaded = settings_from_json(settings_to_json(settings))
    assert loaded.language == "en"
    assert loaded.selected_tool_ids == ["custom"]
    assert loaded.custom_speed_limits_enabled is True
    assert loaded.speed_min_kmh == pytest.approx(3.0)
    assert loaded.speed_max_kmh == pytest.approx(14.0)
    assert loaded.custom_depth_limits_enabled is True
    assert loaded.depth_min_cm == pytest.approx(4.0)
    assert loaded.depth_max_cm == pytest.approx(30.0)
    assert loaded.speed_step_kmh == pytest.approx(0.25)
    assert loaded.last_seen_changelog_version == "0.2.4"
    assert loaded.pretty_interface_enabled is True
    assert loaded.startup_instruction_dismissed is True
    assert loaded.inline_help_enabled is False
    assert len(loaded.custom_tools) == 1
    assert loaded.custom_tools[0].id == "custom"
    assert loaded.custom_tools[0].width_m == pytest.approx(0.45)


def test_old_config_without_speed_limit_fields_uses_defaults() -> None:
    loaded = settings_from_dict({"schema_version": 1, "settings": {"language": "en"}, "custom_tools": []})
    assert loaded.language == "en"
    assert loaded.custom_speed_limits_enabled is False
    assert loaded.speed_min_kmh == pytest.approx(5.0)
    assert loaded.speed_max_kmh == pytest.approx(12.0)
    assert loaded.custom_depth_limits_enabled is False
    assert loaded.depth_min_cm == pytest.approx(5.0)
    assert loaded.depth_max_cm == pytest.approx(20.0)
    assert loaded.speed_step_kmh == pytest.approx(0.5)
    assert loaded.last_seen_changelog_version == ""
    assert loaded.pretty_interface_enabled is False
    assert loaded.startup_instruction_dismissed is False
    assert loaded.inline_help_enabled is True


def test_config_rejects_wrong_schema_version() -> None:
    with pytest.raises(ConfigError):
        settings_from_dict({"schema_version": 999, "settings": {}, "custom_tools": []})


def test_config_rejects_non_list_tools() -> None:
    with pytest.raises(ConfigError):
        settings_from_dict({"schema_version": 1, "settings": {}, "custom_tools": {}})


def test_config_rejects_invalid_tool_width() -> None:
    data = {
        "schema_version": 1,
        "settings": {},
        "custom_tools": [
            {
                "id": "bad",
                "name": "Bad",
                "width_m": -1,
                "base_depth_cm": 10,
                "reference_points": [{"speed_kmh": 6, "force_n": 100}, {"speed_kmh": 10, "force_n": 200}],
            }
        ],
    }
    with pytest.raises(ValueError):
        settings_from_dict(data)


def test_config_rejects_tool_with_too_few_reference_points() -> None:
    data = {
        "schema_version": 1,
        "settings": {},
        "custom_tools": [
            {
                "id": "bad",
                "name": "Bad",
                "width_m": 0.5,
                "base_depth_cm": 10,
                "reference_points": [{"speed_kmh": 6, "force_n": 100}],
            }
        ],
    }
    with pytest.raises(ValueError):
        settings_from_dict(data)


def test_imported_builtin_id_does_not_overwrite_builtin_tool() -> None:
    data = {
        "schema_version": 1,
        "settings": {"language": "ru"},
        "custom_tools": [
            {
                "id": "kps",
                "name": "Fake KPS",
                "width_m": 999,
                "base_depth_cm": 10,
                "reference_points": [{"speed_kmh": 6, "force_n": 1}, {"speed_kmh": 10, "force_n": 2}],
            }
        ],
    }
    settings = settings_from_dict(data)
    assert settings.custom_tools == []


def test_duplicate_custom_id_in_config_keeps_last_tool() -> None:
    first = make_tool("same").to_dict()
    second = make_tool("same").to_dict()
    second["name"] = "Replacement"
    loaded = settings_from_dict({"schema_version": 1, "settings": {}, "custom_tools": [first, second]})
    assert len(loaded.custom_tools) == 1
    assert loaded.custom_tools[0].name == "Replacement"


def test_merge_imported_settings_replaces_conflicting_custom_tool() -> None:
    current = AppSettings(language="ru", custom_tools=[make_tool("same")], selected_tool_ids=["same"])
    replacement = make_tool("same").to_dict()
    replacement["name"] = "Imported"
    imported = settings_from_json(json.dumps({"schema_version": 1, "settings": {"language": "en"}, "custom_tools": [replacement]}))

    merged = merge_imported_settings(current, imported)

    assert merged.language == "en"
    assert len(merged.custom_tools) == 1
    assert merged.custom_tools[0].name == "Imported"


def test_config_location_bootstrap_can_move_and_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path.cwd() / ".cache" / f"config-test-{os.getpid()}"
    root.mkdir(parents=True, exist_ok=True)
    custom_path = root / "custom-config.json"
    monkeypatch.setattr("soil_tiller_calculator.config.user_config_dir", lambda: root)

    settings = AppSettings(language="en", custom_speed_limits_enabled=True, speed_min_kmh=2.0, speed_max_kmh=9.0)
    move_settings_to_path(settings, custom_path)

    assert active_config_path() == custom_path.resolve()
    assert load_settings().language == "en"
    assert load_settings().speed_min_kmh == pytest.approx(2.0)

    move_settings_to_default_path(settings)

    assert active_config_path() == default_config_path()
    assert load_settings().speed_max_kmh == pytest.approx(9.0)
