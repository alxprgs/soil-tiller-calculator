from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path

import pytest

from soil_tiller_calculator.calculations import OptimizationResult
from soil_tiller_calculator.config import AppSettings
from soil_tiller_calculator.version import __version__
from soil_tiller_calculator.gui import (
    AboutWindow,
    ChangelogWindow,
    InstructionWindow,
    LicenseWindow,
    MainWindow,
    ToolManager,
    format_changelog,
    format_instruction_text,
    is_newer_version,
    load_changelog_entries,
    should_show_startup_changelog,
    should_show_startup_instruction,
    validate_depth,
    validate_depth_limits,
    validate_speed,
    validate_speed_limits,
    validate_speed_step,
    version_tuple,
)


def gui_settings(**kwargs) -> AppSettings:
    defaults = {"startup_instruction_dismissed": True}
    defaults.update(kwargs)
    return AppSettings(**defaults)


def test_validate_depth_accepts_valid_range() -> None:
    assert validate_depth("5") == (5.0, False)
    assert validate_depth("20") == (20.0, False)
    assert validate_depth("12.5") == (12.5, False)


def test_validate_depth_defaults_invalid_values() -> None:
    assert validate_depth("4.9") == (10.0, True)
    assert validate_depth("bad") == (10.0, True)


def test_validate_depth_accepts_custom_limits_and_fallback() -> None:
    assert validate_depth("25", 4, 30, 17) == (25.0, False)
    assert validate_depth("3", 4, 30, 17) == (17, True)


def test_validate_speed_accepts_valid_range() -> None:
    assert validate_speed("5") == (5.0, False)
    assert validate_speed("12") == (12.0, False)
    assert validate_speed("8.5") == (8.5, False)


def test_validate_speed_defaults_invalid_values() -> None:
    assert validate_speed("12.1") == (8.0, True)
    assert validate_speed("bad") == (8.0, True)


def test_validate_speed_accepts_custom_limits_and_fallback() -> None:
    assert validate_speed("14", 3, 15, 9) == (14.0, False)
    assert validate_speed("2", 3, 15, 9) == (9, True)


def test_validate_speed_limits_accepts_valid_range() -> None:
    assert validate_speed_limits("3", "15") == (3.0, 15.0, False)
    assert validate_speed_limits("15", "3") == (5.0, 12.0, True)
    assert validate_speed_limits("0", "15") == (5.0, 12.0, True)
    assert validate_speed_limits("-1", "15") == (5.0, 12.0, True)


def test_validate_depth_limits_accepts_valid_range() -> None:
    assert validate_depth_limits("4", "30") == (4.0, 30.0, False)
    assert validate_depth_limits("30", "4") == (5.0, 20.0, True)
    assert validate_depth_limits("0", "30") == (5.0, 20.0, True)
    assert validate_depth_limits("-1", "30") == (5.0, 20.0, True)


def test_validate_speed_step_requires_positive_value() -> None:
    assert validate_speed_step("0.25") == (0.25, False)
    assert validate_speed_step("0") == (0.5, True)
    assert validate_speed_step("bad") == (0.5, True)


def test_version_comparison_accepts_github_release_tags() -> None:
    assert version_tuple("v1.2.3") == (1, 2, 3)
    assert version_tuple("0.2") == (0, 2, 0)
    assert is_newer_version("v1.0.0", "0.2.3")
    assert not is_newer_version("v0.2.3", "0.2.3")


def test_startup_changelog_visibility_rules() -> None:
    assert not should_show_startup_changelog(False, "")
    assert should_show_startup_changelog(True, "")
    assert should_show_startup_changelog(True, "0.2.3")
    assert not should_show_startup_changelog(True, __version__)


def test_startup_instruction_visibility_rules() -> None:
    assert should_show_startup_instruction(False)
    assert not should_show_startup_instruction(True)


def test_changelog_resource_contains_release_history() -> None:
    entries = load_changelog_entries()
    text = format_changelog(entries, lambda key: "Current build" if key == "changelog.current_build" else key)

    assert "Current build" in text
    for version in ("v1.0.0", "v0.2.0", "v0.2.1", "v0.2.2", "v0.2.3", "v0.2.4"):
        assert version in text


def test_main_window_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    mpl_config = Path.cwd() / ".cache" / "matplotlib-test"
    mpl_config.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MPLCONFIGDIR", str(mpl_config))

    root.withdraw()
    app = MainWindow(root, gui_settings())
    menu = app.main_menu
    assert menu is not None
    file_menu = app.file_menu
    assert file_menu is not None
    settings_menu = app.settings_menu
    assert settings_menu is not None
    file_labels = [
        file_menu.entrycget(index, "label")
        for index in range((file_menu.index("end") or 0) + 1)
        if file_menu.type(index) != "separator"
    ]
    settings_labels = [
        settings_menu.entrycget(index, "label")
        for index in range((settings_menu.index("end") or 0) + 1)
        if settings_menu.type(index) != "separator"
    ]
    assert app.localizer("changelog.title") in file_labels
    assert app.localizer("instruction.title") in file_labels
    assert app.localizer("pretty_interface") in settings_labels
    assert app.localizer("inline_help") in settings_labels
    assert app.pretty_interface_var.get() is False
    assert app.settings.pretty_interface_enabled is False
    assert app.inline_help_var.get() is True
    assert app.settings.inline_help_enabled is True
    assert not app.depth_min_help.grid_info()
    assert not app.depth_max_help.grid_info()
    assert not app.speed_min_help.grid_info()
    assert not app.speed_max_help.grid_info()
    assert app.menu_labels == ("Файл", "Инструменты", "Настройки")
    assert any(label == "Версия" and value == __version__ for label, value in app.about_details())
    assert any(label == "Лицензия" and value == "MIT" for label, value in app.about_details())
    assert all(isinstance(label, str) and isinstance(value, str) for label, value in app.about_details())
    assert not hasattr(app, "tools_button")
    assert not hasattr(app, "import_button")
    assert not hasattr(app, "export_button")
    assert not hasattr(app, "speed_step_label")
    assert not hasattr(app, "speed_step_entry")

    app.depth_var.set("25")
    app.speed_var.set("30")
    app.calculate()

    text = app.results_text.get("1.0", "end")
    assert "10.0" in text
    assert "8.0" in text
    assert "F -" in text
    assert "q -" in text
    assert "P -" in text
    assert "Q -" in text

    app.language_var.set("en")
    app.change_language()
    assert app.localizer.language == "en"
    assert app.settings.language == "en"
    assert "drawbar power" in app.results_text.get("1.0", "end")

    app._apply_responsive_layout(1200)
    assert app.parameters.grid_info()["column"] == 0
    assert app.graphs.grid_info()["column"] == 1
    app._apply_responsive_layout(800)
    assert app.parameters.grid_info()["row"] == 0
    assert app.graphs.grid_info()["row"] == 1
    root.destroy()


def test_pretty_interface_toggle_updates_style_and_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    saved: list[bool] = []
    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda settings: saved.append(settings.pretty_interface_enabled))
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    root.withdraw()
    app = MainWindow(root, gui_settings())
    saved.clear()

    app.pretty_interface_var.set(True)
    app.toggle_pretty_interface()

    assert app.settings.pretty_interface_enabled is True
    assert app.pretty_interface_var.get() is True
    assert saved and all(saved_value is True for saved_value in saved)
    assert "F -" in app.results_text.get("1.0", "end")
    if app.figure is not None:
        assert app.figure.axes
        assert app.figure.get_facecolor()[:3] != (1.0, 1.0, 1.0)
    root.destroy()


def test_inline_help_toggle_hides_and_restores_icons(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    saved: list[bool] = []
    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda settings: saved.append(settings.inline_help_enabled))
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    root.withdraw()
    app = MainWindow(root, gui_settings())
    visible_icon = next(widget for widget in app._help_widgets if widget.grid_info())

    app.inline_help_var.set(False)
    app.toggle_inline_help()

    assert app.settings.inline_help_enabled is False
    assert saved[-1] is False
    assert all(not widget.grid_info() for widget in app._help_widgets if widget.winfo_exists())

    app.inline_help_var.set(True)
    app.toggle_inline_help()

    assert app.settings.inline_help_enabled is True
    assert saved[-1] is True
    assert visible_icon.grid_info()
    root.destroy()


def test_help_icon_opens_matching_instruction_section(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    opened: list[str | None] = []
    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    root.withdraw()
    app = MainWindow(root, gui_settings())
    monkeypatch.setattr(app, "open_instruction", lambda section_id=None, **_kwargs: opened.append(section_id))

    app.depth_entry.focus_set()
    app._help_widgets[0].invoke()

    assert opened == ["depth"]
    root.destroy()


def test_instruction_window_manual_mode_is_not_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    root.withdraw()
    app = MainWindow(root, gui_settings())
    instruction = app.open_instruction(section_id="graphs")
    instruction.window.withdraw()

    assert str(instruction.close_button["state"]) == "normal"
    assert instruction.dismiss_button is None
    assert "F" in format_instruction_text(app.localizer)
    assert instruction.section_id == "graphs"

    instruction.window.destroy()
    root.destroy()


def test_instruction_window_strict_mode_unlocks_after_scroll(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    saved: list[bool] = []
    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda settings: saved.append(settings.startup_instruction_dismissed))
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    root.withdraw()
    app = MainWindow(root, gui_settings())
    app.settings.startup_instruction_dismissed = False
    instruction = InstructionWindow(app, root, modal=True, startup=True)
    instruction.window.withdraw()

    assert str(instruction.close_button["state"]) == "disabled"
    assert instruction.dismiss_button is not None
    assert str(instruction.dismiss_button["state"]) == "disabled"

    instruction.text.yview_moveto(1.0)
    instruction._check_read_to_end()

    assert str(instruction.close_button["state"]) == "normal"
    assert str(instruction.dismiss_button["state"]) == "normal"
    instruction._dismiss_and_close()
    assert app.settings.startup_instruction_dismissed is True
    assert saved[-1] is True
    root.destroy()


def test_startup_instruction_is_scheduled_by_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    callbacks: list[object] = []
    monkeypatch.setattr(root, "after_idle", lambda callback: callbacks.append(callback))
    monkeypatch.setattr("soil_tiller_calculator.gui.MainWindow._init_graphs", lambda self: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    root.withdraw()

    MainWindow(root, AppSettings(startup_instruction_dismissed=False))

    assert callbacks
    root.destroy()

    root = tk.Tk()
    callbacks = []
    monkeypatch.setattr(root, "after_idle", lambda callback: callbacks.append(callback))
    root.withdraw()

    MainWindow(root, gui_settings())

    assert callbacks == []
    root.destroy()


def test_main_window_recovers_broken_startup_config(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    config_dir = Path.cwd() / ".cache" / "config-recovery-test"
    config_dir.mkdir(parents=True, exist_ok=True)
    for item in config_dir.glob("config*"):
        item.unlink()
    config_path = config_dir / "config.json"
    config_path.write_text("{bad", encoding="utf-8")
    callbacks: list[object] = []
    monkeypatch.setattr("soil_tiller_calculator.gui.active_config_path", lambda: config_path)
    monkeypatch.setattr("soil_tiller_calculator.config.active_config_path", lambda: config_path)
    monkeypatch.setattr(root, "after_idle", lambda callback: callbacks.append(callback))
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    root.withdraw()

    app = MainWindow(root)

    backups = list(config_dir.glob("config.broken-*.json"))
    assert backups
    assert backups[0].read_text(encoding="utf-8") == "{bad"
    assert json.loads(config_path.read_text(encoding="utf-8"))["schema_version"] == 1
    assert app._config_recovery_error is not None
    assert app._config_recovery_backup in backups
    assert callbacks
    root.destroy()


def test_about_window_adapts_to_window_width(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    root.withdraw()
    app = MainWindow(root, gui_settings())
    about = AboutWindow(app, root, check_updates=False)
    about.window.withdraw()
    assert about.window.winfo_width() <= 560
    assert about.update_var.get()
    assert about.timestamp_var.get()
    assert about._timestamp_job is not None

    about._apply_responsive_layout(560)
    first_label, first_value = about.rows[0]
    assert first_label.grid_info()["row"] == first_value.grid_info()["row"]
    assert first_value.grid_info()["column"] == 1

    about._apply_responsive_layout(360)
    assert first_value.grid_info()["row"] == first_label.grid_info()["row"] + 1
    assert first_value.grid_info()["columnspan"] == 2

    timestamp_job = about._timestamp_job
    about.destroy()
    assert timestamp_job is not None
    assert about._timestamp_job is None
    root.destroy()


def test_about_window_reports_update_status(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.fetch_latest_release", lambda: ("v99.0.0", "https://example.test/release"))
    root.withdraw()
    app = MainWindow(root, gui_settings())
    about = AboutWindow(app, root, check_updates=False)
    about.window.withdraw()

    about._check_updates_in_background()
    root.update()

    assert "99.0.0" in about.update_var.get()
    assert about.update_url == "https://example.test/release"
    about.destroy()
    root.destroy()


def test_changelog_window_shows_bundled_history(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    root.withdraw()
    app = MainWindow(root, gui_settings(language="en"))
    changelog = ChangelogWindow(app.localizer, root)
    changelog.window.withdraw()

    text = changelog.text.get("1.0", "end")
    assert "Current build" in text
    assert "v1.0.0" in text
    assert "Chocolatey" in text

    changelog.window.destroy()
    root.destroy()


def test_license_window_reads_mit_license(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)
    root.withdraw()
    app = MainWindow(root, gui_settings())
    license_window = LicenseWindow(app.localizer, root)
    license_window.window.withdraw()

    assert "MIT License" in license_window.text.get("1.0", "end")
    license_window.window.destroy()
    root.destroy()


def test_optimization_step_is_configured_from_settings_dialog(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    saved: list[AppSettings] = []
    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda settings: saved.append(settings))
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.simpledialog.askfloat", lambda *_args, **_kwargs: 0.25)
    root.withdraw()
    app = MainWindow(root, gui_settings())

    app.configure_optimization_step()

    assert app.speed_step_var.get() == "0.25"
    assert app.settings.speed_step_kmh == pytest.approx(0.25)
    assert saved
    root.destroy()


def test_graphs_always_include_required_builtin_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    root.withdraw()
    app = MainWindow(root, gui_settings())
    app.tool_mode_var.set("single")
    app.first_tool_var.set("kps")

    app.calculate()

    assert app.figure is not None
    labels = {line.get_label() for line in app.figure.axes[0].lines}
    assert {"КПС-4,0", "Экспериментальная"}.issubset(labels)
    root.destroy()


def test_enabling_custom_limits_shows_assignment_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    warnings: list[str] = []
    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda _title, message: warnings.append(message))
    root.withdraw()
    app = MainWindow(root, gui_settings())

    app.custom_speed_limits_var.set(True)
    app.toggle_custom_speed_limits()
    app.custom_depth_limits_var.set(True)
    app.toggle_custom_depth_limits()

    assert any("скорости отклоняют расчёт от ТЗ" in message for message in warnings)
    assert any("глубины отклоняют расчёт от ТЗ" in message for message in warnings)
    root.destroy()


def test_custom_speed_limits_drive_auto_optimization(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)

    calls: dict[str, float] = {}

    def fake_optimize(_depth, _tools, *, start, stop, step=0.5):
        calls["start"] = start
        calls["stop"] = stop
        calls["step"] = step
        return OptimizationResult(speed_kmh=start, q_min=100.0, q_by_tool={})

    monkeypatch.setattr("soil_tiller_calculator.gui.optimize_speed", fake_optimize)
    root.withdraw()
    app = MainWindow(root, gui_settings())
    app.speed_mode_var.set("auto")
    app.custom_speed_limits_var.set(True)
    app.speed_min_var.set("3")
    app.speed_max_var.set("15")
    app.speed_step_var.set("0.25")
    app.calculate()

    assert calls["start"] == pytest.approx(3.0)
    assert calls["stop"] == pytest.approx(15.0)
    assert calls["step"] == pytest.approx(0.25)
    assert app.settings.custom_speed_limits_enabled is True
    assert app.settings.speed_step_kmh == pytest.approx(0.25)
    root.destroy()


def test_invalid_custom_speed_limits_reset_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    root.withdraw()
    app = MainWindow(root, gui_settings())
    app.custom_speed_limits_var.set(True)
    app.speed_min_var.set("20")
    app.speed_max_var.set("10")

    assert app._speed_limits() == (5.0, 12.0)
    assert app.settings.custom_speed_limits_enabled is False
    assert app.custom_speed_limits_var.get() is False
    root.destroy()


def test_custom_depth_limits_and_invalid_step(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    root.withdraw()
    app = MainWindow(root, gui_settings())
    app.custom_depth_limits_var.set(True)
    app.depth_min_var.set("4")
    app.depth_max_var.set("30")
    app.depth_var.set("25")
    app.speed_step_var.set("-1")
    app.calculate()

    assert app.depth_var.get() == "25.0"
    assert app.settings.custom_depth_limits_enabled is True
    assert app.settings.depth_min_cm == pytest.approx(4.0)
    assert app.settings.depth_max_cm == pytest.approx(30.0)
    assert app.speed_step_var.get() == "0.5"
    assert app.settings.speed_step_kmh == pytest.approx(0.5)
    root.destroy()


def test_invalid_custom_depth_limits_reset_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    root.withdraw()
    app = MainWindow(root, gui_settings())
    app.custom_depth_limits_var.set(True)
    app.depth_min_var.set("30")
    app.depth_max_var.set("4")

    assert app._depth_limits() == (5.0, 20.0)
    assert app.settings.custom_depth_limits_enabled is False
    assert app.custom_depth_limits_var.get() is False
    root.destroy()


def test_negative_custom_depth_limits_reset_and_do_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    root.withdraw()
    app = MainWindow(root, gui_settings())
    app.custom_depth_limits_var.set(True)
    app.depth_min_var.set("-1")
    app.depth_max_var.set("10")
    app.depth_var.set("0")

    app.calculate()

    assert app.settings.custom_depth_limits_enabled is False
    assert app.custom_depth_limits_var.get() is False
    assert app.depth_var.get() == "10.0"
    root.destroy()


def test_tool_manager_adapts_to_window_width(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    root.withdraw()
    app = MainWindow(root, gui_settings())
    manager = ToolManager(app, root)
    manager.window.withdraw()

    manager._apply_responsive_layout(760)
    assert manager.list_frame.grid_info()["column"] == 0
    assert manager.form_frame.grid_info()["column"] == 1
    assert manager.buttons[-1].grid_info()["row"] == 0

    manager._apply_responsive_layout(520)
    assert manager.list_frame.grid_info()["row"] == 0
    assert manager.form_frame.grid_info()["row"] == 1
    assert manager.buttons[-1].grid_info()["row"] == 2

    manager.window.destroy()
    root.destroy()
