from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from soil_tiller_calculator.calculations import OptimizationResult
from soil_tiller_calculator.config import AppSettings
from soil_tiller_calculator.gui import (
    MainWindow,
    ToolManager,
    validate_depth,
    validate_depth_limits,
    validate_speed,
    validate_speed_limits,
    validate_speed_step,
)


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


def test_validate_depth_limits_accepts_valid_range() -> None:
    assert validate_depth_limits("4", "30") == (4.0, 30.0, False)
    assert validate_depth_limits("30", "4") == (5.0, 20.0, True)


def test_validate_speed_step_requires_positive_value() -> None:
    assert validate_speed_step("0.25") == (0.25, False)
    assert validate_speed_step("0") == (0.5, True)
    assert validate_speed_step("bad") == (0.5, True)


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
    app = MainWindow(root, AppSettings())
    menu = app.main_menu
    assert menu is not None
    assert app.menu_labels == ("Файл", "Инструменты", "Настройки")
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
    app = MainWindow(root, AppSettings())

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
    app = MainWindow(root, AppSettings())
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
    app = MainWindow(root, AppSettings())

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
    app = MainWindow(root, AppSettings())
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
    app = MainWindow(root, AppSettings())
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
    app = MainWindow(root, AppSettings())
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
    app = MainWindow(root, AppSettings())
    app.custom_depth_limits_var.set(True)
    app.depth_min_var.set("30")
    app.depth_max_var.set("4")

    assert app._depth_limits() == (5.0, 20.0)
    assert app.settings.custom_depth_limits_enabled is False
    assert app.custom_depth_limits_var.get() is False
    root.destroy()


def test_tool_manager_adapts_to_window_width(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is not available: {exc}")

    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)
    monkeypatch.setattr("soil_tiller_calculator.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    root.withdraw()
    app = MainWindow(root, AppSettings())
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
