"""Unit tests for IterativeQAOrchestrator and stopping condition mechanics."""

from unittest.mock import MagicMock, patch
from core.loop_orchestrator import IterativeQAOrchestrator
from models.schemas import (
    APIEndpoint,
    APISpecification,
    IterationResult,
    ReflectionFeedback,
    ScenarioType,
    StoppingConditionReason,
    TestCase,
    TestExecutionResult,
    TestSuite,
)


def _make_spec() -> APISpecification:
    return APISpecification(
        title="Orchestrator API",
        version="1.0.0",
        base_url="http://127.0.0.1:8000",
        endpoints=[
            APIEndpoint(path="/api/data", method="GET", responses={"200": {}}),
        ],
    )


@patch("core.loop_orchestrator.OpenAPIParser")
def test_orchestrator_stops_at_max_iterations(mock_parser_cls):
    """Verify orchestrator halts loop when max_iterations limit is reached."""
    mock_parser = MagicMock()
    mock_parser.parse.return_value = _make_spec()
    mock_parser_cls.return_value = mock_parser

    orchestrator = IterativeQAOrchestrator()

    # Mock generator
    orchestrator.generator.generate_initial_suite = MagicMock(
        return_value=TestSuite(
            suite_version="V1",
            iteration=1,
            test_cases=[
                TestCase(
                    test_id="TC-001",
                    endpoint_path="/api/data",
                    http_method="GET",
                    scenario_type=ScenarioType.POSITIVE,
                    description="Test data endpoint",
                    expected_status=200,
                )
            ],
        )
    )

    # Mock executor to return low coverage so it doesn't trigger TARGET_REACHED
    def fake_execute(suite, base_url):
        return IterationResult(
            iteration=suite.iteration,
            suite_version=suite.suite_version,
            total_tests=len(suite.test_cases),
            passed_count=len(suite.test_cases),
            coverage_percentage=40.0,
            edge_cases_count=suite.iteration,  # grows each time to avoid CONVERGENCE
            execution_results=[
                TestExecutionResult(
                    test_id=f"TC-{i}",
                    endpoint_path="/api/data",
                    http_method="GET",
                    passed=True,
                    status_code=200,
                )
                for i in range(len(suite.test_cases))
            ],
        )

    orchestrator.executor.execute = MagicMock(side_effect=fake_execute)

    # Mock reflector to return quality_score below target
    orchestrator.reflector.reflect = MagicMock(
        side_effect=lambda spec, suite, rep: ReflectionFeedback(
            iteration=suite.iteration,
            quality_score=0.5,
            reflection_summary="Iteration ongoing",
        )
    )

    # Mock improver to add an extra test case each cycle
    def fake_improver(spec, current_suite, reflection, base_url):
        next_iter = current_suite.iteration + 1
        return TestSuite(
            suite_version=f"V{next_iter}",
            iteration=next_iter,
            test_cases=current_suite.test_cases + [
                TestCase(
                    test_id=f"TC-{next_iter:03d}",
                    endpoint_path="/api/data",
                    http_method="GET",
                    scenario_type=ScenarioType.BOUNDARY,
                    description=f"Boundary test for cycle {next_iter}",
                    expected_status=200,
                )
            ],
        )

    orchestrator.improver.generate_improved_suite = MagicMock(side_effect=fake_improver)

    spec, history, comparison = orchestrator.run(
        spec_path="fake_path.json",
        target_url="http://127.0.0.1:8000",
        max_iterations=3,
        target_coverage=95.0,
        target_quality=0.90,
    )

    assert len(history) == 3
    assert history[-1].stopping_condition_met is True
    assert history[-1].stopping_reason == StoppingConditionReason.MAX_ITERATIONS
    assert comparison.final_iteration == 3


@patch("core.loop_orchestrator.OpenAPIParser")
def test_orchestrator_stops_at_target_reached(mock_parser_cls):
    """Verify orchestrator halts immediately when coverage and quality targets are achieved."""
    mock_parser = MagicMock()
    mock_parser.parse.return_value = _make_spec()
    mock_parser_cls.return_value = mock_parser

    orchestrator = IterativeQAOrchestrator()

    orchestrator.generator.generate_initial_suite = MagicMock(
        return_value=TestSuite(suite_version="V1", iteration=1, test_cases=[])
    )

    # Return high coverage right on iteration 1
    orchestrator.executor.execute = MagicMock(
        return_value=IterationResult(
            iteration=1,
            suite_version="V1",
            total_tests=5,
            passed_count=5,
            coverage_percentage=95.0,
            edge_cases_count=3,
        )
    )

    orchestrator.reflector.reflect = MagicMock(
        return_value=ReflectionFeedback(
            iteration=1,
            quality_score=0.92,
            reflection_summary="Targets exceeded",
        )
    )

    spec, history, comparison = orchestrator.run(
        spec_path="fake_path.json",
        max_iterations=5,
        target_coverage=90.0,
        target_quality=0.85,
    )

    assert len(history) == 1
    assert history[0].stopping_condition_met is True
    assert history[0].stopping_reason == StoppingConditionReason.TARGET_REACHED


@patch("core.loop_orchestrator.OpenAPIParser")
def test_orchestrator_stops_at_convergence(mock_parser_cls):
    """Verify orchestrator halts when no new edge cases or coverage improvements occur."""
    mock_parser = MagicMock()
    mock_parser.parse.return_value = _make_spec()
    mock_parser_cls.return_value = mock_parser

    orchestrator = IterativeQAOrchestrator()

    orchestrator.generator.generate_initial_suite = MagicMock(
        return_value=TestSuite(suite_version="V1", iteration=1, test_cases=[])
    )

    # Identical metrics for both iteration 1 and 2 (plateau / convergence)
    orchestrator.executor.execute = MagicMock(
        side_effect=[
            IterationResult(
                iteration=1,
                suite_version="V1",
                total_tests=3,
                passed_count=3,
                coverage_percentage=70.0,
                edge_cases_count=1,
            ),
            IterationResult(
                iteration=2,
                suite_version="V2",
                total_tests=3,
                passed_count=3,
                coverage_percentage=70.0,
                edge_cases_count=1,
            ),
        ]
    )

    orchestrator.reflector.reflect = MagicMock(
        return_value=ReflectionFeedback(
            iteration=1,
            quality_score=0.70,
            reflection_summary="Plateau",
        )
    )

    orchestrator.improver.generate_improved_suite = MagicMock(
        return_value=TestSuite(suite_version="V2", iteration=2, test_cases=[])
    )

    spec, history, comparison = orchestrator.run(
        spec_path="fake_path.json",
        max_iterations=5,
        target_coverage=90.0,
        target_quality=0.90,
    )

    assert len(history) == 2
    assert history[1].stopping_condition_met is True
    assert history[1].stopping_reason == StoppingConditionReason.CONVERGENCE
