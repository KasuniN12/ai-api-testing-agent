"""Unit tests for the TestExecutor execution engine."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import httpx
from execution.test_executor import TestExecutor
from models.schemas import ScenarioType, TestCase, TestSuite


def test_test_executor_initialization():
    executor = TestExecutor(timeout=15)
    assert executor.timeout == 15
    assert executor.generated_tests_dir.exists()
    assert executor.reports_dir.exists()


def test_test_executor_saves_suite_file(tmp_path):
    executor = TestExecutor(timeout=10)
    executor.generated_tests_dir = tmp_path

    suite = TestSuite(
        suite_version="V1",
        iteration=1,
        generated_code="import pytest\ndef test_hello(): pass",
        test_cases=[],
    )
    saved = executor.save_test_file(suite)

    assert saved.exists()
    assert saved.name == "test_v1_iter1.py"
    assert "def test_hello" in saved.read_text(encoding="utf-8")


def test_test_executor_with_mocked_responses():
    """Verify execution metrics calculation with mocked HTTP responses."""
    executor = TestExecutor()

    suite = TestSuite(
        suite_version="V1",
        iteration=1,
        generated_code="# code",
        test_cases=[
            TestCase(
                test_id="TC-001",
                endpoint_path="/api/users",
                http_method="GET",
                scenario_type=ScenarioType.POSITIVE,
                description="List users positive",
                expected_status=200,
            ),
            TestCase(
                test_id="TC-002",
                endpoint_path="/api/users",
                http_method="POST",
                scenario_type=ScenarioType.EMPTY_INPUT,
                description="Empty body validation",
                body={},
                expected_status=400,
            ),
            TestCase(
                test_id="TC-003",
                endpoint_path="/api/users/99999",
                http_method="GET",
                scenario_type=ScenarioType.BOUNDARY,
                description="Boundary not found",
                expected_status=404,
            ),
        ],
    )

    # Mock responses for TC-001 (200 PASS), TC-002 (400 PASS), TC-003 (500 FAIL - unexpected status)
    mock_resp_1 = MagicMock(status_code=200, json=lambda: {"users": []})
    mock_resp_2 = MagicMock(status_code=400, json=lambda: {"error": "empty body"})
    mock_resp_3 = MagicMock(status_code=500, json=lambda: {"error": "internal error"}, text="Server Error")

    with patch("httpx.Client.request") as mock_req:
        mock_req.side_effect = [mock_resp_1, mock_resp_2, mock_resp_3]

        report = executor.execute(suite, "http://localhost:8000")

        assert report.total_tests == 3
        assert report.passed_count == 2
        assert report.failed_count == 1
        assert report.error_count == 0
        assert report.edge_cases_count == 2  # EMPTY_INPUT and BOUNDARY
        assert report.total_scenarios == 3
        assert report.covered_scenarios == 2
        assert report.coverage_percentage == 66.7
        assert len(report.execution_results) == 3

        # Check third test failure recording
        failed_result = report.execution_results[2]
        assert not failed_result.passed
        assert failed_result.status_code == 500
        assert "Expected HTTP 404, received 500" in failed_result.error_message


def test_test_executor_handles_connection_error():
    """Verify network connection failures are gracefully recorded as test errors."""
    executor = TestExecutor()

    suite = TestSuite(
        suite_version="V1",
        iteration=1,
        generated_code="# code",
        test_cases=[
            TestCase(
                test_id="TC-CONN-01",
                endpoint_path="/api/users",
                http_method="GET",
                scenario_type=ScenarioType.POSITIVE,
                description="Test with offline server",
                expected_status=200,
            )
        ],
    )

    with patch("httpx.Client.request") as mock_req:
        mock_req.side_effect = httpx.ConnectError("Failed to establish a new connection")

        report = executor.execute(suite, "http://127.0.0.1:9999")

        assert report.total_tests == 1
        assert report.passed_count == 0
        assert report.failed_count == 0
        assert report.error_count == 1
        assert report.execution_results[0].status_code is None
        assert "Connection failed" in report.execution_results[0].error_message
