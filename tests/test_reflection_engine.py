"""Unit tests for ReflectionEngine analyzing execution evidence and detecting gaps."""

from unittest.mock import MagicMock
from core.llm_client import LLMClient
from core.reflection_engine import ReflectionEngine
from models.schemas import (
    APIEndpoint,
    APISpecification,
    IterationResult,
    ReflectionFeedback,
    ReflectionFinding,
    ScenarioType,
    TestCase,
    TestExecutionResult,
    TestSuite,
)


def _make_sample_spec() -> APISpecification:
    return APISpecification(
        title="Sample Users API",
        version="1.0.0",
        base_url="http://127.0.0.1:8000",
        endpoints=[
            APIEndpoint(
                path="/api/users",
                method="GET",
                summary="List all users",
                parameters=[],
                responses={"200": {"description": "List returned"}},
            ),
            APIEndpoint(
                path="/api/users",
                method="POST",
                summary="Create user",
                request_body_schema={
                    "type": "object",
                    "required": ["name", "email"],
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string", "format": "email"},
                    },
                },
                responses={"201": {"description": "User created"}},
            ),
            APIEndpoint(
                path="/api/users/{id}",
                method="GET",
                summary="Get user by id",
                parameters=[{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                responses={"200": {"description": "User details"}, "404": {"description": "Not found"}},
            ),
            APIEndpoint(
                path="/api/admin/users/{id}",
                method="DELETE",
                summary="Admin delete user",
                parameters=[{"name": "id", "in": "path", "required": True}],
                requires_auth=True,
                responses={"204": {"description": "Deleted"}, "401": {"description": "Unauthorized"}},
            ),
        ],
    )


def test_reflection_detects_server_500_defects():
    """Verify reflection engine flags HTTP 500 status as a server defect finding."""
    engine = ReflectionEngine()
    spec = _make_sample_spec()
    suite = TestSuite(
        suite_version="V1",
        iteration=1,
        test_cases=[
            TestCase(
                test_id="TC-001",
                endpoint_path="/api/users",
                http_method="POST",
                scenario_type=ScenarioType.POSITIVE,
                description="Valid user creation",
                expected_status=201,
            )
        ],
    )
    report = IterationResult(
        iteration=1,
        suite_version="V1",
        total_tests=1,
        passed_count=0,
        failed_count=1,
        error_count=0,
        coverage_percentage=25.0,
        execution_results=[
            TestExecutionResult(
                test_id="TC-001",
                endpoint_path="/api/users",
                http_method="POST",
                passed=False,
                status_code=500,
                response_body={"error": "Internal Server Crash"},
                error_message="Expected HTTP 201, received 500",
            )
        ],
    )

    feedback = engine.reflect(spec, suite, report)
    assert feedback is not None
    assert 0.0 <= feedback.quality_score <= 1.0

    categories = [f.category for f in feedback.identified_issues]
    assert "server_error" in categories


def test_reflection_identifies_missing_edge_cases_and_security():
    """Verify missing scenarios (boundary, empty input, invalid type, missing auth) are detected."""
    engine = ReflectionEngine()
    spec = _make_sample_spec()

    # Suite has only happy path GET /api/users
    suite = TestSuite(
        suite_version="V1",
        iteration=1,
        test_cases=[
            TestCase(
                test_id="TC-001",
                endpoint_path="/api/users",
                http_method="GET",
                scenario_type=ScenarioType.POSITIVE,
                description="List users",
                expected_status=200,
            )
        ],
    )
    report = IterationResult(
        iteration=1,
        suite_version="V1",
        total_tests=1,
        passed_count=1,
        failed_count=0,
        coverage_percentage=25.0,
        execution_results=[
            TestExecutionResult(
                test_id="TC-001",
                endpoint_path="/api/users",
                http_method="GET",
                passed=True,
                status_code=200,
            )
        ],
    )

    feedback = engine.reflect(spec, suite, report)

    # Missing scenarios should be identified
    assert len(feedback.missing_scenarios) > 0
    missing_text = " ".join(feedback.missing_scenarios)
    assert "boundary" in missing_text
    assert "empty_input" in missing_text
    assert "missing_auth" in missing_text

    # Untested endpoints should appear in coverage gaps
    assert any("DELETE" in gap for gap in feedback.coverage_gaps)


def test_reflection_engine_with_mocked_llm():
    """Verify LLM structured reflection is integrated when LLM is configured."""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.is_configured = True
    mock_llm.structured_completion.return_value = ReflectionFeedback(
        iteration=1,
        identified_issues=[
            ReflectionFinding(
                category="llm_insight",
                endpoint="/api/users",
                observation="SQL injection boundary check needed on query params",
                evidence="No query parameter sanitization tests found",
                recommended_action="Inject quotes and SQL syntax into filter params",
            )
        ],
        missing_scenarios=["GET /api/users missing scenario: boundary"],
        coverage_gaps=[],
        reflection_summary="LLM analyzed execution and spotted subtle attack vectors.",
        quality_score=0.75,
    )

    engine = ReflectionEngine(llm_client=mock_llm)
    spec = _make_sample_spec()
    suite = TestSuite(suite_version="V1", iteration=1, test_cases=[])
    report = IterationResult(iteration=1, suite_version="V1")

    feedback = engine.reflect(spec, suite, report)
    assert feedback.quality_score >= 0.0
    assert any(i.category == "llm_insight" for i in feedback.identified_issues)
