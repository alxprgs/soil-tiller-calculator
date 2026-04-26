from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from soil_tiller_calculator.models import BUILTIN_TOOL_IDS, ToolProfile

SCHEMA_VERSION = 1


class ConfigError(ValueError):
    """Ошибка чтения или проверки JSON-конфига приложения."""


@dataclass(slots=True)
class AppSettings:
    """Пользовательские настройки приложения.

    Хранит выбранный язык, пользовательские инструменты, диапазоны скорости
    и глубины, а также шаг перебора скоростей для автооптимизации.
    """

    language: str = "ru"
    custom_tools: list[ToolProfile] = field(default_factory=list)
    selected_tool_ids: list[str] = field(default_factory=lambda: ["kps", "exp"])
    custom_speed_limits_enabled: bool = False
    speed_min_kmh: float = 5.0
    speed_max_kmh: float = 12.0
    custom_depth_limits_enabled: bool = False
    depth_min_cm: float = 5.0
    depth_max_cm: float = 20.0
    speed_step_kmh: float = 0.5
    last_seen_changelog_version: str = ""

    def all_tools(self) -> list[ToolProfile]:
        """Возвращает полный список инструментов: встроенные плюс пользовательские."""
        from soil_tiller_calculator.models import BUILTIN_TOOLS

        return [*BUILTIN_TOOLS.values(), *self.custom_tools]

    def to_dict(self) -> dict[str, Any]:
        """Преобразует настройки в словарь, пригодный для JSON-сохранения."""
        return {
            "schema_version": SCHEMA_VERSION,
            "settings": {
                "language": self.language,
                "selected_tool_ids": self.selected_tool_ids,
                "custom_speed_limits_enabled": self.custom_speed_limits_enabled,
                "speed_min_kmh": self.speed_min_kmh,
                "speed_max_kmh": self.speed_max_kmh,
                "custom_depth_limits_enabled": self.custom_depth_limits_enabled,
                "depth_min_cm": self.depth_min_cm,
                "depth_max_cm": self.depth_max_cm,
                "speed_step_kmh": self.speed_step_kmh,
                "last_seen_changelog_version": self.last_seen_changelog_version,
            },
            "custom_tools": [tool.to_dict() for tool in self.custom_tools],
        }


def user_config_dir() -> Path:
    """Возвращает стандартную папку пользовательских настроек.

    На Windows используется APPDATA, на Linux — XDG_CONFIG_HOME или ~/.config.
    """
    if os.name == "nt":
        root = os.environ.get("APPDATA")
        if root:
            return Path(root) / "SoilTillerCalculator"
        return Path.home() / "AppData" / "Roaming" / "SoilTillerCalculator"

    root = os.environ.get("XDG_CONFIG_HOME")
    if root:
        return Path(root) / "soil-tiller-calculator"
    return Path.home() / ".config" / "soil-tiller-calculator"


def default_config_path() -> Path:
    """Возвращает стандартный путь к основному config.json."""
    return user_config_dir() / "config.json"


def config_location_path() -> Path:
    """Возвращает путь к bootstrap-файлу с выбранным местом хранения конфига."""
    return user_config_dir() / "config-location.json"


def active_config_path() -> Path:
    """Определяет активный путь к config.json.

    Если bootstrap-файл существует и содержит путь, используется он.
    Если bootstrap некорректен или отсутствует, возвращается стандартный путь.
    """
    location_path = config_location_path()
    if not location_path.exists():
        return default_config_path()
    try:
        data = json.loads(location_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_config_path()
    selected = data.get("config_path")
    if not isinstance(selected, str) or not selected:
        return default_config_path()
    return Path(selected).expanduser()


def set_active_config_path(path: Path) -> None:
    """Запоминает пользовательский путь к config.json в bootstrap-файле."""
    location_path = config_location_path()
    location_path.parent.mkdir(parents=True, exist_ok=True)
    location_path.write_text(
        json.dumps({"config_path": str(path.expanduser().resolve())}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def reset_active_config_path() -> None:
    """Сбрасывает пользовательский путь и возвращает приложение к стандартному config.json."""
    location_path = config_location_path()
    if location_path.exists():
        location_path.unlink()


def move_settings_to_path(settings: AppSettings, path: Path) -> None:
    """Сохраняет текущие настройки в новый файл и делает его активным."""
    save_settings(settings, path)
    set_active_config_path(path)


def move_settings_to_default_path(settings: AppSettings) -> None:
    """Переносит текущие настройки в стандартный config.json и сбрасывает bootstrap."""
    save_settings(settings, default_config_path())
    reset_active_config_path()


def load_settings(path: Path | None = None) -> AppSettings:
    """Загружает настройки приложения.

    path: явный путь к JSON-конфигу. Если не указан, используется active_config_path.
    Возвращает AppSettings; если файла нет, возвращает настройки по умолчанию.
    """
    config_path = path or active_config_path()
    if not config_path.exists():
        settings = AppSettings()
        if path is None and config_path != default_config_path():
            save_settings(settings, config_path)
        return settings
    return settings_from_json(config_path.read_text(encoding="utf-8"))


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    """Сохраняет настройки в JSON-файл.

    settings: объект настроек.
    path: путь сохранения; если не указан, используется активный config.json.
    """
    config_path = path or active_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(settings_to_json(settings), encoding="utf-8")


def settings_to_json(settings: AppSettings) -> str:
    """Сериализует настройки в форматированный JSON-текст."""
    return json.dumps(settings.to_dict(), ensure_ascii=False, indent=2)


def settings_from_json(raw: str) -> AppSettings:
    """Создаёт AppSettings из JSON-строки.

    При ошибке синтаксиса JSON выбрасывает ConfigError.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON: {exc}") from exc
    return settings_from_dict(data)


def settings_from_dict(data: dict[str, Any]) -> AppSettings:
    """Проверяет словарь конфига и создаёт AppSettings.

    data: объект, прочитанный из JSON. Функция поддерживает старые конфиги
    без новых полей, подставляя значения по умолчанию.
    """
    if not isinstance(data, dict):
        raise ConfigError("Config root must be an object.")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ConfigError(f"Unsupported schema_version: {data.get('schema_version')!r}.")

    settings_data = data.get("settings", {})
    if not isinstance(settings_data, dict):
        raise ConfigError("settings must be an object.")
    language = str(settings_data.get("language", "ru"))
    selected_tool_ids = settings_data.get("selected_tool_ids", ["kps", "exp"])
    if not isinstance(selected_tool_ids, list) or not all(isinstance(item, str) for item in selected_tool_ids):
        raise ConfigError("selected_tool_ids must be a list of strings.")
    custom_speed_limits_enabled = bool(settings_data.get("custom_speed_limits_enabled", False))
    speed_min_kmh = float(settings_data.get("speed_min_kmh", 5.0))
    speed_max_kmh = float(settings_data.get("speed_max_kmh", 12.0))
    custom_depth_limits_enabled = bool(settings_data.get("custom_depth_limits_enabled", False))
    depth_min_cm = float(settings_data.get("depth_min_cm", 5.0))
    depth_max_cm = float(settings_data.get("depth_max_cm", 20.0))
    speed_step_kmh = float(settings_data.get("speed_step_kmh", 0.5))
    last_seen_changelog_version = str(settings_data.get("last_seen_changelog_version", ""))

    tool_items = data.get("custom_tools", [])
    if not isinstance(tool_items, list):
        raise ConfigError("custom_tools must be a list.")

    custom_tools: list[ToolProfile] = []
    for item in tool_items:
        if not isinstance(item, dict):
            raise ConfigError("Each custom tool must be an object.")
        tool = ToolProfile.from_dict(item, built_in=False)
        if tool.id in BUILTIN_TOOL_IDS:
            continue
        custom_tools = [existing for existing in custom_tools if existing.id != tool.id]
        custom_tools.append(tool)

    return AppSettings(
        language=language,
        custom_tools=custom_tools,
        selected_tool_ids=selected_tool_ids,
        custom_speed_limits_enabled=custom_speed_limits_enabled,
        speed_min_kmh=speed_min_kmh,
        speed_max_kmh=speed_max_kmh,
        custom_depth_limits_enabled=custom_depth_limits_enabled,
        depth_min_cm=depth_min_cm,
        depth_max_cm=depth_max_cm,
        speed_step_kmh=speed_step_kmh,
        last_seen_changelog_version=last_seen_changelog_version,
    )


def merge_imported_settings(current: AppSettings, imported: AppSettings) -> AppSettings:
    """Объединяет текущие настройки с импортированными.

    Пользовательские инструменты с одинаковым id заменяются импортированными.
    Язык, диапазоны и шаг оптимизации берутся из импортированного конфига.
    """
    custom_tools = [tool for tool in current.custom_tools]
    for imported_tool in imported.custom_tools:
        custom_tools = [tool for tool in custom_tools if tool.id != imported_tool.id]
        custom_tools.append(imported_tool)
    return AppSettings(
        language=imported.language or current.language,
        custom_tools=custom_tools,
        selected_tool_ids=imported.selected_tool_ids or current.selected_tool_ids,
        custom_speed_limits_enabled=imported.custom_speed_limits_enabled,
        speed_min_kmh=imported.speed_min_kmh,
        speed_max_kmh=imported.speed_max_kmh,
        custom_depth_limits_enabled=imported.custom_depth_limits_enabled,
        depth_min_cm=imported.depth_min_cm,
        depth_max_cm=imported.depth_max_cm,
        speed_step_kmh=imported.speed_step_kmh,
        last_seen_changelog_version=imported.last_seen_changelog_version or current.last_seen_changelog_version,
    )
