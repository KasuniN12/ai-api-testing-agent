"""Unit tests validating schema constraints and improvements."""

import pytest
from pydantic import ValidationError
from models.schemas import (
    ScenarioType,
    TestCase,
    ReflectionFeedback,
    IterationResult,
    TestExecutionResult,
)


def test_testcase_scenario_type_enum():
    """Verify TestCase scenario_type uses ScenarioType enum."""
    tc = TestCase(
        test_id="TC-001",
        endpoint_path="/api/users",
        http_method="POST",
        description="Create user with empty body",
        scenario_type=ScenarioType.EMPTY_INPUT,
        expected_status=400,
    )
    assert tc.scenario_type == ScenarioType.EMPTY_INPUT

    # Test default scenario type is POSITIVE
    tc_default = TestCase(
        test_id="TC-002",
        endpoint_path="/api/users",
        http_method="GET",
        description="List users",
        expected_status=200,
    )
    assert tc_default.scenario_type == ScenarioType.POSITIVE

    # Invalid scenario type should raise ValidationError
    with pytest.raises(ValidationError):
        TestCase(
            test_id="TC-003",
            endpoint_path="/api/users",
            http_method="GET",
            description="Invalid scenario",
            scenario_type="non_existent_type",
            expected_status=200,
        )


def test_reflection_feedback_quality_score_bounds():
    """Verify quality_score must be between 0.0 and 1.0."""
    valid_rf = ReflectionFeedback(iteration=1, quality_score=0.85)
    assert valid_rf.quality_score == 0.85

    # Out of bounds (< 0.0)
    with pytest.raises(ValidationError):
        ReflectionFeedback(iteration=1, quality_score=-0.1)

    # Out of bounds (> 1.0)
    with pytest.raises(ValidationError):
        ReflectionFeedback(iteration=1, quality_score=1.5)


def test_iteration_result_coverage_fields():
    """Verify IterationResult contains scenario coverage fields and execution_results."""
    result = IterationResult(
        iteration=1,
        suite_version="V1",
        total_tests=10,
        passed_count=8,
        failed_count=2,
        total_scenarios=15,
        covered_scenarios=10,
        edge_cases_count=4,
        execution_results=[
            TestExecutionResult(test_id="TC-01", passed=True, status_code=200),
            TestExecutionResult(test_id="TC-02", passed=False, status_code=500),
        ],
    )
    assert result.total_scenarios == 15
    assert result.covered_scenarios == 10
    assert result.edge_cases_count == 4
    assert len(result.execution_results) == 2
