from __future__ import annotations

import pytest

from soil_tiller_calculator.calculations import (
    compare_tools,
    force_at_depth,
    optimize_speed,
    plot_speed_grid,
    power_and_fuel,
    specific_resistance,
    speed_grid,
)
from soil_tiller_calculator.models import ReferencePoint, ToolProfile


def test_force_matches_reference_points() -> None:
    assert force_at_depth(6, 10, "kps") == pytest.approx(367.8)
    assert force_at_depth(10, 10, "kps") == pytest.approx(403.5)
    assert force_at_depth(6, 10, "exp") == pytest.approx(429.7)
    assert force_at_depth(10, 10, "exp") == pytest.approx(544.2)


def test_force_interpolates_between_reference_points() -> None:
    assert force_at_depth(8, 10, "kps") == pytest.approx(385.65)
    assert force_at_depth(8, 10, "exp") == pytest.approx(486.95)


def test_force_extrapolates_outside_reference_points() -> None:
    assert force_at_depth(12, 10, "kps") == pytest.approx(421.35)
    assert force_at_depth(5, 10, "exp") == pytest.approx(401.075)


def test_force_scales_by_depth() -> None:
    assert force_at_depth(8, 20, "kps") == pytest.approx(771.3)
    assert force_at_depth(8, 5, "kps") == pytest.approx(192.825)


def test_specific_resistance_uses_tool_width() -> None:
    assert specific_resistance(8, 10, "kps") == pytest.approx(385.65 / 0.33)
    assert specific_resistance(8, 10, "exp") == pytest.approx(486.95 / 0.40)


def test_power_and_fuel_use_required_formulas() -> None:
    power, fuel = power_and_fuel(8, 10, "kps")
    expected_power = 385.65 * (8 / 3.6) / 1000
    expected_fuel = expected_power * 0.25 / 0.85
    assert power == pytest.approx(expected_power)
    assert fuel == pytest.approx(expected_fuel)


def test_speed_grids_are_inclusive() -> None:
    assert speed_grid()[0] == 5.0
    assert speed_grid()[-1] == 12.0
    assert len(speed_grid()) == 15
    assert plot_speed_grid(step=0.2)[0] == 5.0
    assert plot_speed_grid(step=0.2)[-1] == 12.0
    assert len(plot_speed_grid(step=0.2)) == 36


def test_speed_grid_never_exceeds_stop_with_uneven_step() -> None:
    assert speed_grid(5, 12, 2) == [5.0, 7.0, 9.0, 11.0, 12.0]
    assert plot_speed_grid(5, 12, 0.3)[-1] == pytest.approx(12.0)
    assert max(plot_speed_grid(5, 12, 0.3)) == pytest.approx(12.0)


def test_speed_grid_rejects_invalid_range_or_step() -> None:
    with pytest.raises(ValueError):
        speed_grid(5, 12, 0)
    with pytest.raises(ValueError):
        plot_speed_grid(12, 5, 0.2)


def test_optimize_speed_for_single_tool() -> None:
    result = optimize_speed(10, ["kps"])
    assert result.speed_kmh == pytest.approx(5.0)
    assert result.q_min == pytest.approx(specific_resistance(5, 10, "kps"))
    assert result.q_by_tool["kps"] == pytest.approx(result.q_min)


def test_optimize_speed_for_comparison_uses_average_q() -> None:
    result = optimize_speed(10, ["kps", "exp"])
    expected_average = (specific_resistance(5, 10, "kps") + specific_resistance(5, 10, "exp")) / 2
    assert result.speed_kmh == pytest.approx(5.0)
    assert result.q_min == pytest.approx(expected_average)
    assert set(result.q_by_tool) == {"kps", "exp"}


def test_optimize_speed_rejects_empty_tool_list() -> None:
    with pytest.raises(ValueError):
        optimize_speed(10, [])


def test_compare_tools_reports_better_tool_and_delta_against_first() -> None:
    result = compare_tools(10, 8, "kps", "exp")
    assert result.better_tool.id == "kps"
    assert result.first_q == pytest.approx(385.65 / 0.33)
    assert result.second_q == pytest.approx(486.95 / 0.40)
    assert result.difference_percent == pytest.approx(abs(result.second_q - result.first_q) / result.first_q * 100)


def test_compare_tools_handles_zero_depth_without_division_error() -> None:
    result = compare_tools(0, 8, "kps", "exp")
    assert result.first_q == pytest.approx(0.0)
    assert result.second_q == pytest.approx(0.0)
    assert result.difference_percent == pytest.approx(0.0)


def test_custom_tool_interpolates_across_nearest_segment() -> None:
    tool = ToolProfile(
        id="custom",
        name="Custom",
        width_m=0.5,
        base_depth_cm=10,
        reference_points=(
            ReferencePoint(5, 100),
            ReferencePoint(8, 160),
            ReferencePoint(12, 200),
        ),
    )
    assert force_at_depth(7, 10, tool) == pytest.approx(140)
    assert force_at_depth(10, 10, tool) == pytest.approx(180)


def test_unknown_tool_type_is_rejected() -> None:
    with pytest.raises(ValueError):
        force_at_depth(8, 10, "missing")
