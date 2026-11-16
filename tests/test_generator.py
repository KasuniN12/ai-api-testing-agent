"""Unit tests for the TestGenerator (V1) module covering structured data and multi-scenarios."""

from pathlib import Path
from unittest.mock import MagicMock
from core.api_parser import OpenAPIParser
from core.test_generator import TestGenerator, GeneratedTestCasesPayload
from core.llm_client import LLMClient
from models.schemas import ScenarioType, TestCase


def test_generator_creates_multi_scenario_baseline():
    """Verify test generation without external LLM produces multi-scenario test cases."""
    spec_path = Path("examples/sample_openapi.json")
    spec = OpenAPIParser(spec_path).parse()

    generator = TestGenerator(llm_client=LLMClient(api_key=""))
    suite = generator.generate_initial_suite(spec, "http://localhost:8000")

    assert suite.suite_version == "V1"
    assert suite.iteration == 1

    # Verify that multiple scenario types are present
    scenarios_present = {tc.scenario_type for tc in suite.test_cases}
    assert ScenarioType.POSITIVE in scenarios_present
    assert ScenarioType.EMPTY_INPUT in scenarios_present
    assert ScenarioType.INVALID_TYPE in scenarios_present
    assert ScenarioType.BOUNDARY in scenarios_present

    # Verify coverage count is significantly higher than just 4 positive tests
    assert len(suite.test_cases) >= 8

    # Verify realistic email in positive POST request body
    post_cases = [tc for tc in suite.test_cases if tc.http_method == "POST" and tc.scenario_type == ScenarioType.POSITIVE]
    assert len(post_cases) > 0
    assert post_cases[0].body is not None
    assert "@" in post_cases[0].body.get("email", "")

    # Verify code compilation to guarantee valid Python syntax
    compiled = compile(suite.generated_code, "<test_suite_v1>", "exec")
    assert compiled is not None


def test_generator_with_mocked_structured_llm():
    """Verify test generation with mocked structured LLM parsing."""
    spec_path = Path("examples/sample_openapi.json")
    spec = OpenAPIParser(spec_path).parse()

    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.is_configured.return_value = True

    mock_payload = GeneratedTestCasesPayload(
        test_cases=[
            TestCase(
                test_id="TC-LLM-001",
                endpoint_path="/api/users",
                http_method="GET",
                scenario_type=ScenarioType.POSITIVE,
                description="LLM generated positive list users",
                expected_status=200,
            ),
            TestCase(
                test_id="TC-LLM-002",
                endpoint_path="/api/users",
                http_method="POST",
                scenario_type=ScenarioType.EMPTY_INPUT,
                description="LLM generated missing fields validation",
                body={},
                expected_status=400,
            ),
        ]
    )
    mock_llm.generate_structured.return_value = mock_payload

    generator = TestGenerator(llm_client=mock_llm)
    suite = generator.generate_initial_suite(spec, "http://localhost:8000")

    assert suite.suite_version == "V1"
    assert len(suite.test_cases) == 2
    assert suite.test_cases[0].test_id == "TC-LLM-001"
    assert suite.test_cases[1].scenario_type == ScenarioType.EMPTY_INPUT

    # Verify application synthesized controlled, safe Pytest code
    assert "def test_tc_llm_001_get_api_users_positive():" in suite.generated_code
    assert "def test_tc_llm_002_post_api_users_empty_input():" in suite.generated_code
    assert "httpx.get" in suite.generated_code
    assert "httpx.post" in suite.generated_code


def test_build_pytest_code_resolves_path_overrides():
    """Verify application-side Pytest builder handles boundary path parameter overrides."""
    generator = TestGenerator()
    test_cases = [
        TestCase(
            test_id="TC-099",
            endpoint_path="/api/users/{id}",
            http_method="GET",
            scenario_type=ScenarioType.BOUNDARY,
            description="Test non-existent ID",
            query_params={"_path_override": {"id": "99999"}},
            expected_status=404,
        )
    ]
    code = generator.build_pytest_code(test_cases, "http://localhost:8000")
    assert "/api/users/99999" in code
    assert "assert response.status_code == 404" in code
