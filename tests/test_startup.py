from __future__ import annotations

import tkinter as tk

import pytest

from soil_tiller_calculator.config import AppSettings
from soil_tiller_calculator.gui import MainWindow


def test_application_window_starts_and_closes(monkeypatch) -> None:
    monkeypatch.setattr("soil_tiller_calculator.gui.save_settings", lambda _settings: None)

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk runtime is not available: {exc}")

    root.withdraw()
    try:
        app = MainWindow(root, AppSettings(startup_instruction_dismissed=True))
        root.after(10, root.quit)
        root.mainloop()

        assert app.root.winfo_exists()
        assert app.results_text.winfo_exists()
    finally:
        root.destroy()
