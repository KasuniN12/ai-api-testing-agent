"""Unit tests for TestImprover synthesizing improved test suites (V2..Vn)."""

from unittest.mock import MagicMock
from core.llm_client import LLMClient
from core.test_improver import TestImprover
from models.schemas import (
    APIEndpoint,
    APISpecification,
    ReflectionFeedback,
    ReflectionFinding,
    ScenarioType,
    TestCase,
    TestSuite,
)


def _make_spec() -> APISpecification:
    return APISpecification(
        title="Test Store API",
        version="1.0.0",
        base_url="http://127.0.0.1:8000",
        endpoints=[
            APIEndpoint(
                path="/api/items",
                method="GET",
                parameters=[],
                responses={"200": {}},
            ),
            APIEndpoint(
                path="/api/items",
                method="POST",
                request_body_schema={
                    "type": "object",
                    "required": ["title", "price"],
                    "properties": {
                        "title": {"type": "string"},
                        "price": {"type": "number"},
                    },
                },
                responses={"201": {}},
            ),
            APIEndpoint(
                path="/api/items/{id}",
                method="GET",
                parameters=[{"name": "id", "in": "path", "required": True}],
                responses={"200": {}, "404": {}},
            ),
        ],
    )


def test_test_improver_generates_v2_from_v1_and_reflection():
    """Verify TestImprover retains V1 tests and adds missing boundary/edge cases into V2."""
    improver = TestImprover()
    spec = _make_spec()

    # V1 initial suite
    v1_suite = TestSuite(
        suite_version="V1",
        iteration=1,
        test_cases=[
            TestCase(
                test_id="TC-001",
                endpoint_path="/api/items",
                http_method="GET",
                scenario_type=ScenarioType.POSITIVE,
                description="List items",
                expected_status=200,
            )
        ],
    )

    # Reflection indicating missing boundary & empty input
    reflection = ReflectionFeedback(
        iteration=1,
        missing_scenarios=[
            "GET /api/items/{id} missing scenario: boundary",
            "POST /api/items missing scenario: empty_input",
            "POST /api/items missing scenario: invalid_type",
        ],
        identified_issues=[
            ReflectionFinding(
                category="missing_edge_case",
                endpoint="/api/items/{id}",
                observation="Lacks negative ID boundary test",
                evidence="No ID tests",
                recommended_action="Add negative ID test",
            )
        ],
        quality_score=0.45,
    )

    v2_suite = improver.generate_improved_suite(spec, v1_suite, reflection)

    # Assertions on V2 suite
    assert v2_suite.suite_version == "V2"
    assert v2_suite.iteration == 2
    assert len(v2_suite.test_cases) > len(v1_suite.test_cases)

    # TC-001 must be preserved
    ids = [tc.test_id for tc in v2_suite.test_cases]
    assert "TC-001" in ids

    # Newly added scenarios
    scenarios = {tc.scenario_type for tc in v2_suite.test_cases}
    assert ScenarioType.BOUNDARY in scenarios
    assert ScenarioType.EMPTY_INPUT in scenarios
    assert ScenarioType.INVALID_TYPE in scenarios

    # Check generated Pytest code is valid Python syntax
    assert "def test_" in v2_suite.generated_code
    assert 'BASE_URL = "http://127.0.0.1:8000"' in v2_suite.generated_code
    compile(v2_suite.generated_code, "<string>", "exec")


def test_test_improver_queries_llm_when_configured():
    """Verify LLM query for additional edge cases runs when LLM is configured."""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.is_configured = True

    from core.test_generator import GeneratedTestCasesPayload

    mock_llm.structured_completion.return_value = GeneratedTestCasesPayload(
        test_cases=[
            TestCase(
                test_id="TC-LLM-1",
                endpoint_path="/api/items",
                http_method="POST",
                scenario_type=ScenarioType.BOUNDARY,
                description="LLM discovered price overflow boundary",
                body={"title": "Item", "price": 999999999.99},
                expected_status=400,
            )
        ]
    )

    improver = TestImprover(llm_client=mock_llm)
    spec = _make_spec()
    v1_suite = TestSuite(suite_version="V1", iteration=1, test_cases=[])
    reflection = ReflectionFeedback(iteration=1)

    v2_suite = improver.generate_improved_suite(spec, v1_suite, reflection)
    assert any("price overflow" in tc.description for tc in v2_suite.test_cases)
