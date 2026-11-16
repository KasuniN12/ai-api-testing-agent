"""Quantitative evaluation metrics for measuring Reflection Design Pattern effectiveness."""

from typing import Any, Dict, List
from models.schemas import IterationResult, TestExecutionResult


def calculate_coverage_delta(initial_cov: float, final_cov: float) -> float:
    """Calculate percentage delta in API endpoint scenario coverage."""
    return round(final_cov - initial_cov, 2)


def calculate_defect_detection_rate(results: List[TestExecutionResult]) -> float:
    """Calculate percentage of tests identifying non-passing execution evidence."""
    if not results:
        return 0.0
    failed_tests = [r for r in results if not r.passed]
    return round((len(failed_tests) / len(results)) * 100.0, 2)


def calculate_edge_case_growth(initial_edge_count: int, final_edge_count: int) -> int:
    """Calculate net increase in edge-case scenario tests across cycles."""
    return max(0, final_edge_count - initial_edge_count)


def calculate_quality_trajectory(iterations: List[IterationResult]) -> List[Dict[str, Any]]:
    """Generate trajectory points showing test suite evolution over iterations."""
    trajectory = []
    for it in iterations:
        q_score = (
            it.reflection_feedback.quality_score
            if it.reflection_feedback
            else 0.0
        )
        trajectory.append({
            "iteration": it.iteration,
            "suite_version": it.suite_version,
            "total_tests": it.total_tests,
            "passed_count": it.passed_count,
            "failed_count": it.failed_count,
            "error_count": it.error_count,
            "coverage_percentage": it.coverage_percentage,
            "edge_cases_count": it.edge_cases_count,
            "quality_score": q_score,
            "stopping_condition_met": it.stopping_condition_met,
            "stopping_reason": it.stopping_reason.value if it.stopping_reason else None,
        })
    return trajectory
