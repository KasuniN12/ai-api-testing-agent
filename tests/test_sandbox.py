"""Unit tests for the Docker ExecutionSandbox module."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import docker.errors
from execution.sandbox import ExecutionSandbox, SandboxResult
from execution.test_executor import TestExecutor
from models.schemas import ScenarioType, TestCase, TestSuite


def test_sandbox_offline_detection():
    """Verify is_available returns False when Docker daemon is offline."""
    sandbox = ExecutionSandbox()
    with patch.object(sandbox, "_get_client", return_value=None):
        assert not sandbox.is_available()


def test_sandbox_online_detection_mock():
    """Verify is_available returns True when Docker daemon pings successfully."""
    mock_client = MagicMock()
    mock_client.ping.return_value = True

    sandbox = ExecutionSandbox()
    with patch.object(sandbox, "_get_client", return_value=mock_client):
        assert sandbox.is_available()


def test_sandbox_run_isolated_file_not_found():
    """Verify error returned when test script path does not exist."""
    sandbox = ExecutionSandbox()
    res = sandbox.run_isolated(Path("non_existent_test.py"))
    assert not res.sandboxed
    assert "not found" in str(res.error).lower()


def test_sandbox_run_isolated_offline():
    """Verify clean error returned when Docker is unavailable."""
    sandbox = ExecutionSandbox()
    temp_file = Path("artifacts/generated_tests/.gitkeep")

    with patch.object(sandbox, "is_available", return_value=False):
        res = sandbox.run_isolated(temp_file)
        assert not res.sandboxed
        assert "not reachable" in str(res.error).lower()


def test_sandbox_run_isolated_success_mock(tmp_path):
    """Verify container run execution and volume mount security options."""
    test_file = tmp_path / "test_dummy.py"
    test_file.write_text("def test_dummy(): pass", encoding="utf-8")

    mock_client = MagicMock()
    mock_client.containers.run.return_value = b"================ 1 passed in 0.05s ================\n"

    sandbox = ExecutionSandbox()
    with patch.object(sandbox, "is_available", return_value=True), patch.object(
        sandbox, "_get_client", return_value=mock_client
    ):
        result = sandbox.run_isolated(test_file)

        assert result.sandboxed
        assert result.exit_code == 0
        assert "1 passed" in result.output

        # Verify security parameters passed to containers.run
        mock_client.containers.run.assert_called_once()
        _, kwargs = mock_client.containers.run.call_args
        assert kwargs["security_opt"] == ["no-new-privileges:true"]
        assert kwargs["remove"] is True
        assert kwargs["mem_limit"] == "256m"
        assert kwargs["network_mode"] == "host"

        # Verify read-only volume mount mode
        mount_info = next(iter(kwargs["volumes"].values()))
        assert mount_info["mode"] == "ro"


def test_sandbox_run_isolated_container_error_mock(tmp_path):
    """Verify ContainerError is captured with exit code and stderr."""
    test_file = tmp_path / "test_failing.py"
    test_file.write_text("def test_fail(): assert False", encoding="utf-8")

    mock_client = MagicMock()
    mock_client.containers.run.side_effect = docker.errors.ContainerError(
        container=MagicMock(),
        exit_status=1,
        command="pytest",
        image="python:3.11-slim",
        stderr=b"AssertionError in test_fail",
    )

    sandbox = ExecutionSandbox()
    with patch.object(sandbox, "is_available", return_value=True), patch.object(
        sandbox, "_get_client", return_value=mock_client
    ):
        result = sandbox.run_isolated(test_file)

        assert result.sandboxed
        assert result.exit_code == 1
        assert "AssertionError" in result.output


def test_executor_incorporates_docker_sandbox_status():
    """Verify TestExecutor incorporates Docker sandbox status when enabled."""
    mock_sandbox = MagicMock(spec=ExecutionSandbox)
    mock_sandbox.is_available.return_value = True
    mock_sandbox.run_isolated.return_value = SandboxResult(
        exit_code=0,
        output="Mocked container output",
        duration_seconds=0.15,
        sandboxed=True,
    )

    executor = TestExecutor(enable_sandbox=True)
    executor.sandbox = mock_sandbox

    suite = TestSuite(
        suite_version="V1",
        iteration=1,
        generated_code="import pytest\ndef test_ok(): pass",
        test_cases=[
            TestCase(
                test_id="TC-001",
                endpoint_path="/api/test",
                http_method="GET",
                scenario_type=ScenarioType.POSITIVE,
                description="Sandbox test",
                expected_status=200,
            )
        ],
    )

    with patch("httpx.Client.request") as mock_req:
        mock_req.return_value = MagicMock(status_code=200, json=lambda: {})
        report = executor.execute(suite, "http://localhost:8000")

        assert "[DOCKER SANDBOX ACTIVE]" in report.raw_output
        mock_sandbox.run_isolated.assert_called_once()


def test_sandbox_fallback_execution_when_docker_offline(tmp_path):
    """Verify ExecutionSandbox seamlessly executes test locally when Docker is offline."""
    test_file = tmp_path / "test_local.py"
    test_file.write_text("def test_success(): assert 1 == 1\n", encoding="utf-8")

    sandbox = ExecutionSandbox()
    with patch.object(sandbox, "is_available", return_value=False):
        res = sandbox.run_isolated(test_file, fallback_to_local=True)

        assert not res.sandboxed
        assert res.fallback_used is True
        assert res.exit_code == 0
        assert "1 passed" in res.output


def test_executor_incorporates_docker_sandbox_fallback_notice():
    """Verify TestExecutor records fallback notice when Docker sandbox falls back to local runner."""
    mock_sandbox = MagicMock(spec=ExecutionSandbox)
    mock_sandbox.run_isolated.return_value = SandboxResult(
        exit_code=0,
        output="Local fallback output",
        duration_seconds=0.10,
        sandboxed=False,
        fallback_used=True,
        error="Docker daemon offline",
    )

    executor = TestExecutor(enable_sandbox=True)
    executor.sandbox = mock_sandbox

    suite = TestSuite(
        suite_version="V1",
        iteration=1,
        generated_code="import pytest\ndef test_fallback(): pass",
        test_cases=[
            TestCase(
                test_id="TC-001",
                endpoint_path="/api/test",
                http_method="GET",
                scenario_type=ScenarioType.POSITIVE,
                description="Sandbox fallback test",
                expected_status=200,
            )
        ],
    )

    with patch("httpx.Client.request") as mock_req:
        mock_req.return_value = MagicMock(status_code=200, json=lambda: {})
        report = executor.execute(suite, "http://localhost:8000")

        assert "[DOCKER SANDBOX FALLBACK]" in report.raw_output
        mock_sandbox.run_isolated.assert_called_once()
