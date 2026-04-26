from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

VALID_LINE_STYLES = frozenset({"-", "--", "-.", ":", "solid", "dashed", "dashdot", "dotted"})


class ToolValidationError(ValueError):
    """Ошибка валидации профиля инструмента.

    Возникает, если профиль неполный или содержит физически невозможные
    значения: отрицательную ширину, пустое имя, повторяющиеся скорости и т.д.
    """


@dataclass(frozen=True, slots=True)
class ReferencePoint:
    """Опорная точка зависимости силы тяги от скорости.

    speed_kmh: скорость в км/ч.
    force_n: сила тяги в ньютонах на опорной глубине инструмента.
    """

    speed_kmh: float
    force_n: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReferencePoint":
        """Создаёт опорную точку из словаря JSON-конфига."""
        return cls(speed_kmh=float(data["speed_kmh"]), force_n=float(data["force_n"]))

    def to_dict(self) -> dict[str, float]:
        """Преобразует опорную точку в словарь для сохранения в JSON."""
        return {"speed_kmh": self.speed_kmh, "force_n": self.force_n}


@dataclass(frozen=True, slots=True)
class SpeedRange:
    """Допустимый диапазон скоростей инструмента.

    min_kmh и max_kmh задаются в км/ч и используются как справочные
    границы для пользовательских профилей.
    """

    min_kmh: float = 5.0
    max_kmh: float = 12.0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SpeedRange":
        """Создаёт диапазон скоростей из словаря или возвращает значения по умолчанию."""
        if data is None:
            return cls()
        return cls(min_kmh=float(data["min_kmh"]), max_kmh=float(data["max_kmh"]))

    def to_dict(self) -> dict[str, float]:
        """Преобразует диапазон скоростей в словарь для JSON-конфига."""
        return {"min_kmh": self.min_kmh, "max_kmh": self.max_kmh}


@dataclass(frozen=True, slots=True)
class ToolProfile:
    """Профиль рабочего инструмента.

    Хранит все параметры, нужные для расчётов и отображения: id, название,
    ширину, опорную глубину, точки скорость-сила, топливные коэффициенты,
    цвет/стиль графика и признак встроенного инструмента.
    """

    id: str
    name: str
    width_m: float
    base_depth_cm: float
    reference_points: tuple[ReferencePoint, ...]
    speed_range: SpeedRange = field(default_factory=SpeedRange)
    fuel_specific_consumption: float = 0.25
    fuel_density: float = 0.85
    color: str = "#1f77b4"
    line_style: str = "-"
    built_in: bool = False

    def __post_init__(self) -> None:
        """Сортирует опорные точки по скорости и запускает проверку профиля."""
        normalized_points = tuple(sorted(self.reference_points, key=lambda point: point.speed_kmh))
        object.__setattr__(self, "reference_points", normalized_points)
        self.validate()

    def validate(self) -> None:
        """Проверяет, что профиль можно безопасно использовать в расчётах.

        Метод не возвращает значение. При ошибке выбрасывает ToolValidationError.
        """
        if not self.id:
            raise ToolValidationError("Tool id is required.")
        if not self.name:
            raise ToolValidationError("Tool name is required.")
        if self.width_m <= 0:
            raise ToolValidationError("Tool width must be greater than zero.")
        if self.base_depth_cm <= 0:
            raise ToolValidationError("Base depth must be greater than zero.")
        if len(self.reference_points) < 2:
            raise ToolValidationError("At least two reference points are required.")
        speeds = [point.speed_kmh for point in self.reference_points]
        if len(set(speeds)) != len(speeds):
            raise ToolValidationError("Reference point speeds must be unique.")
        if any(point.force_n <= 0 for point in self.reference_points):
            raise ToolValidationError("Reference forces must be greater than zero.")
        if self.speed_range.min_kmh >= self.speed_range.max_kmh:
            raise ToolValidationError("Minimum speed must be less than maximum speed.")
        if self.fuel_specific_consumption <= 0:
            raise ToolValidationError("Fuel specific consumption must be greater than zero.")
        if self.fuel_density <= 0:
            raise ToolValidationError("Fuel density must be greater than zero.")
        if not _is_valid_color(self.color):
            raise ToolValidationError("Tool color must be a valid matplotlib color.")
        if self.line_style not in VALID_LINE_STYLES:
            raise ToolValidationError("Tool line style is not supported.")

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, built_in: bool = False) -> "ToolProfile":
        """Создаёт профиль инструмента из словаря JSON-конфига.

        data: словарь с параметрами инструмента.
        built_in: значение по умолчанию для признака встроенного инструмента,
        если поле отсутствует в data.
        """
        points = tuple(ReferencePoint.from_dict(item) for item in data["reference_points"])
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            width_m=float(data["width_m"]),
            base_depth_cm=float(data.get("base_depth_cm", 10.0)),
            reference_points=points,
            speed_range=SpeedRange.from_dict(data.get("speed_range")),
            fuel_specific_consumption=float(data.get("fuel_specific_consumption", 0.25)),
            fuel_density=float(data.get("fuel_density", 0.85)),
            color=str(data.get("color", "#1f77b4")),
            line_style=str(data.get("line_style", "-")),
            built_in=bool(data.get("built_in", built_in)),
        )

    def to_dict(self, *, include_built_in: bool = False) -> dict[str, Any]:
        """Преобразует профиль инструмента в словарь для сохранения.

        include_built_in управляет тем, нужно ли сохранять служебный признак
        встроенного инструмента.
        """
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "width_m": self.width_m,
            "base_depth_cm": self.base_depth_cm,
            "reference_points": [point.to_dict() for point in self.reference_points],
            "speed_range": self.speed_range.to_dict(),
            "fuel_specific_consumption": self.fuel_specific_consumption,
            "fuel_density": self.fuel_density,
            "color": self.color,
            "line_style": self.line_style,
        }
        if include_built_in:
            data["built_in"] = self.built_in
        return data

    def clone_custom(self, *, new_id: str, new_name: str | None = None) -> "ToolProfile":
        """Создаёт пользовательскую копию профиля.

        new_id: id нового инструмента.
        new_name: новое имя; если не передано, используется имя исходника с
        пометкой copy. Копия всегда получает built_in=False.
        """
        return ToolProfile(
            id=new_id,
            name=new_name or f"{self.name} copy",
            width_m=self.width_m,
            base_depth_cm=self.base_depth_cm,
            reference_points=self.reference_points,
            speed_range=self.speed_range,
            fuel_specific_consumption=self.fuel_specific_consumption,
            fuel_density=self.fuel_density,
            color=self.color,
            line_style=self.line_style,
            built_in=False,
        )


def _is_valid_color(color: str) -> bool:
    """Проверяет цвет matplotlib, не делая модель жёстко зависимой от установленного matplotlib."""
    if not color:
        return False
    try:
        from matplotlib.colors import is_color_like
    except ModuleNotFoundError:
        return True
    return bool(is_color_like(color))


KPS_TOOL = ToolProfile(
    id="kps",
    name="КПС-4,0",
    width_m=0.33,
    base_depth_cm=10.0,
    reference_points=(
        ReferencePoint(speed_kmh=6.0, force_n=367.8),
        ReferencePoint(speed_kmh=10.0, force_n=403.5),
    ),
    color="blue",
    line_style="-",
    built_in=True,
)

EXPERIMENTAL_TOOL = ToolProfile(
    id="exp",
    name="Экспериментальная",
    width_m=0.40,
    base_depth_cm=10.0,
    reference_points=(
        ReferencePoint(speed_kmh=6.0, force_n=429.7),
        ReferencePoint(speed_kmh=10.0, force_n=544.2),
    ),
    color="red",
    line_style="-",
    built_in=True,
)

BUILTIN_TOOLS: dict[str, ToolProfile] = {
    KPS_TOOL.id: KPS_TOOL,
    EXPERIMENTAL_TOOL.id: EXPERIMENTAL_TOOL,
}

BUILTIN_TOOL_IDS = frozenset(BUILTIN_TOOLS)
