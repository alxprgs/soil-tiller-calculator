from __future__ import annotations

import json
import re
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from importlib import resources
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from soil_tiller_calculator.calculations import (
    compare_tools,
    force_at_depth,
    optimize_speed,
    plot_speed_grid,
    power_and_fuel,
    specific_resistance,
)
from soil_tiller_calculator.config import (
    AppSettings,
    ConfigError,
    active_config_path,
    load_settings,
    merge_imported_settings,
    move_settings_to_default_path,
    move_settings_to_path,
    save_settings,
    settings_from_json,
    settings_to_json,
)
from soil_tiller_calculator.localization import Localizer
from soil_tiller_calculator.models import BUILTIN_TOOL_IDS, BUILTIN_TOOLS, ToolProfile, ReferencePoint, SpeedRange
from soil_tiller_calculator.version import __version__

RESIZE_SETTLE_MS = 350
LAYOUT_SETTLE_MS = 180
TOOL_MANAGER_BREAKPOINT = 680
ABOUT_BREAKPOINT = 520
GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/alxprgs/soil-tiller-calculator/releases/latest"
CHANGELOG_RESOURCE = "CHANGELOG.json"


def validate_depth(value: str, min_cm: float = 5.0, max_cm: float = 20.0, fallback: float | None = None) -> tuple[float, bool]:
    """Проверяет глубину обработки.

    value: текст из поля ввода.
    min_cm и max_cm: допустимые границы глубины в сантиметрах.
    fallback: значение, которое нужно вернуть при ошибке.
    Возвращает `(глубина, была_ошибка)`.
    """
    fallback_value = fallback if fallback is not None else 10.0
    try:
        depth = float(value)
    except ValueError:
        return fallback_value, True
    if min_cm <= depth <= max_cm:
        return depth, False
    return fallback_value, True


def validate_speed(value: str, min_kmh: float = 5.0, max_kmh: float = 12.0, fallback: float | None = None) -> tuple[float, bool]:
    """Проверяет ручную скорость.

    value: текст из поля ввода.
    min_kmh и max_kmh: допустимый диапазон в км/ч.
    fallback: значение по умолчанию при ошибке.
    Возвращает `(скорость, была_ошибка)`.
    """
    fallback_value = fallback if fallback is not None else 8.0
    try:
        speed = float(value)
    except ValueError:
        return fallback_value, True
    if min_kmh <= speed <= max_kmh:
        return speed, False
    return fallback_value, True


def validate_speed_limits(min_value: str, max_value: str) -> tuple[float, float, bool]:
    """Проверяет пользовательские границы скорости.

    min_value и max_value: строки с минимальной и максимальной скоростью.
    Возвращает `(min, max, была_ошибка)`. При ошибке возвращает 5-12 км/ч.
    """
    try:
        min_kmh = float(min_value)
        max_kmh = float(max_value)
    except ValueError:
        return 5.0, 12.0, True
    if min_kmh < max_kmh:
        return min_kmh, max_kmh, False
    return 5.0, 12.0, True


def validate_depth_limits(min_value: str, max_value: str) -> tuple[float, float, bool]:
    """Проверяет пользовательские границы глубины.

    min_value и max_value: строки с минимальной и максимальной глубиной.
    Возвращает `(min, max, была_ошибка)`. При ошибке возвращает 5-20 см.
    """
    try:
        min_cm = float(min_value)
        max_cm = float(max_value)
    except ValueError:
        return 5.0, 20.0, True
    if min_cm < max_cm:
        return min_cm, max_cm, False
    return 5.0, 20.0, True


def validate_speed_step(value: str) -> tuple[float, bool]:
    """Проверяет шаг перебора скоростей для автооптимизации.

    value: строка с шагом в км/ч. Шаг должен быть положительным.
    Возвращает `(шаг, была_ошибка)`.
    """
    try:
        step = float(value)
    except ValueError:
        return 0.5, True
    if step > 0:
        return step, False
    return 0.5, True


def version_tuple(version: str) -> tuple[int, int, int]:
    """Возвращает числовую часть версии для сравнения тегов GitHub."""
    raw_parts = version.strip().lstrip("vV").split(".")
    parts: list[int] = []
    for raw_part in raw_parts[:3]:
        match = re.match(r"(\d+)", raw_part)
        parts.append(int(match.group(1)) if match else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer_version(latest: str, current: str) -> bool:
    """Проверяет, новее ли версия релиза текущей версии приложения."""
    return version_tuple(latest) > version_tuple(current)


def fetch_latest_release(timeout: float = 5.0) -> tuple[str, str]:
    """Загружает тег и ссылку последнего GitHub-релиза."""
    request = urllib.request.Request(
        GITHUB_LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "soil-tiller-calculator",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    tag = str(payload.get("tag_name") or "")
    url = str(payload.get("html_url") or "https://github.com/alxprgs/soil-tiller-calculator/releases")
    if not tag:
        raise ValueError("GitHub release tag is empty")
    return tag, url


def load_changelog_entries() -> list[dict[str, object]]:
    """Загружает встроенную офлайн-историю изменений."""
    try:
        raw = resources.files("soil_tiller_calculator").joinpath(CHANGELOG_RESOURCE).read_text(encoding="utf-8")
        entries = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def format_changelog(entries: list[dict[str, object]], localizer: Localizer) -> str:
    """Форматирует историю изменений для текстового виджета Tk."""
    if not entries:
        return localizer("changelog.unavailable")

    lines: list[str] = []
    for entry in entries:
        version = str(entry.get("version") or "")
        if bool(entry.get("current")):
            version = localizer("changelog.current_build")
        date = str(entry.get("date") or "")
        title = f"{version} - {date}" if date else version
        lines.append(title)
        lines.append("-" * len(title))
        changes_data = entry.get("changes", [])
        if isinstance(changes_data, dict):
            language = getattr(localizer, "language", "en")
            changes = changes_data.get(language) or changes_data.get("en") or []
        else:
            changes = changes_data
        if isinstance(changes, list):
            for change in changes:
                lines.append(f"* {change}")
        lines.append("")
    return "\n".join(lines).strip()


def should_show_startup_changelog(config_existed_at_start: bool, last_seen_version: str, current_version: str = __version__) -> bool:
    """Проверяет, нужно ли показать историю изменений для существующего конфига."""
    if not config_existed_at_start:
        return False
    return is_newer_version(current_version, last_seen_version)


class MainWindow:
    """Главное окно приложения.

    Отвечает за ввод параметров, запуск расчётов, вывод результатов, графики,
    меню настроек и связь GUI с JSON-конфигом.
    """

    def __init__(self, root: tk.Tk, settings: AppSettings | None = None) -> None:
        """Создаёт главное окно.

        root: корневой объект Tk.
        settings: настройки приложения; если не переданы, загружаются из конфига.
        """
        self.root = root
        self._config_existed_at_start = settings is None and active_config_path().exists()
        self.settings = settings or load_settings()
        if settings is None and not self._config_existed_at_start:
            self.settings.last_seen_changelog_version = __version__
        self.localizer = Localizer(self.settings.language)
        self.graph_canvas = None
        self.figure = None
        self.main_menu: tk.Menu | None = None
        self.file_menu: tk.Menu | None = None
        self.settings_menu: tk.Menu | None = None
        self._menus: list[tk.Menu] = []
        self.menu_labels: tuple[str, str, str] = ()
        self.ttk_style = ttk.Style(self.root)
        self._default_theme = self.ttk_style.theme_use()
        self._styled_widget_names = (
            "TFrame",
            "TLabelframe",
            "TLabelframe.Label",
            "TLabel",
            "TButton",
            "TEntry",
            "TCombobox",
            "TCheckbutton",
            "TRadiobutton",
        )
        self._default_style_options = {style_name: self.ttk_style.configure(style_name) for style_name in self._styled_widget_names}
        self._default_style_maps = {style_name: self.ttk_style.map(style_name) for style_name in self._styled_widget_names}
        self._layout_mode: str | None = None
        self._graph_resize_job: str | None = None
        self._layout_resize_job: str | None = None
        self._last_graph_size: tuple[int, int] = (0, 0)
        self._last_graph_orientation: str | None = None
        self._last_depth = 10.0
        self._last_tools: list[ToolProfile] = []

        self.depth_var = tk.StringVar(value="10.0")
        self.speed_var = tk.StringVar(value="8.0")
        self.language_var = tk.StringVar(value=self.settings.language)
        self.custom_speed_limits_var = tk.BooleanVar(value=self.settings.custom_speed_limits_enabled)
        self.speed_min_var = tk.StringVar(value=f"{self.settings.speed_min_kmh:.1f}")
        self.speed_max_var = tk.StringVar(value=f"{self.settings.speed_max_kmh:.1f}")
        self.custom_depth_limits_var = tk.BooleanVar(value=self.settings.custom_depth_limits_enabled)
        self.depth_min_var = tk.StringVar(value=f"{self.settings.depth_min_cm:.1f}")
        self.depth_max_var = tk.StringVar(value=f"{self.settings.depth_max_cm:.1f}")
        self.speed_step_var = tk.StringVar(value=f"{self.settings.speed_step_kmh:.1f}")
        self.pretty_interface_var = tk.BooleanVar(value=self.settings.pretty_interface_enabled)
        self.tool_mode_var = tk.StringVar(value="builtin_compare")
        self.tool_mode_display_var = tk.StringVar()
        self.speed_mode_var = tk.StringVar(value="manual")
        self.speed_mode_display_var = tk.StringVar()
        self.first_tool_var = tk.StringVar(value="kps")
        self.second_tool_var = tk.StringVar(value="exp")

        self._build()
        self.refresh_texts()
        self.calculate()
        self._schedule_startup_changelog()

    @property
    def tools(self) -> dict[str, ToolProfile]:
        """Возвращает инструменты приложения словарём `id -> ToolProfile`."""
        return {tool.id: tool for tool in self.settings.all_tools()}

    def _build(self) -> None:
        """Создаёт все основные виджеты главного окна и связывает обработчики."""
        self.root.geometry("1180x720")
        self.root.minsize(760, 560)
        self._build_menu()

        self.parameters = ttk.LabelFrame(self.root)
        self.parameters.columnconfigure(1, weight=1)

        self.graphs = ttk.Frame(self.root)
        self.graphs.columnconfigure(0, weight=1)
        self.graphs.rowconfigure(0, weight=1)
        self.graphs.bind("<Configure>", self._schedule_graph_resize)

        self.results_panel = ttk.LabelFrame(self.root)
        self.results_panel.columnconfigure(0, weight=1)
        self.results_panel.rowconfigure(0, weight=1)

        self.depth_label = ttk.Label(self.parameters)
        self.depth_label.grid(row=0, column=0, sticky="w", padx=8, pady=5)
        ttk.Entry(self.parameters, textvariable=self.depth_var, width=12).grid(row=0, column=1, sticky="ew", padx=8, pady=5)

        self.depth_min_label = ttk.Label(self.parameters)
        self.depth_min_label.grid(row=1, column=0, sticky="w", padx=8, pady=5)
        self.depth_min_entry = ttk.Entry(self.parameters, textvariable=self.depth_min_var, width=12)
        self.depth_min_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=5)

        self.depth_max_label = ttk.Label(self.parameters)
        self.depth_max_label.grid(row=2, column=0, sticky="w", padx=8, pady=5)
        self.depth_max_entry = ttk.Entry(self.parameters, textvariable=self.depth_max_var, width=12)
        self.depth_max_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=5)

        self.tool_mode_label = ttk.Label(self.parameters)
        self.tool_mode_label.grid(row=3, column=0, sticky="w", padx=8, pady=5)
        self.tool_mode_combo = ttk.Combobox(self.parameters, state="readonly", textvariable=self.tool_mode_display_var)
        self.tool_mode_combo.grid(row=3, column=1, sticky="ew", padx=8, pady=5)
        self.tool_mode_combo.bind("<<ComboboxSelected>>", lambda _event: self._set_tool_mode_from_display())

        self.first_tool_label = ttk.Label(self.parameters)
        self.first_tool_label.grid(row=4, column=0, sticky="w", padx=8, pady=5)
        self.first_tool_combo = ttk.Combobox(self.parameters, state="readonly", textvariable=self.first_tool_var)
        self.first_tool_combo.grid(row=4, column=1, sticky="ew", padx=8, pady=5)

        self.second_tool_label = ttk.Label(self.parameters)
        self.second_tool_label.grid(row=5, column=0, sticky="w", padx=8, pady=5)
        self.second_tool_combo = ttk.Combobox(self.parameters, state="readonly", textvariable=self.second_tool_var)
        self.second_tool_combo.grid(row=5, column=1, sticky="ew", padx=8, pady=5)

        self.speed_mode_label = ttk.Label(self.parameters)
        self.speed_mode_label.grid(row=6, column=0, sticky="w", padx=8, pady=5)
        self.speed_mode_combo = ttk.Combobox(self.parameters, state="readonly", textvariable=self.speed_mode_display_var)
        self.speed_mode_combo.grid(row=6, column=1, sticky="ew", padx=8, pady=5)
        self.speed_mode_combo.bind("<<ComboboxSelected>>", lambda _event: self._set_speed_mode_from_display())

        self.speed_label = ttk.Label(self.parameters)
        self.speed_label.grid(row=7, column=0, sticky="w", padx=8, pady=5)
        self.speed_entry = ttk.Entry(self.parameters, textvariable=self.speed_var, width=12)
        self.speed_entry.grid(row=7, column=1, sticky="ew", padx=8, pady=5)

        self.speed_min_label = ttk.Label(self.parameters)
        self.speed_min_label.grid(row=8, column=0, sticky="w", padx=8, pady=5)
        self.speed_min_entry = ttk.Entry(self.parameters, textvariable=self.speed_min_var, width=12)
        self.speed_min_entry.grid(row=8, column=1, sticky="ew", padx=8, pady=5)

        self.speed_max_label = ttk.Label(self.parameters)
        self.speed_max_label.grid(row=9, column=0, sticky="w", padx=8, pady=5)
        self.speed_max_entry = ttk.Entry(self.parameters, textvariable=self.speed_max_var, width=12)
        self.speed_max_entry.grid(row=9, column=1, sticky="ew", padx=8, pady=5)

        self.calculate_button = ttk.Button(self.parameters, command=self.calculate)
        self.calculate_button.grid(row=10, column=0, columnspan=2, sticky="ew", padx=8, pady=(14, 5))

        self.results_text = tk.Text(self.results_panel, width=38, wrap="word")
        self.results_scrollbar = ttk.Scrollbar(self.results_panel, orient="vertical", command=self.results_text.yview)
        self.results_text.configure(yscrollcommand=self.results_scrollbar.set)
        self.results_text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.results_scrollbar.grid(row=0, column=1, sticky="ns", pady=6)
        self.results_text.configure(state="disabled")

        self._refresh_tool_options()
        self._init_graphs()
        self._apply_responsive_layout(self.root.winfo_width())
        self._update_speed_limit_controls()
        self._update_depth_limit_controls()
        self.root.bind("<Configure>", self._on_root_configure)

    def refresh_texts(self) -> None:
        """Обновляет все видимые подписи после смены языка или пересоздания меню."""
        t = self.localizer
        self.root.title(t("app.title"))
        self._build_menu()
        self.parameters.configure(text=t("panel.parameters"))
        self.results_panel.configure(text=t("panel.results"))
        self.depth_label.configure(text=t("depth"))
        self.depth_min_label.configure(text=t("depth_min"))
        self.depth_max_label.configure(text=t("depth_max"))
        self.tool_mode_label.configure(text=t("tool_mode"))
        self.first_tool_label.configure(text=t("first_tool"))
        self.second_tool_label.configure(text=t("second_tool"))
        self.speed_mode_label.configure(text=t("speed_mode"))
        self.speed_label.configure(text=t("speed"))
        self.speed_min_label.configure(text=t("speed_min"))
        self.speed_max_label.configure(text=t("speed_max"))
        self.calculate_button.configure(text=t("calculate"))

        tool_labels = self._tool_mode_labels()
        speed_labels = self._speed_mode_labels()
        self.tool_mode_combo.configure(values=tuple(tool_labels.values()))
        self.speed_mode_combo.configure(values=tuple(speed_labels.values()))
        self.tool_mode_display_var.set(tool_labels.get(self.tool_mode_var.get(), tool_labels["builtin_compare"]))
        self.speed_mode_display_var.set(speed_labels.get(self.speed_mode_var.get(), speed_labels["manual"]))
        self._update_tool_controls()
        self._update_speed_controls()
        self._update_speed_limit_controls()
        self._update_depth_limit_controls()
        self._apply_interface_style()

    def change_language(self, language: str | None = None) -> None:
        """Переключает язык интерфейса.

        language: код языка (`ru`, `en`). Если не передан, берётся из переменной меню.
        Сохраняет новый язык в настройках.
        """
        if language is not None:
            self.language_var.set(language)
        self.settings.language = self.language_var.get()
        self.localizer.set_language(self.settings.language)
        self.refresh_texts()
        self.calculate()
        save_settings(self.settings)

    def toggle_custom_speed_limits(self) -> None:
        """Включает или выключает пользовательские пороги скорости."""
        self.settings.custom_speed_limits_enabled = self.custom_speed_limits_var.get()
        if self.custom_speed_limits_var.get():
            messagebox.showwarning(self.localizer("warning"), self.localizer("custom_speed_limits_tz_warning"))
        self._update_speed_limit_controls()
        self.calculate()

    def toggle_custom_depth_limits(self) -> None:
        """Включает или выключает пользовательские пороги глубины обработки."""
        self.settings.custom_depth_limits_enabled = self.custom_depth_limits_var.get()
        if self.custom_depth_limits_var.get():
            messagebox.showwarning(self.localizer("warning"), self.localizer("custom_depth_limits_tz_warning"))
        self._update_depth_limit_controls()
        self.calculate()

    def configure_optimization_step(self) -> None:
        """Открывает диалог настройки шага перебора скоростей для оптимизации."""
        value = simpledialog.askfloat(
            self.localizer("speed_step"),
            self.localizer("speed_step_prompt"),
            parent=self.root,
            initialvalue=self.settings.speed_step_kmh,
            minvalue=0.000001,
        )
        if value is None:
            return
        speed_step, invalid = validate_speed_step(str(value))
        if invalid:
            messagebox.showwarning(self.localizer("warning"), self.localizer("speed_step_warning"))
            speed_step = 0.5
        self.speed_step_var.set(f"{speed_step:g}")
        self.settings.speed_step_kmh = speed_step
        save_settings(self.settings)
        self.calculate()

    def toggle_pretty_interface(self) -> None:
        """Включает или выключает улучшенное оформление интерфейса."""
        self.settings.pretty_interface_enabled = self.pretty_interface_var.get()
        self._apply_interface_style()
        save_settings(self.settings)
        self.calculate()

    def open_about(self) -> None:
        """Открывает адаптивное окно со сведениями о приложении."""
        about = AboutWindow(self, self.root)
        self._apply_plain_widget_style(about.window)

    def open_changelog(self, mark_seen: bool = False) -> None:
        """Открывает окно со встроенной историей изменений."""
        changelog = ChangelogWindow(self.localizer, self.root)
        self._apply_plain_widget_style(changelog.window)
        if mark_seen:
            self.settings.last_seen_changelog_version = __version__
            save_settings(self.settings)

    def _schedule_startup_changelog(self) -> None:
        if should_show_startup_changelog(self._config_existed_at_start, self.settings.last_seen_changelog_version):
            self.root.after_idle(lambda: self.open_changelog(mark_seen=True))

    def about_details(self) -> list[tuple[str, str]]:
        """Возвращает строки для окна «О приложении»."""
        return [
            (self.localizer("about.version"), __version__),
            (self.localizer("about.updates"), self.localizer("about.updates_checking")),
            (self.localizer("about.timestamp"), ""),
            (self.localizer("about.launch"), self._launch_description()),
            (self.localizer("about.license"), "MIT"),
            (self.localizer("about.author"), "alxprgs"),
        ]

    def _launch_description(self) -> str:
        """Определяет, запущено ли приложение из Python или собранного исполняемого файла."""
        executable = Path(sys.executable).name
        if getattr(sys, "frozen", False):
            return self.localizer("about.launch_frozen", executable=executable)
        return self.localizer(
            "about.launch_python",
            version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            executable=executable,
        )

    def calculate(self) -> None:
        """Выполняет полный расчёт по текущим данным интерфейса.

        Метод валидирует глубину, скорость и пороги, выбирает инструменты,
        запускает ручной расчёт или автооптимизацию, обновляет текст и графики.
        """
        depth_min, depth_max = self._depth_limits()
        depth_fallback = self._depth_fallback(depth_min, depth_max)
        depth, depth_warn = validate_depth(self.depth_var.get(), depth_min, depth_max, depth_fallback)
        self.depth_var.set(f"{depth:.1f}")
        if depth_warn:
            messagebox.showwarning(self.localizer("warning"), self.localizer("depth_warning"))

        selected_tools = self._selected_tools()
        speed_min, speed_max = self._speed_limits()
        speed_step = self._speed_step()
        if self.speed_mode_var.get() == "auto":
            optimization = optimize_speed(depth, selected_tools, start=speed_min, stop=speed_max, step=speed_step)
            speed = optimization.speed_kmh
            q_min = optimization.q_min
        else:
            fallback = self._speed_fallback(speed_min, speed_max)
            speed, speed_warn = validate_speed(self.speed_var.get(), speed_min, speed_max, fallback)
            self.speed_var.set(f"{speed:.1f}")
            if speed_warn:
                messagebox.showwarning(self.localizer("warning"), self.localizer("speed_warning"))
            q_min = None

        self._render_results(depth, speed, selected_tools, q_min)
        self._render_graphs(depth, selected_tools, speed_min, speed_max)
        save_settings(self.settings)

    def open_tool_manager(self) -> None:
        """Открывает отдельное окно управления пользовательскими инструментами."""
        manager = ToolManager(self, self.root)
        self._apply_plain_widget_style(manager.window)

    def import_config(self) -> None:
        """Импортирует настройки и инструменты из выбранного JSON-файла."""
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            imported = settings_from_json(Path(path).read_text(encoding="utf-8"))
        except (ConfigError, OSError, ValueError) as exc:
            messagebox.showerror(self.localizer("error"), str(exc))
            return
        self.settings = merge_imported_settings(self.settings, imported)
        self.language_var.set(self.settings.language)
        self.custom_speed_limits_var.set(self.settings.custom_speed_limits_enabled)
        self.speed_min_var.set(f"{self.settings.speed_min_kmh:.1f}")
        self.speed_max_var.set(f"{self.settings.speed_max_kmh:.1f}")
        self.custom_depth_limits_var.set(self.settings.custom_depth_limits_enabled)
        self.depth_min_var.set(f"{self.settings.depth_min_cm:.1f}")
        self.depth_max_var.set(f"{self.settings.depth_max_cm:.1f}")
        self.speed_step_var.set(f"{self.settings.speed_step_kmh:.1f}")
        self.pretty_interface_var.set(self.settings.pretty_interface_enabled)
        self.localizer.set_language(self.settings.language)
        self._refresh_tool_options()
        self.refresh_texts()
        self.calculate()
        messagebox.showinfo(self.localizer("info"), self.localizer("config_imported"))

    def export_config(self) -> None:
        """Экспортирует текущие настройки и пользовательские инструменты в JSON."""
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            Path(path).write_text(settings_to_json(self.settings), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror(self.localizer("error"), str(exc))
            return
        messagebox.showinfo(self.localizer("info"), self.localizer("config_exported"))

    def choose_config_location(self) -> None:
        """Позволяет выбрать постоянное место хранения основного config.json."""
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            move_settings_to_path(self.settings, Path(path))
        except OSError as exc:
            messagebox.showerror(self.localizer("error"), str(exc))
            return
        messagebox.showinfo(self.localizer("info"), self.localizer("config_location_changed"))

    def use_default_config_location(self) -> None:
        """Возвращает сохранение настроек в стандартный путь приложения."""
        try:
            move_settings_to_default_path(self.settings)
        except OSError as exc:
            messagebox.showerror(self.localizer("error"), str(exc))
            return
        messagebox.showinfo(self.localizer("info"), self.localizer("config_location_reset"))

    def _selected_tools(self) -> list[ToolProfile]:
        """Определяет список инструментов, выбранных текущим режимом расчёта."""
        tools = self.tools
        mode = self.tool_mode_var.get()
        if mode == "single":
            return [tools.get(self.first_tool_var.get(), tools["kps"])]
        if mode == "builtin_compare":
            return [tools["kps"], tools["exp"]]
        first = tools.get(self.first_tool_var.get(), tools["kps"])
        second = tools.get(self.second_tool_var.get(), tools["exp"])
        return [first, second]

    def _render_results(self, depth: float, speed: float, selected_tools: list[ToolProfile], q_min: float | None) -> None:
        """Записывает расчётные результаты в текстовую область.

        depth: глубина в см, speed: скорость в км/ч.
        selected_tools: инструменты, для которых выводятся показатели.
        q_min: минимальное q при автооптимизации или None в ручном режиме.
        """
        t = self.localizer
        lines = [
            "=" * 46,
            t("result_header"),
            "=" * 46,
            t("depth_line", value=depth),
            t("speed_line", value=speed),
            "",
            t("result_legend_header"),
            t("result_legend_force"),
            t("result_legend_resistance"),
            t("result_legend_power"),
            t("result_legend_fuel"),
            "",
        ]
        if q_min is not None:
            lines.append(t("optimal_line", speed=speed, q=q_min))

        for tool in selected_tools:
            force = force_at_depth(speed, depth, tool)
            q_value = specific_resistance(speed, depth, tool)
            power, fuel = power_and_fuel(speed, depth, tool)
            lines.append(t("tool_result", name=tool.name, force=force, q=q_value, power=power, fuel=fuel))

        if len(selected_tools) == 2:
            comparison = compare_tools(depth, speed, selected_tools[0], selected_tools[1])
            lines.append(t("better_line", name=comparison.better_tool.name, diff=comparison.difference_percent))

        self.results_text.configure(state="normal")
        self.results_text.delete("1.0", "end")
        self.results_text.insert("1.0", "\n".join(lines))
        self.results_text.configure(state="disabled")

    def _init_graphs(self) -> None:
        """Инициализирует matplotlib-графики внутри Tkinter-контейнера."""
        for child in self.graphs.winfo_children():
            child.destroy()
        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
        except ModuleNotFoundError:
            ttk.Label(self.graphs, text=self.localizer("matplotlib_missing"), wraplength=460).grid(row=0, column=0, padx=12, pady=12)
            return

        palette = self._interface_palette()
        self.figure = Figure(figsize=(7.2, 5.2), dpi=100, facecolor=palette["figure"])
        self.graph_canvas = FigureCanvasTkAgg(self.figure, master=self.graphs)
        graph_widget = self.graph_canvas.get_tk_widget()
        graph_widget.configure(background=palette["figure"])
        graph_widget.grid(row=0, column=0, sticky="nsew")

    def _render_graphs(
        self,
        depth: float,
        selected_tools: list[ToolProfile],
        speed_min: float | None = None,
        speed_max: float | None = None,
    ) -> None:
        """Перерисовывает графики F(V) и q(V).

        depth: текущая глубина в см.
        selected_tools: инструменты для отображения.
        speed_min и speed_max: границы диапазона скоростей на графиках.
        """
        self._last_depth = depth
        self._last_tools = selected_tools
        if self.figure is None or self.graph_canvas is None:
            return
        self.figure.clear()
        canvas_width = self.graph_canvas.get_tk_widget().winfo_width()
        orientation = "vertical" if canvas_width and canvas_width < 620 else "horizontal"
        self._last_graph_orientation = orientation
        if orientation == "vertical":
            force_axis = self.figure.add_subplot(2, 1, 1)
            q_axis = self.figure.add_subplot(2, 1, 2)
        else:
            force_axis = self.figure.add_subplot(1, 2, 1)
            q_axis = self.figure.add_subplot(1, 2, 2)
        start = 5.0 if speed_min is None else speed_min
        stop = 12.0 if speed_max is None else speed_max
        speeds = plot_speed_grid(start=start, stop=stop, step=0.2)
        for tool in self._graph_tools(selected_tools):
            force_values = [force_at_depth(speed, depth, tool) for speed in speeds]
            q_values = [specific_resistance(speed, depth, tool) for speed in speeds]
            force_axis.plot(speeds, force_values, color=tool.color, linestyle=tool.line_style, label=tool.name)
            q_axis.plot(speeds, q_values, color=tool.color, linestyle="--", label=tool.name)

        force_axis.set_title(self.localizer("force_title", depth=depth))
        force_axis.set_xlabel(self.localizer("axis_speed"))
        force_axis.set_ylabel(self.localizer("axis_force"))
        force_axis.grid(True)
        force_axis.legend()

        q_axis.set_title(self.localizer("resistance_title", depth=depth))
        q_axis.set_xlabel(self.localizer("axis_speed"))
        q_axis.set_ylabel(self.localizer("axis_resistance"))
        q_axis.grid(True)
        q_axis.legend()
        self._style_graph_figure()
        self.figure.tight_layout()
        self.graph_canvas.draw_idle()

    def _graph_tools(self, selected_tools: list[ToolProfile]) -> list[ToolProfile]:
        """Возвращает инструменты для графиков с обязательными лапами из ТЗ."""
        tools_by_id: dict[str, ToolProfile] = {}
        for tool_id in ("kps", "exp"):
            tools_by_id[tool_id] = BUILTIN_TOOLS[tool_id]
        for tool in selected_tools:
            tools_by_id.setdefault(tool.id, tool)
        return list(tools_by_id.values())

    def _refresh_tool_options(self) -> None:
        """Обновляет списки выбора инструментов в комбобоксах."""
        values = tuple(self.tools.keys())
        self.first_tool_combo.configure(values=values)
        self.second_tool_combo.configure(values=values)
        if self.first_tool_var.get() not in values:
            self.first_tool_var.set(values[0])
        if self.second_tool_var.get() not in values:
            self.second_tool_var.set(values[1] if len(values) > 1 else values[0])

    def _update_tool_controls(self) -> None:
        """Включает или отключает поля выбора инструмента по режиму сравнения."""
        mode = self.tool_mode_var.get()
        second_state = "readonly" if mode == "custom_compare" else "disabled"
        first_state = "readonly" if mode in {"single", "custom_compare"} else "disabled"
        self.first_tool_combo.configure(state=first_state)
        self.second_tool_combo.configure(state=second_state)

    def _update_speed_controls(self) -> None:
        """Включает ручной ввод скорости только в ручном режиме расчёта."""
        state = "normal" if self.speed_mode_var.get() == "manual" else "disabled"
        self.speed_entry.configure(state=state)

    def _update_speed_limit_controls(self) -> None:
        """Показывает или скрывает поля пользовательских границ скорости."""
        if self.custom_speed_limits_var.get():
            self.speed_min_label.grid()
            self.speed_min_entry.grid()
            self.speed_max_label.grid()
            self.speed_max_entry.grid()
        else:
            self.speed_min_label.grid_remove()
            self.speed_min_entry.grid_remove()
            self.speed_max_label.grid_remove()
            self.speed_max_entry.grid_remove()

    def _update_depth_limit_controls(self) -> None:
        """Показывает или скрывает поля пользовательских границ глубины."""
        if self.custom_depth_limits_var.get():
            self.depth_min_label.grid()
            self.depth_min_entry.grid()
            self.depth_max_label.grid()
            self.depth_max_entry.grid()
        else:
            self.depth_min_label.grid_remove()
            self.depth_min_entry.grid_remove()
            self.depth_max_label.grid_remove()
            self.depth_max_entry.grid_remove()

    def _tool_mode_labels(self) -> dict[str, str]:
        """Возвращает локализованные подписи режимов выбора инструментов."""
        return {
            "single": self.localizer("tool_single"),
            "builtin_compare": self.localizer("tool_builtin_compare"),
            "custom_compare": self.localizer("tool_custom_compare"),
        }

    def _speed_mode_labels(self) -> dict[str, str]:
        """Возвращает локализованные подписи режимов скорости."""
        return {
            "manual": self.localizer("manual_speed"),
            "auto": self.localizer("auto_speed"),
        }

    def _set_tool_mode_from_display(self) -> None:
        """Преобразует видимую подпись режима инструмента во внутренний код."""
        labels = self._tool_mode_labels()
        reverse = {label: code for code, label in labels.items()}
        self.tool_mode_var.set(reverse.get(self.tool_mode_display_var.get(), "builtin_compare"))
        self._update_tool_controls()

    def _set_speed_mode_from_display(self) -> None:
        """Преобразует видимую подпись режима скорости во внутренний код."""
        labels = self._speed_mode_labels()
        reverse = {label: code for code, label in labels.items()}
        self.speed_mode_var.set(reverse.get(self.speed_mode_display_var.get(), "manual"))
        self._update_speed_controls()

    def _interface_palette(self) -> dict[str, str]:
        if self.pretty_interface_var.get():
            return {
                "window": "#edf3ee",
                "panel": "#f8fbf7",
                "field": "#ffffff",
                "foreground": "#24322b",
                "muted": "#5f7168",
                "accent": "#2f6f4f",
                "accent_hover": "#24583f",
                "select": "#b8d8c4",
                "grid": "#d5dfd7",
                "figure": "#f4f8f3",
                "axes": "#ffffff",
            }
        return {
            "window": "#f0f0f0",
            "panel": "#f0f0f0",
            "field": "#ffffff",
            "foreground": "#000000",
            "muted": "#444444",
            "accent": "#e1e1e1",
            "accent_hover": "#d5d5d5",
            "select": "#c7ddf2",
            "grid": "#d9d9d9",
            "figure": "#ffffff",
            "axes": "#ffffff",
        }

    def _apply_interface_style(self) -> None:
        enabled = self.pretty_interface_var.get()
        if enabled and "clam" in self.ttk_style.theme_names():
            self.ttk_style.theme_use("clam")
        else:
            self.ttk_style.theme_use(self._default_theme)

        palette = self._interface_palette()
        if enabled:
            self.ttk_style.configure("TFrame", background=palette["window"])
            self.ttk_style.configure("TLabelframe", background=palette["panel"], bordercolor=palette["grid"], relief="solid")
            self.ttk_style.configure(
                "TLabelframe.Label",
                background=palette["panel"],
                foreground=palette["accent"],
                font=("Segoe UI", 10, "bold"),
            )
            self.ttk_style.configure("TLabel", background=palette["window"], foreground=palette["foreground"])
            self.ttk_style.configure(
                "TButton",
                background=palette["accent"],
                foreground="#ffffff",
                borderwidth=1,
                focusthickness=2,
                focuscolor=palette["select"],
                padding=(10, 6),
            )
            self.ttk_style.map(
                "TButton",
                background=[("active", palette["accent_hover"]), ("disabled", palette["grid"])],
                foreground=[("disabled", palette["muted"])],
            )
            self.ttk_style.configure("TEntry", fieldbackground=palette["field"], foreground=palette["foreground"], padding=4)
            self.ttk_style.configure(
                "TCombobox",
                fieldbackground=palette["field"],
                foreground=palette["foreground"],
                arrowcolor=palette["accent"],
                padding=4,
            )
            self.ttk_style.configure("TCheckbutton", background=palette["window"], foreground=palette["foreground"])
            self.ttk_style.configure("TRadiobutton", background=palette["window"], foreground=palette["foreground"])
        else:
            for style_name, options in self._default_style_options.items():
                if options:
                    self.ttk_style.configure(style_name, **options)
            for style_name, mappings in self._default_style_maps.items():
                if mappings:
                    self.ttk_style.map(style_name, **mappings)

        self._apply_plain_widget_style(self.root)
        self._apply_menu_style()
        if self.graph_canvas is not None:
            self.graph_canvas.get_tk_widget().configure(background=palette["figure"])
        self._style_graph_figure()

    def _apply_plain_widget_style(self, widget: tk.Widget) -> None:
        palette = self._interface_palette()
        enabled = self.pretty_interface_var.get()
        if isinstance(widget, (tk.Tk, tk.Toplevel, tk.Frame)):
            widget.configure(background=palette["window"])
        elif isinstance(widget, tk.Text):
            widget.configure(
                background=palette["field"],
                foreground=palette["foreground"],
                insertbackground=palette["foreground"],
                selectbackground=palette["select"],
                relief="flat" if enabled else "sunken",
                borderwidth=1,
                padx=8 if enabled else 1,
                pady=8 if enabled else 1,
            )
        elif isinstance(widget, tk.Listbox):
            widget.configure(
                background=palette["field"],
                foreground=palette["foreground"],
                selectbackground=palette["select"],
                selectforeground=palette["foreground"],
                relief="flat" if enabled else "sunken",
                borderwidth=1,
                highlightthickness=1 if enabled else 0,
                highlightbackground=palette["grid"],
            )

        for child in widget.winfo_children():
            self._apply_plain_widget_style(child)

    def _apply_menu_style(self) -> None:
        palette = self._interface_palette()
        for menu in self._menus:
            try:
                menu.configure(
                    background=palette["panel"],
                    foreground=palette["foreground"],
                    activebackground=palette["select"],
                    activeforeground=palette["foreground"],
                    borderwidth=0 if self.pretty_interface_var.get() else 1,
                )
            except tk.TclError:
                continue

    def _style_graph_figure(self) -> None:
        if self.figure is None:
            return
        palette = self._interface_palette()
        self.figure.set_facecolor(palette["figure"])
        for axis in self.figure.axes:
            axis.set_facecolor(palette["axes"])
            axis.tick_params(colors=palette["muted"])
            axis.xaxis.label.set_color(palette["foreground"])
            axis.yaxis.label.set_color(palette["foreground"])
            axis.title.set_color(palette["foreground"])
            for spine in axis.spines.values():
                spine.set_color(palette["grid"])
            axis.grid(True, color=palette["grid"], linewidth=0.8)
            legend = axis.get_legend()
            if legend is not None:
                legend.get_frame().set_facecolor(palette["field"])
                legend.get_frame().set_edgecolor(palette["grid"])
                for text in legend.get_texts():
                    text.set_color(palette["foreground"])

    def _build_menu(self) -> None:
        """Создаёт верхнее меню приложения и привязывает команды."""
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label=self.localizer("import_config"), command=self.import_config)
        file_menu.add_command(label=self.localizer("export_config"), command=self.export_config)
        file_menu.add_separator()
        file_menu.add_command(label=self.localizer("config_change_location"), command=self.choose_config_location)
        file_menu.add_command(label=self.localizer("config_use_default_location"), command=self.use_default_config_location)
        file_menu.add_separator()
        file_menu.add_command(label=self.localizer("changelog.title"), command=self.open_changelog)
        file_menu.add_separator()
        file_menu.add_command(label=self.localizer("about.title"), command=self.open_about)
        file_menu.add_separator()
        file_menu.add_command(label=self.localizer("exit"), command=self.root.destroy)

        tools_menu = tk.Menu(menu, tearoff=False)
        tools_menu.add_command(label=self.localizer("manage_tools"), command=self.open_tool_manager)

        settings_menu = tk.Menu(menu, tearoff=False)
        language_menu = tk.Menu(settings_menu, tearoff=False)
        language_menu.add_radiobutton(label=self.localizer("language_ru"), variable=self.language_var, value="ru", command=lambda: self.change_language("ru"))
        language_menu.add_radiobutton(label=self.localizer("language_en"), variable=self.language_var, value="en", command=lambda: self.change_language("en"))
        settings_menu.add_cascade(label=self.localizer("language"), menu=language_menu)
        settings_menu.add_checkbutton(
            label=self.localizer("custom_speed_limits"),
            variable=self.custom_speed_limits_var,
            command=self.toggle_custom_speed_limits,
        )
        settings_menu.add_checkbutton(
            label=self.localizer("custom_depth_limits"),
            variable=self.custom_depth_limits_var,
            command=self.toggle_custom_depth_limits,
        )
        settings_menu.add_checkbutton(
            label=self.localizer("pretty_interface"),
            variable=self.pretty_interface_var,
            command=self.toggle_pretty_interface,
        )
        settings_menu.add_command(label=self.localizer("speed_step"), command=self.configure_optimization_step)

        self.menu_labels = (
            self.localizer("menu_file"),
            self.localizer("menu_tools"),
            self.localizer("menu_settings"),
        )
        menu.add_cascade(label=self.menu_labels[0], menu=file_menu)
        menu.add_cascade(label=self.menu_labels[1], menu=tools_menu)
        menu.add_cascade(label=self.menu_labels[2], menu=settings_menu)
        self.file_menu = file_menu
        self.settings_menu = settings_menu
        self.main_menu = menu
        self._menus = [menu, file_menu, tools_menu, settings_menu, language_menu]
        self.root.configure(menu=menu)

    def _speed_limits(self) -> tuple[float, float]:
        """Возвращает активные границы скорости и синхронизирует их с настройками."""
        if not self.custom_speed_limits_var.get():
            self.settings.custom_speed_limits_enabled = False
            self.settings.speed_min_kmh = 5.0
            self.settings.speed_max_kmh = 12.0
            self.speed_min_var.set("5.0")
            self.speed_max_var.set("12.0")
            return 5.0, 12.0

        speed_min, speed_max, invalid = validate_speed_limits(self.speed_min_var.get(), self.speed_max_var.get())
        if invalid:
            messagebox.showwarning(self.localizer("warning"), self.localizer("speed_limits_warning"))
            self.custom_speed_limits_var.set(False)
            self.settings.custom_speed_limits_enabled = False
            self.speed_min_var.set("5.0")
            self.speed_max_var.set("12.0")
            self._update_speed_limit_controls()
            return 5.0, 12.0

        self.settings.custom_speed_limits_enabled = True
        self.settings.speed_min_kmh = speed_min
        self.settings.speed_max_kmh = speed_max
        return speed_min, speed_max

    def _speed_fallback(self, speed_min: float, speed_max: float) -> float:
        """Возвращает запасное значение скорости при неверном вводе."""
        if self.custom_speed_limits_var.get():
            return (speed_min + speed_max) / 2
        return 8.0

    def _depth_limits(self) -> tuple[float, float]:
        """Возвращает активные границы глубины и синхронизирует их с настройками."""
        if not self.custom_depth_limits_var.get():
            self.settings.custom_depth_limits_enabled = False
            self.settings.depth_min_cm = 5.0
            self.settings.depth_max_cm = 20.0
            self.depth_min_var.set("5.0")
            self.depth_max_var.set("20.0")
            return 5.0, 20.0

        depth_min, depth_max, invalid = validate_depth_limits(self.depth_min_var.get(), self.depth_max_var.get())
        if invalid:
            messagebox.showwarning(self.localizer("warning"), self.localizer("depth_limits_warning"))
            self.custom_depth_limits_var.set(False)
            self.settings.custom_depth_limits_enabled = False
            self.depth_min_var.set("5.0")
            self.depth_max_var.set("20.0")
            self._update_depth_limit_controls()
            return 5.0, 20.0

        self.settings.custom_depth_limits_enabled = True
        self.settings.depth_min_cm = depth_min
        self.settings.depth_max_cm = depth_max
        return depth_min, depth_max

    def _depth_fallback(self, depth_min: float, depth_max: float) -> float:
        """Возвращает запасное значение глубины при неверном вводе."""
        if self.custom_depth_limits_var.get():
            return (depth_min + depth_max) / 2
        return 10.0

    def _speed_step(self) -> float:
        """Возвращает шаг перебора скоростей и сохраняет его в настройках."""
        speed_step, invalid = validate_speed_step(self.speed_step_var.get())
        if invalid:
            messagebox.showwarning(self.localizer("warning"), self.localizer("speed_step_warning"))
            self.speed_step_var.set("0.5")
        self.settings.speed_step_kmh = speed_step
        return speed_step

    def _on_root_configure(self, event: tk.Event) -> None:
        """Обрабатывает изменение размера главного окна."""
        if event.widget is self.root:
            self._schedule_responsive_layout(event.width)

    def _schedule_responsive_layout(self, width: int) -> None:
        """Откладывает перестройку раскладки, чтобы resize не лагал."""
        if self._layout_resize_job is not None:
            self.root.after_cancel(self._layout_resize_job)
        self._layout_resize_job = self.root.after(LAYOUT_SETTLE_MS, lambda: self._run_responsive_layout(width))

    def _run_responsive_layout(self, width: int) -> None:
        """Запускает отложенную перестройку раскладки главного окна."""
        self._layout_resize_job = None
        self._apply_responsive_layout(width)

    def _apply_responsive_layout(self, width: int) -> None:
        """Переключает главное окно между широкой и узкой компоновкой."""
        mode = "wide" if width >= 1000 else "narrow"
        if mode == self._layout_mode:
            return
        self._layout_mode = mode
        for index in range(3):
            self.root.columnconfigure(index, weight=0)
            self.root.rowconfigure(index, weight=0)
        self.parameters.grid_forget()
        self.graphs.grid_forget()
        self.results_panel.grid_forget()

        if mode == "wide":
            self.root.columnconfigure(0, weight=0)
            self.root.columnconfigure(1, weight=1)
            self.root.columnconfigure(2, weight=0)
            self.root.rowconfigure(0, weight=1)
            self.parameters.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
            self.graphs.grid(row=0, column=1, sticky="nsew", padx=4, pady=8)
            self.results_panel.grid(row=0, column=2, sticky="nsew", padx=8, pady=8)
        else:
            self.root.columnconfigure(0, weight=1)
            self.root.rowconfigure(0, weight=0)
            self.root.rowconfigure(1, weight=1)
            self.root.rowconfigure(2, weight=1)
            self.parameters.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
            self.graphs.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
            self.results_panel.grid(row=2, column=0, sticky="nsew", padx=8, pady=6)

    def _schedule_graph_resize(self, event: tk.Event) -> None:
        """Откладывает тяжёлую перерисовку графиков после изменения размера."""
        if self.figure is None or self.graph_canvas is None:
            return
        width = int(event.width)
        height = int(event.height)
        if width <= 1 or height <= 1:
            return
        current_orientation = "vertical" if width < 620 else "horizontal"
        if self._last_graph_size == (width, height) and self._last_graph_orientation == current_orientation:
            return
        if self._graph_resize_job is not None:
            self.root.after_cancel(self._graph_resize_job)
        self._graph_resize_job = self.root.after(RESIZE_SETTLE_MS, lambda: self._resize_graphs(width, height))

    def _resize_graphs(self, width: int, height: int) -> None:
        """Меняет размер Figure и перерисовывает графики после стабилизации окна."""
        self._graph_resize_job = None
        if self.figure is None or self.graph_canvas is None or width <= 1 or height <= 1:
            return
        current_orientation = "vertical" if width < 620 else "horizontal"
        if self._last_graph_size == (width, height) and self._last_graph_orientation == current_orientation:
            return
        self._last_graph_size = (width, height)
        dpi = self.figure.get_dpi()
        self.figure.set_size_inches(max(width / dpi, 1), max(height / dpi, 1), forward=False)
        speed_min, speed_max = self._current_speed_limits_for_resize()
        self._render_graphs(self._last_depth, self._last_tools or self._selected_tools(), speed_min, speed_max)

    def _current_speed_limits_for_resize(self) -> tuple[float, float]:
        """Возвращает границы скорости для resize без показа предупреждений."""
        if not self.custom_speed_limits_var.get():
            return 5.0, 12.0
        speed_min, speed_max, invalid = validate_speed_limits(self.speed_min_var.get(), self.speed_max_var.get())
        if invalid:
            return 5.0, 12.0
        return speed_min, speed_max


class ChangelogWindow:
    """Окно со встроенной историей релизов."""

    def __init__(self, localizer: Localizer, master: tk.Tk | tk.Toplevel) -> None:
        self.localizer = localizer
        self.window = tk.Toplevel(master)
        self.window.title(self.localizer("changelog.title"))
        self.window.geometry("720x480")
        self.window.minsize(420, 300)
        self.window.transient(master)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        self.title_label = ttk.Label(self.window, text=self.localizer("changelog.title"), font=("TkDefaultFont", 12, "bold"))
        self.title_label.grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(12, 4))

        self.text = tk.Text(self.window, wrap="word", height=18)
        self.scrollbar = ttk.Scrollbar(self.window, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=self.scrollbar.set)
        self.text.grid(row=1, column=0, sticky="nsew", padx=(12, 0), pady=8)
        self.scrollbar.grid(row=1, column=1, sticky="ns", padx=(0, 12), pady=8)

        self.close_button = ttk.Button(self.window, text=self.localizer("tools.close"), command=self.window.destroy)
        self.close_button.grid(row=2, column=0, columnspan=2, sticky="e", padx=12, pady=(0, 12))

        self.text.insert("1.0", format_changelog(load_changelog_entries(), self.localizer))
        self.text.configure(state="disabled")
        self._center_on_screen()
        self.window.focus_set()

    def _center_on_screen(self) -> None:
        self.window.update_idletasks()
        width = self.window.winfo_width()
        height = self.window.winfo_height()
        x = max(0, (self.window.winfo_screenwidth() - width) // 2)
        y = max(0, (self.window.winfo_screenheight() - height) // 2)
        self.window.geometry(f"{width}x{height}+{x}+{y}")


class AboutWindow:
    """Адаптивное окно со сведениями о приложении."""

    def __init__(self, app: MainWindow, master: tk.Tk, check_updates: bool = True) -> None:
        self.app = app
        self.localizer = app.localizer
        self.window = tk.Toplevel(master)
        self.window.title(self.localizer("about.title"))
        self.window.geometry("560x315")
        self.window.minsize(320, 260)
        self.window.transient(master)

        self._layout_mode: str | None = None
        self._timestamp_job: str | None = None
        self.rows: list[tuple[ttk.Label, tk.Widget]] = []
        self.update_var = tk.StringVar(value=self.localizer("about.updates_checking"))
        self.timestamp_var = tk.StringVar(value=self._timestamp_text())
        self.update_url: str | None = None

        self.container = ttk.Frame(self.window, padding=(16, 14))
        self.container.columnconfigure(0, weight=1)
        self.container.columnconfigure(1, weight=2)

        self.title_label = ttk.Label(self.container, text=self.localizer("app.title"), font=("TkDefaultFont", 12, "bold"))
        self.subtitle_label = ttk.Label(self.container, text=self.localizer("about.subtitle"), wraplength=480)

        for label_text, value_text in app.about_details():
            label = ttk.Label(self.container, text=label_text)
            if label_text == self.localizer("about.updates"):
                value = ttk.Label(self.container, textvariable=self.update_var, wraplength=320, justify="left")
            elif label_text == self.localizer("about.timestamp"):
                value = ttk.Label(self.container, textvariable=self.timestamp_var, wraplength=320, justify="left")
            elif label_text == self.localizer("about.license"):
                value = ttk.Button(self.container, text=value_text, command=self.open_license)
            else:
                value = ttk.Label(self.container, text=value_text, wraplength=320, justify="left")
            self.rows.append((label, value))

        self.close_button = ttk.Button(self.container, text=self.localizer("tools.close"), command=self.destroy)

        self._apply_responsive_layout(560)
        self._center_on_screen()
        self._schedule_timestamp_refresh()
        self.window.protocol("WM_DELETE_WINDOW", self.destroy)
        self.window.bind("<Configure>", self._on_configure)
        self.window.focus_set()
        if check_updates:
            self.check_updates()

    def destroy(self) -> None:
        if self._timestamp_job is not None:
            try:
                self.window.after_cancel(self._timestamp_job)
            except tk.TclError:
                pass
            self._timestamp_job = None
        self.window.destroy()

    def _center_on_screen(self) -> None:
        self.window.update_idletasks()
        width = self.window.winfo_width()
        height = self.window.winfo_height()
        x = max(0, (self.window.winfo_screenwidth() - width) // 2)
        y = max(0, (self.window.winfo_screenheight() - height) // 2)
        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def _timestamp_text(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

    def _schedule_timestamp_refresh(self) -> None:
        self.timestamp_var.set(self._timestamp_text())
        self._timestamp_job = self.window.after(1000, self._schedule_timestamp_refresh)

    def check_updates(self) -> None:
        thread = threading.Thread(target=self._check_updates_in_background, daemon=True)
        thread.start()

    def _check_updates_in_background(self) -> None:
        try:
            latest_tag, release_url = fetch_latest_release()
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
            self._schedule_update_status(self.localizer("about.updates_error", message=str(exc)), None)
            return

        if is_newer_version(latest_tag, __version__):
            text = self.localizer("about.updates_available", version=latest_tag)
            self._schedule_update_status(text, release_url)
        else:
            self._schedule_update_status(self.localizer("about.updates_current"), release_url)

    def _schedule_update_status(self, text: str, url: str | None) -> None:
        try:
            self.window.after(0, lambda: self._set_update_status(text, url))
        except tk.TclError:
            return

    def _set_update_status(self, text: str, url: str | None) -> None:
        self.update_var.set(text)
        self.update_url = url

    def open_license(self) -> None:
        LicenseWindow(self.localizer, self.window)

    def _on_configure(self, event: tk.Event) -> None:
        if event.widget is self.window:
            self._apply_responsive_layout(event.width)

    def _apply_responsive_layout(self, width: int) -> None:
        mode = "wide" if width >= ABOUT_BREAKPOINT else "narrow"
        if mode == self._layout_mode:
            self._update_wrap(width)
            return
        self._layout_mode = mode

        self.container.grid_forget()
        for child in self.container.winfo_children():
            child.grid_forget()

        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        self.container.grid(row=0, column=0, sticky="nsew")
        self.title_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.subtitle_label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        row = 2
        if mode == "wide":
            self.container.columnconfigure(0, weight=0)
            self.container.columnconfigure(1, weight=1)
            for label, value in self.rows:
                label.grid(row=row, column=0, sticky="nw", padx=(0, 14), pady=3)
                value.grid(row=row, column=1, sticky="ew", pady=3)
                row += 1
        else:
            self.container.columnconfigure(0, weight=1)
            self.container.columnconfigure(1, weight=0)
            for label, value in self.rows:
                label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(5, 1))
                value.grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(0, 2))
                row += 2

        self.close_button.grid(row=row, column=0, columnspan=2, sticky="e", pady=(10, 0))
        self._update_wrap(width)

    def _update_wrap(self, width: int) -> None:
        wrap = max(240, min(520, width - 48))
        self.subtitle_label.configure(wraplength=wrap)
        value_wrap = max(220, min(360, width - 190 if self._layout_mode == "wide" else width - 48))
        for _label, value in self.rows:
            if isinstance(value, ttk.Label):
                value.configure(wraplength=value_wrap)


class LicenseWindow:
    """Окно с текстом MIT-лицензии."""

    def __init__(self, localizer: Localizer, master: tk.Toplevel) -> None:
        self.localizer = localizer
        self.window = tk.Toplevel(master)
        self.window.title(self.localizer("about.license_title"))
        self.window.geometry("640x420")
        self.window.minsize(360, 260)
        self.window.transient(master)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)

        self.text = tk.Text(self.window, wrap="word", height=16)
        self.scrollbar = ttk.Scrollbar(self.window, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=self.scrollbar.set)
        self.text.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)
        self.scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=10)
        self.close_button = ttk.Button(self.window, text=self.localizer("tools.close"), command=self.window.destroy)
        self.close_button.grid(row=1, column=0, columnspan=2, sticky="e", padx=10, pady=(0, 10))

        self.text.insert("1.0", self._license_text())
        self.text.configure(state="disabled")
        self.window.focus_set()

    def _license_text(self) -> str:
        try:
            return resources.files("soil_tiller_calculator").joinpath("LICENSE.txt").read_text(encoding="utf-8")
        except OSError:
            return self.localizer("about.license_unavailable")


class ToolManager:
    """Окно управления пользовательскими инструментами.

    Позволяет добавить, дублировать, удалить и сохранить профиль инструмента.
    Также адаптирует расположение списка, формы и кнопок под размер окна.
    """

    def __init__(self, app: MainWindow, master: tk.Tk) -> None:
        """Создаёт окно управления инструментами.

        app: главное окно, через которое доступны настройки и список инструментов.
        master: родительское Tk-окно.
        """
        self.app = app
        self.localizer = app.localizer
        self.window = tk.Toplevel(master)
        self.window.title(self.localizer("tools.title"))
        self.window.geometry("760x520")
        self.window.minsize(520, 420)

        self.selected_id: str | None = None
        self._layout_mode: str | None = None
        self.id_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.width_var = tk.StringVar()
        self.depth_var = tk.StringVar()
        self.color_var = tk.StringVar()
        self.style_var = tk.StringVar(value="-")
        self.field_rows: list[tuple[ttk.Label, ttk.Entry]] = []
        self.buttons: list[ttk.Button] = []

        self.list_frame = ttk.Frame(self.window)
        self.list_frame.columnconfigure(0, weight=1)
        self.list_frame.rowconfigure(0, weight=1)
        self.listbox = tk.Listbox(self.list_frame, width=28, height=10)
        self.list_scrollbar = ttk.Scrollbar(self.list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=self.list_scrollbar.set)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        self.list_scrollbar.grid(row=0, column=1, sticky="ns")
        self.listbox.bind("<<ListboxSelect>>", lambda _event: self.load_selected())

        self.form_frame = ttk.Frame(self.window)
        self.form_frame.columnconfigure(1, weight=1)
        self._add_row(0, "tools.id", self.id_var)
        self._add_row(1, "tools.name", self.name_var)
        self._add_row(2, "tools.width", self.width_var)
        self._add_row(3, "tools.depth", self.depth_var)
        self._add_row(4, "tools.color", self.color_var)
        self._add_row(5, "tools.style", self.style_var)

        self.points_label = ttk.Label(self.form_frame, text=self.localizer("tools.points"))
        self.points_label.grid(row=6, column=0, columnspan=2, sticky="w", padx=4, pady=(8, 2))
        self.points_text = tk.Text(self.form_frame, height=7, wrap="none")
        self.points_text.grid(row=7, column=0, columnspan=2, sticky="nsew", padx=4, pady=2)
        self.form_frame.rowconfigure(7, weight=1)

        self.buttons_frame = ttk.Frame(self.window)
        self.buttons = [
            ttk.Button(self.buttons_frame, text=self.localizer("tools.add"), command=self.add_tool),
            ttk.Button(self.buttons_frame, text=self.localizer("tools.duplicate"), command=self.duplicate_tool),
            ttk.Button(self.buttons_frame, text=self.localizer("tools.delete"), command=self.delete_tool),
            ttk.Button(self.buttons_frame, text=self.localizer("tools.save"), command=self.save_tool),
            ttk.Button(self.buttons_frame, text=self.localizer("tools.close"), command=self.window.destroy),
        ]

        self.note = ttk.Label(self.window, text=self.localizer("tools.builtin_note"), wraplength=460)

        self._apply_responsive_layout(760)
        self.window.bind("<Configure>", self._on_configure)
        self.refresh_list()

    def _add_row(self, row: int, key: str, variable: tk.StringVar) -> None:
        """Добавляет строку формы с подписью и полем ввода."""
        label = ttk.Label(self.form_frame, text=self.localizer(key))
        entry = ttk.Entry(self.form_frame, textvariable=variable)
        label.grid(row=row, column=0, sticky="w", padx=4, pady=(8, 2))
        entry.grid(row=row, column=1, sticky="ew", padx=4, pady=(8, 2))
        self.field_rows.append((label, entry))

    def _on_configure(self, event: tk.Event) -> None:
        """Обрабатывает изменение размера окна инструментов."""
        if event.widget is self.window:
            self._apply_responsive_layout(event.width)

    def _apply_responsive_layout(self, width: int) -> None:
        """Переключает окно инструментов между широкой и узкой компоновкой."""
        mode = "wide" if width >= TOOL_MANAGER_BREAKPOINT else "narrow"
        if mode == self._layout_mode:
            self._update_note_wrap(width)
            return
        self._layout_mode = mode

        self.list_frame.grid_forget()
        self.form_frame.grid_forget()
        self.buttons_frame.grid_forget()
        self.note.grid_forget()
        for index in range(4):
            self.window.columnconfigure(index, weight=0)
            self.window.rowconfigure(index, weight=0)
        self._layout_buttons(mode)

        if mode == "wide":
            self.window.columnconfigure(0, weight=0, minsize=220)
            self.window.columnconfigure(1, weight=1)
            self.window.rowconfigure(0, weight=1)
            self.list_frame.grid(row=0, column=0, rowspan=3, sticky="nsew", padx=(8, 4), pady=8)
            self.form_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=(8, 2))
            self.buttons_frame.grid(row=1, column=1, sticky="ew", padx=(4, 8), pady=6)
            self.note.grid(row=2, column=1, sticky="ew", padx=(4, 8), pady=(2, 8))
        else:
            self.window.columnconfigure(0, weight=1)
            self.window.rowconfigure(0, weight=1)
            self.window.rowconfigure(1, weight=3)
            self.list_frame.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
            self.form_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
            self.buttons_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
            self.note.grid(row=3, column=0, sticky="ew", padx=8, pady=(4, 8))
        self._update_note_wrap(width)

    def _layout_buttons(self, mode: str) -> None:
        """Раскладывает кнопки в одну строку или в несколько строк."""
        for child in self.buttons_frame.winfo_children():
            child.grid_forget()
        columns = 5 if mode == "wide" else 2
        for index in range(5):
            self.buttons_frame.columnconfigure(index, weight=0)
        for index, button in enumerate(self.buttons):
            row = index // columns
            column = index % columns
            self.buttons_frame.columnconfigure(column, weight=1)
            button.grid(row=row, column=column, sticky="ew", padx=2, pady=2)

    def _update_note_wrap(self, width: int) -> None:
        """Подстраивает ширину переноса поясняющей заметки."""
        wrap = max(260, min(620, width - 64))
        self.note.configure(wraplength=wrap)

    def refresh_list(self) -> None:
        """Обновляет список инструментов в левой части окна."""
        self.listbox.delete(0, "end")
        for tool in self.app.tools.values():
            suffix = " *" if tool.built_in else ""
            self.listbox.insert("end", f"{tool.id} - {tool.name}{suffix}")

    def load_selected(self) -> None:
        """Загружает выбранный инструмент из списка в поля формы."""
        selection = self.listbox.curselection()
        if not selection:
            return
        tool = list(self.app.tools.values())[selection[0]]
        self.selected_id = tool.id
        self.id_var.set(tool.id)
        self.name_var.set(tool.name)
        self.width_var.set(str(tool.width_m))
        self.depth_var.set(str(tool.base_depth_cm))
        self.color_var.set(tool.color)
        self.style_var.set(tool.line_style)
        self.points_text.delete("1.0", "end")
        self.points_text.insert("1.0", "\n".join(f"{point.speed_kmh}:{point.force_n}" for point in tool.reference_points))

    def add_tool(self) -> None:
        """Заполняет форму шаблоном нового пользовательского инструмента."""
        new_id = f"tool-{int(time.time())}"
        self.selected_id = None
        self.id_var.set(new_id)
        self.name_var.set("Custom tool")
        self.width_var.set("0.35")
        self.depth_var.set("10.0")
        self.color_var.set("#2ca02c")
        self.style_var.set("-")
        self.points_text.delete("1.0", "end")
        self.points_text.insert("1.0", "6:400\n10:500")

    def duplicate_tool(self) -> None:
        """Создаёт пользовательскую копию выбранного инструмента."""
        tool = self._current_tool()
        if tool is None:
            return
        clone = tool.clone_custom(new_id=f"{tool.id}-copy-{int(time.time())}")
        self.app.settings.custom_tools.append(clone)
        self.app._refresh_tool_options()
        self.refresh_list()

    def delete_tool(self) -> None:
        """Удаляет выбранный пользовательский инструмент.

        Встроенные инструменты не удаляются.
        """
        tool = self._current_tool()
        if tool is None or tool.id in BUILTIN_TOOL_IDS:
            return
        self.app.settings.custom_tools = [item for item in self.app.settings.custom_tools if item.id != tool.id]
        save_settings(self.app.settings)
        self.app._refresh_tool_options()
        self.app.calculate()
        self.refresh_list()
        messagebox.showinfo(self.localizer("info"), self.localizer("tools.deleted"))

    def save_tool(self) -> None:
        """Сохраняет данные формы как пользовательский инструмент."""
        try:
            tool = ToolProfile(
                id=self.id_var.get().strip(),
                name=self.name_var.get().strip(),
                width_m=float(self.width_var.get()),
                base_depth_cm=float(self.depth_var.get()),
                reference_points=tuple(self._parse_points()),
                speed_range=SpeedRange(),
                color=self.color_var.get().strip() or "#2ca02c",
                line_style=self.style_var.get().strip() or "-",
                built_in=False,
            )
            if tool.id in BUILTIN_TOOL_IDS:
                raise ValueError(self.localizer("tools.builtin_note"))
        except (KeyError, ValueError) as exc:
            messagebox.showerror(self.localizer("error"), self.localizer("tools.invalid", message=str(exc)))
            return

        self.app.settings.custom_tools = [item for item in self.app.settings.custom_tools if item.id != tool.id]
        self.app.settings.custom_tools.append(tool)
        save_settings(self.app.settings)
        self.app._refresh_tool_options()
        self.app.calculate()
        self.refresh_list()
        messagebox.showinfo(self.localizer("info"), self.localizer("tools.saved"))

    def _parse_points(self) -> list[ReferencePoint]:
        """Разбирает текстовое поле опорных точек в список ReferencePoint."""
        points: list[ReferencePoint] = []
        for raw_line in self.points_text.get("1.0", "end").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            speed, force = line.replace(",", ".").split(":", maxsplit=1)
            points.append(ReferencePoint(speed_kmh=float(speed), force_n=float(force)))
        return points

    def _current_tool(self) -> ToolProfile | None:
        """Возвращает выбранный инструмент или None, если выбор пустой."""
        selection = self.listbox.curselection()
        if not selection:
            return None
        return list(self.app.tools.values())[selection[0]]


def run_app() -> None:
    """Создаёт Tk-приложение и запускает главный цикл обработки событий."""
    root = tk.Tk()
    MainWindow(root)
    root.mainloop()
