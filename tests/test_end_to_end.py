"""End-to-end integration tests for AI API Testing Agent.

Validates the complete execution flow from OpenAPI specification parsing through
iterative reflection, refinement, and final trajectory evaluation against a live API.
"""

from http.server import HTTPServer
import os
from pathlib import Path
import subprocess
import sys
import threading
import pytest
import httpx

from core.loop_orchestrator import IterativeQAOrchestrator
from examples.mock_server import MockAPIHandler
from models.schemas import StoppingConditionReason

TEST_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TEST_DIR.parent
SPEC_PATH = str(PROJECT_ROOT / "examples" / "sample_openapi.json")


@pytest.fixture(scope="module")
def live_mock_server():
    """Ensure a live mock server is running for end-to-end integration tests."""
    host = "127.0.0.1"
    port = 8899
    base_url = f"http://{host}:{port}"

    server = HTTPServer((host, port), MockAPIHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    # Wait for server readiness
    ready = False
    for _ in range(20):
        try:
            r = httpx.get(f"{base_url}/api/reset", timeout=0.5)
            if r.status_code == 200:
                ready = True
                break
        except Exception:
            pass
    assert ready, "Failed to start mock API server for E2E testing"

    yield base_url

    server.shutdown()
    server.server_close()


def test_end_to_end_orchestrator_live_api(live_mock_server):
    """Test full orchestrator execution loop against live API server."""
    orchestrator = IterativeQAOrchestrator(
        enable_sandbox=False,
    )

    events_received = []

    def tracking_callback(event: str, data: any):
        events_received.append(event)

    spec, history, comparison = orchestrator.run(
        spec_path=SPEC_PATH,
        target_url=live_mock_server,
        max_iterations=2,
        target_coverage=95.0,
        target_quality=0.95,
        callback=tracking_callback,
    )

    # 1. Spec parsing verification
    assert spec is not None
    assert spec.title == "Sample User Management API"
    assert len(spec.endpoints) == 4

    # 2. Iteration history verification
    assert len(history) == 2
    v1_result = history[0]
    v2_result = history[1]

    assert v1_result.suite_version == "V1"
    assert v2_result.suite_version == "V2"
    assert v2_result.total_tests > v1_result.total_tests
    assert v2_result.edge_cases_count >= v1_result.edge_cases_count

    # 3. Reflection feedback verification
    assert v1_result.reflection_feedback is not None
    assert 0.0 <= v1_result.reflection_feedback.quality_score <= 1.0
    assert len(v1_result.reflection_feedback.identified_issues) > 0

    # 4. Comparison verification
    assert comparison is not None
    assert comparison.v1_total == v1_result.total_tests
    assert comparison.v2_total == v2_result.total_tests
    assert comparison.new_edge_cases_count >= 0
    assert comparison.stopping_reason == StoppingConditionReason.MAX_ITERATIONS

    # 5. Pipeline events verification
    assert "spec_parsing" in events_received
    assert "v1_generation_start" in events_received
    assert "execution_completed" in events_received
    assert "reflection_completed" in events_received
    assert "improvement_completed" in events_received
    assert "iteration_halted" in events_received


def test_end_to_end_cli_main_execution(live_mock_server):
    """Test full CLI pipeline execution via subprocess."""
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "main.py"),
        "--spec",
        SPEC_PATH,
        "--url",
        live_mock_server,
        "--max-iterations",
        "2",
        "--target-coverage",
        "99.0",
        "--target-quality",
        "0.99",
    ]

    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, f"CLI exited with error:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    stdout = result.stdout

    assert "AI API Testing & Iterative Self-Improving QA Agent" in stdout
    assert "Sample User Management API" in stdout
    assert "Cycle 1: Suite V1" in stdout
    assert "Cycle 2: Suite V2" in stdout
    assert "Reflection Feedback" in stdout
    assert "=== Iterative QA Lifecycle Final Evaluation ===" in stdout
    assert "Halt Condition:" in stdout


def test_end_to_end_offline_api_resilience():
    """Verify that the full orchestrator handles unreachable API targets gracefully."""
    orchestrator = IterativeQAOrchestrator(
        enable_sandbox=False,
    )

    # Use a port where no server is listening
    offline_url = "http://127.0.0.1:59199"

    spec, history, comparison = orchestrator.run(
        spec_path=SPEC_PATH,
        target_url=offline_url,
        max_iterations=1,
    )

    assert len(history) == 1
    res = history[0]
    assert res.error_count > 0 or res.failed_count > 0
    assert res.passed_count == 0
    assert comparison is not None
