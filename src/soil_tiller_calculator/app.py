from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from pathlib import Path
from types import FrameType
from typing import Any

from soil_tiller_calculator.version import __version__

LOGGER = logging.getLogger(__name__)
TRACE_LOGGER = logging.getLogger("soil_tiller_calculator.trace")
PACKAGE_ROOT = Path(__file__).resolve().parent
PACKAGE_ROOT_TEXT = str(PACKAGE_ROOT) + os.sep
APP_FILE_TEXT = str(Path(__file__).resolve())
_TRACE_STATE = threading.local()


def _short_repr(value: Any, limit: int = 160) -> str:
    """Возвращает короткое представление значения для debug-трассировки."""
    try:
        text = repr(value)
    except Exception as exc:  # pragma: no cover - защита от чужих repr.
        text = f"<repr failed: {exc}>"
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _frame_location(frame: FrameType) -> str:
    """Формирует короткий путь и строку текущего кадра."""
    filename = Path(frame.f_code.co_filename).resolve()
    try:
        relative = filename.relative_to(PACKAGE_ROOT.parent)
    except ValueError:
        relative = filename
    return f"{relative}:{frame.f_lineno}"


def _should_trace(frame: FrameType) -> bool:
    """Проверяет, относится ли кадр к коду приложения."""
    filename = os.path.abspath(frame.f_code.co_filename)
    return filename != APP_FILE_TEXT and filename.startswith(PACKAGE_ROOT_TEXT)


def _format_call_arguments(frame: FrameType) -> str:
    """Собирает аргументы вызванной функции в компактную строку."""
    code = frame.f_code
    argument_names = list(code.co_varnames[: code.co_argcount + code.co_kwonlyargcount])
    values: list[str] = []
    for name in argument_names:
        if name in frame.f_locals:
            values.append(f"{name}={_short_repr(frame.f_locals[name])}")
    if code.co_flags & 0x04:
        name = code.co_varnames[code.co_argcount + code.co_kwonlyargcount]
        values.append(f"*{name}={_short_repr(frame.f_locals.get(name, ()))}")
    if code.co_flags & 0x08:
        index = code.co_argcount + code.co_kwonlyargcount
        if code.co_flags & 0x04:
            index += 1
        name = code.co_varnames[index]
        values.append(f"**{name}={_short_repr(frame.f_locals.get(name, {}))}")
    return ", ".join(values)


def _trace_calls(frame: FrameType, event: str, arg: Any):
    """Пишет подробную трассировку вызовов, возвратов и исключений пакета."""
    if event not in {"call", "return", "exception"}:
        return _trace_calls
    if getattr(_TRACE_STATE, "busy", False) or not _should_trace(frame):
        return _trace_calls
    _TRACE_STATE.busy = True
    try:
        function_name = frame.f_code.co_name
        location = _frame_location(frame)
        if event == "call":
            TRACE_LOGGER.debug("CALL %s %s(%s)", location, function_name, _format_call_arguments(frame))
        elif event == "return":
            TRACE_LOGGER.debug("RETURN %s %s -> %s", location, function_name, _short_repr(arg))
        elif event == "exception":
            exc_type, exc_value, _traceback = arg
            TRACE_LOGGER.debug("EXCEPTION %s %s: %s", location, exc_type.__name__, _short_repr(exc_value))
    finally:
        _TRACE_STATE.busy = False
    return _trace_calls


def configure_debug_logging(debug: bool, *, trace: bool = False) -> None:
    """Настраивает консольное логирование и подробную трассировку."""
    if not debug:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s:%(name)s:%(message)s")
        return

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s:%(lineno)d %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    for noisy_logger in ("matplotlib", "PIL"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    LOGGER.debug("Debug logging enabled")
    LOGGER.debug("Version=%s Python=%s Executable=%s", __version__, sys.version.replace("\n", " "), sys.executable)
    LOGGER.debug("CWD=%s ARGV=%s PID=%s", os.getcwd(), sys.argv, os.getpid())
    if trace:
        sys.settrace(_trace_calls)
        threading.settrace(_trace_calls)
        LOGGER.debug("Function call trace enabled")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Разбирает аргументы командной строки приложения."""
    parser = argparse.ArgumentParser(description="Soil tiller calculator")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="enable verbose debug logging in the console",
    )
    parser.add_argument(
        "--debug-trace",
        action="store_true",
        help="also trace package function calls and returns; extremely noisy and slow",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Запускает графическое приложение из консольной точки входа."""
    args = parse_args(argv)
    debug_enabled = args.debug or args.debug_trace
    configure_debug_logging(debug_enabled, trace=args.debug_trace)
    LOGGER.debug("Importing GUI module")
    from soil_tiller_calculator.gui import run_app

    LOGGER.debug("Starting GUI application")
    run_app(debug=debug_enabled)
