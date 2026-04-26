from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from soil_tiller_calculator.models import BUILTIN_TOOLS, ToolProfile


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    """Результат поиска оптимальной скорости.

    speed_kmh: выбранная скорость в км/ч.
    q_min: минимальное среднее удельное сопротивление.
    q_by_tool: значения q по каждому инструменту на выбранной скорости.
    """

    speed_kmh: float
    q_min: float
    q_by_tool: dict[str, float]


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    """Результат сравнения двух инструментов по удельному сопротивлению.

    better_tool и worse_tool показывают лучший и худший инструмент.
    first_q и second_q содержат q для исходной пары.
    difference_percent хранит разницу относительно первого инструмента.
    """

    better_tool: ToolProfile
    worse_tool: ToolProfile
    first_q: float
    second_q: float
    difference_percent: float


def resolve_tool(tool_type_or_profile: str | ToolProfile) -> ToolProfile:
    """Возвращает профиль инструмента по id или готовому объекту.

    Принимает строковый id встроенного инструмента (`kps`, `exp`) или
    экземпляр ToolProfile. Если id неизвестен, выбрасывает ValueError.
    """
    if isinstance(tool_type_or_profile, ToolProfile):
        return tool_type_or_profile
    try:
        return BUILTIN_TOOLS[tool_type_or_profile]
    except KeyError as exc:
        raise ValueError(f"Unknown tool type: {tool_type_or_profile}") from exc


def speed_grid(start: float = 5.0, stop: float = 12.0, step: float = 0.5) -> list[float]:
    """Формирует список скоростей для оптимизации.

    Принимает начальную скорость, конечную скорость и шаг в км/ч.
    Возвращает включительный диапазон, где присутствуют и start, и stop.
    """
    return _inclusive_grid(start, stop, step)


def plot_speed_grid(start: float = 5.0, stop: float = 12.0, step: float = 0.2) -> list[float]:
    """Формирует список скоростей для построения графиков.

    Работает так же, как speed_grid, но по умолчанию использует более
    мелкий шаг, чтобы линии на графиках были плавнее.
    """
    return _inclusive_grid(start, stop, step)


def force_at_depth(v: float, H: float, tool_type_or_profile: str | ToolProfile) -> float:
    """Рассчитывает силу тяги F для заданной скорости и глубины.

    v: скорость движения в км/ч.
    H: глубина обработки в сантиметрах.
    tool_type_or_profile: id встроенного инструмента или ToolProfile.
    Возвращает силу тяги в ньютонах.
    """
    tool = resolve_tool(tool_type_or_profile)
    base_force = _interpolated_force(float(v), tool)
    return base_force * float(H) / tool.base_depth_cm


def specific_resistance(v: float, H: float, tool_type_or_profile: str | ToolProfile) -> float:
    """Рассчитывает удельное сопротивление q.

    Использует force_at_depth и делит силу тяги на ширину лапы.
    Возвращает q в Н/м; чем меньше значение, тем легче инструменту
    работать при одинаковых условиях.
    """
    tool = resolve_tool(tool_type_or_profile)
    return force_at_depth(v, H, tool) / tool.width_m


def power_and_fuel(v: float, H: float, tool_type_or_profile: str | ToolProfile) -> tuple[float, float]:
    """Рассчитывает тяговую мощность P и расход топлива Q.

    v: скорость в км/ч, H: глубина в см, tool_type_or_profile: инструмент.
    Возвращает кортеж `(P, Q)`, где P измеряется в кВт, а Q в л/ч.
    """
    tool = resolve_tool(tool_type_or_profile)
    force_n = force_at_depth(v, H, tool)
    speed_ms = float(v) / 3.6
    power_kw = force_n * speed_ms / 1000
    fuel_lph = power_kw * tool.fuel_specific_consumption / tool.fuel_density
    return power_kw, fuel_lph


def optimize_speed(
    H: float,
    tools: Iterable[str | ToolProfile],
    *,
    start: float = 5.0,
    stop: float = 12.0,
    step: float = 0.5,
) -> OptimizationResult:
    """Ищет скорость с минимальным средним удельным сопротивлением.

    H: глубина обработки в см.
    tools: список id или ToolProfile для расчёта.
    start, stop, step: диапазон и шаг перебора скоростей в км/ч.
    Возвращает OptimizationResult с лучшей скоростью и значениями q.
    """
    resolved_tools = [resolve_tool(tool) for tool in tools]
    if not resolved_tools:
        raise ValueError("At least one tool is required for optimization.")

    best_speed = start
    best_q = float("inf")
    best_values: dict[str, float] = {}

    for speed in speed_grid(start, stop, step):
        values = {tool.id: specific_resistance(speed, H, tool) for tool in resolved_tools}
        average_q = sum(values.values()) / len(values)
        if average_q < best_q:
            best_speed = speed
            best_q = average_q
            best_values = values

    return OptimizationResult(speed_kmh=best_speed, q_min=best_q, q_by_tool=best_values)


def compare_tools(H: float, v: float, first: str | ToolProfile, second: str | ToolProfile) -> ComparisonResult:
    """Сравнивает два инструмента при одной глубине и скорости.

    H: глубина в см, v: скорость в км/ч.
    first и second: id или ToolProfile. Процентная разница считается
    относительно первого инструмента.
    """
    first_tool = resolve_tool(first)
    second_tool = resolve_tool(second)
    first_q = specific_resistance(v, H, first_tool)
    second_q = specific_resistance(v, H, second_tool)
    better = first_tool if first_q <= second_q else second_tool
    worse = second_tool if better is first_tool else first_tool
    if first_q <= 0:
        difference = 0.0 if second_q == first_q else float("inf")
    else:
        difference = abs(second_q - first_q) / first_q * 100
    return ComparisonResult(
        better_tool=better,
        worse_tool=worse,
        first_q=first_q,
        second_q=second_q,
        difference_percent=difference,
    )


def _inclusive_grid(start: float, stop: float, step: float) -> list[float]:
    """Формирует возрастающую сетку без выхода за конечную границу."""
    start = float(start)
    stop = float(stop)
    step = float(step)
    if step <= 0:
        raise ValueError("Grid step must be greater than zero.")
    if start > stop:
        raise ValueError("Grid start must be less than or equal to stop.")
    values = [round(start, 10)]
    current = start
    while current + step < stop:
        current += step
        values.append(round(current, 10))
    if values[-1] != round(stop, 10):
        values.append(round(stop, 10))
    return values


def _interpolated_force(v: float, tool: ToolProfile) -> float:
    """Находит силу на опорной глубине по линейной интерполяции.

    v: скорость в км/ч, tool: профиль инструмента с опорными точками.
    Если скорость выходит за диапазон точек, используется экстраполяция
    по ближайшему сегменту.
    """
    points = tool.reference_points
    if v <= points[0].speed_kmh:
        left, right = points[0], points[1]
    elif v >= points[-1].speed_kmh:
        left, right = points[-2], points[-1]
    else:
        for index in range(len(points) - 1):
            left, right = points[index], points[index + 1]
            if left.speed_kmh <= v <= right.speed_kmh:
                break
        else:
            raise RuntimeError("Unable to find interpolation segment.")

    slope = (right.force_n - left.force_n) / (right.speed_kmh - left.speed_kmh)
    return left.force_n + slope * (v - left.speed_kmh)
