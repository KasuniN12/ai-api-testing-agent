"""Unit tests for evaluation metrics and delta calculations."""

from evaluation.metrics import (
    calculate_coverage_delta,
    calculate_defect_detection_rate,
    calculate_edge_case_growth,
    calculate_quality_trajectory,
)
from models.schemas import IterationResult, StoppingConditionReason, TestExecutionResult


def test_calculate_coverage_delta():
    assert calculate_coverage_delta(50.0, 75.5) == 25.5
    assert calculate_coverage_delta(80.0, 80.0) == 0.0
    assert calculate_coverage_delta(90.0, 85.0) == -5.0


def test_calculate_defect_detection_rate():
    assert calculate_defect_detection_rate([]) == 0.0

    results = [
        TestExecutionResult(test_id="1", endpoint_path="/api", http_method="GET", passed=True),
        TestExecutionResult(test_id="2", endpoint_path="/api", http_method="GET", passed=False),
        TestExecutionResult(test_id="3", endpoint_path="/api", http_method="GET", passed=True),
        TestExecutionResult(test_id="4", endpoint_path="/api", http_method="GET", passed=False),
    ]
    assert calculate_defect_detection_rate(results) == 50.0


def test_calculate_edge_case_growth():
    assert calculate_edge_case_growth(2, 7) == 5
    assert calculate_edge_case_growth(5, 5) == 0
    assert calculate_edge_case_growth(6, 4) == 0


def test_calculate_quality_trajectory():
    iterations = [
        IterationResult(
            iteration=1,
            suite_version="V1",
            total_tests=5,
            passed_count=5,
            coverage_percentage=50.0,
            edge_cases_count=2,
        ),
        IterationResult(
            iteration=2,
            suite_version="V2",
            total_tests=9,
            passed_count=8,
            failed_count=1,
            coverage_percentage=85.0,
            edge_cases_count=6,
            stopping_condition_met=True,
            stopping_reason=StoppingConditionReason.TARGET_REACHED,
        ),
    ]

    traj = calculate_quality_trajectory(iterations)
    assert len(traj) == 2
    assert traj[0]["iteration"] == 1
    assert traj[0]["total_tests"] == 5
    assert traj[1]["stopping_condition_met"] is True
    assert traj[1]["stopping_reason"] == StoppingConditionReason.TARGET_REACHED.value
