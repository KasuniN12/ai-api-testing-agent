"""Test Executor running generated test suites against target APIs and collecting execution evidence."""

from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional
import httpx
from config.settings import get_settings
from execution.sandbox import ExecutionSandbox
from models.schemas import (
    IterationResult,
    ScenarioType,
    TestCase,
    TestExecutionResult,
    TestSuite,
)


class TestExecutor:
    """Executes generated API test suites and collects structured execution evidence."""

    __test__ = False  # Prevent pytest from treating this as a test class

    def __init__(
        self,
        timeout: Optional[int] = None,
        enable_sandbox: Optional[bool] = None,
    ):
        self.settings = get_settings()
        self.timeout = timeout if timeout is not None else self.settings.EXECUTION_TIMEOUT
        self.enable_sandbox = (
            enable_sandbox
            if enable_sandbox is not None
            else self.settings.ENABLE_DOCKER_SANDBOX
        )
        self.sandbox = ExecutionSandbox(timeout=self.timeout)
        self.generated_tests_dir = Path(self.settings.GENERATED_TESTS_DIR)
        self.reports_dir = Path(self.settings.REPORTS_DIR)

        # Ensure directories exist
        self.generated_tests_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def save_test_file(self, suite: TestSuite) -> Path:
        """Persist generated Pytest code to disk in artifacts/generated_tests/."""
        version_tag = suite.suite_version.lower()
        file_name = f"test_{version_tag}_iter{suite.iteration}.py"
        file_path = self.generated_tests_dir / file_name
        file_path.write_text(suite.generated_code, encoding="utf-8")
        return file_path

    def execute_test_case(
        self, tc: TestCase, base_url: str, client: httpx.Client
    ) -> TestExecutionResult:
        """Execute a single TestCase against the live API and record structured evidence."""
        resolved_path = self._resolve_path(tc)
        clean_url = f"{base_url.rstrip('/')}{resolved_path}"
        method = tc.http_method.upper()

        clean_params = {
            k: v for k, v in tc.query_params.items() if k != "_path_override"
        }

        start_time = time.perf_counter()
        passed = False
        status_code: Optional[int] = None
        response_body: Optional[Any] = None
        error_message: Optional[str] = None

        try:
            response = client.request(
                method=method,
                url=clean_url,
                headers=tc.headers or None,
                params=clean_params or None,
                json=tc.body if tc.body is not None else None,
                timeout=float(self.timeout),
            )
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            status_code = response.status_code

            # Extract response payload
            try:
                response_body = response.json()
            except Exception:
                response_body = response.text[:500] if response.text else None

            # Evaluate assertions
            if status_code == tc.expected_status:
                passed = True
            else:
                passed = False
                error_message = (
                    f"Expected HTTP {tc.expected_status}, received {status_code}. "
                    f"Response: {str(response_body)[:200]}"
                )

        except httpx.ConnectError as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            error_message = f"Connection failed to {clean_url}. Is target API running? ({e})"
        except httpx.TimeoutException as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            error_message = f"Request timed out after {self.timeout}s ({e})"
        except httpx.HTTPError as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            error_message = f"HTTP communication error: {e}"
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            error_message = f"Unexpected execution error: {e}"

        return TestExecutionResult(
            test_id=tc.test_id,
            endpoint_path=tc.endpoint_path,
            http_method=method,
            passed=passed,
            status_code=status_code,
            response_body=response_body,
            error_message=error_message,
            duration_ms=round(duration_ms, 2),
        )

    def execute(self, suite: TestSuite, target_base_url: str) -> IterationResult:
        """Execute all test cases in the suite and aggregate execution evidence."""
        start_suite_time = time.perf_counter()
        target_url = target_base_url or self.settings.TARGET_API_BASE_URL

        # 1. Save executable Pytest file to artifacts
        saved_file = self.save_test_file(suite)

        # 2. Execute test cases via HTTP client
        execution_results: List[TestExecutionResult] = []
        with httpx.Client(timeout=float(self.timeout)) as client:
            for tc in suite.test_cases:
                res = self.execute_test_case(tc, target_url, client)
                execution_results.append(res)

        total_duration = time.perf_counter() - start_suite_time

        # 3. Aggregate metrics
        total_tests = len(execution_results)
        passed_count = sum(1 for r in execution_results if r.passed)
        failed_count = sum(
            1 for r in execution_results if not r.passed and r.status_code is not None
        )
        error_count = sum(1 for r in execution_results if r.status_code is None)

        unique_scenarios = {
            f"{tc.endpoint_path}:{tc.scenario_type.value}" for tc in suite.test_cases
        }
        total_scenarios = len(unique_scenarios)
        covered_scenarios = len(
            {
                f"{r.endpoint_path}:{tc.scenario_type.value}"
                for r, tc in zip(execution_results, suite.test_cases)
                if r.passed
            }
        )
        edge_cases_count = sum(
            1 for tc in suite.test_cases if tc.scenario_type != ScenarioType.POSITIVE
        )
        coverage_pct = (
            round((covered_scenarios / total_scenarios) * 100.0, 1)
            if total_scenarios > 0
            else 0.0
        )

        # 4. Docker Sandbox Execution (if enabled)
        sandbox_note = ""
        if self.enable_sandbox:
            sandbox_res = self.sandbox.run_isolated(
                saved_file,
                environment_vars={"TARGET_URL": target_url},
                fallback_to_local=True,
            )
            if sandbox_res.sandboxed:
                sandbox_note = (
                    f"[DOCKER SANDBOX ACTIVE] Container Exit Code: {sandbox_res.exit_code} "
                    f"({sandbox_res.duration_seconds}s)\n"
                )
            else:
                sandbox_note = (
                    f"[DOCKER SANDBOX FALLBACK] Docker daemon offline or unreachable. "
                    f"Fell back to local sandbox runner (Exit Code: {sandbox_res.exit_code}, {sandbox_res.duration_seconds}s).\n"
                )

        # 5. Generate formatted console summary
        raw_output = sandbox_note + self._format_raw_output(
            suite=suite,
            saved_file=saved_file,
            results=execution_results,
            passed=passed_count,
            failed=failed_count,
            errors=error_count,
            duration=total_duration,
        )

        return IterationResult(
            iteration=suite.iteration,
            suite_version=suite.suite_version,
            total_tests=total_tests,
            passed_count=passed_count,
            failed_count=failed_count,
            error_count=error_count,
            total_scenarios=total_scenarios,
            covered_scenarios=covered_scenarios,
            edge_cases_count=edge_cases_count,
            coverage_percentage=coverage_pct,
            execution_time_seconds=round(total_duration, 3),
            execution_results=execution_results,
            raw_output=raw_output,
        )

    # Alias for execute
    execute_suite = execute

    def _resolve_path(self, tc: TestCase) -> str:
        """Resolve path parameters using concrete values or overrides."""
        path = tc.endpoint_path
        path_overrides = (
            tc.query_params.get("_path_override", {})
            if isinstance(tc.query_params, dict)
            else {}
        )

        for param in re.findall(r"\{([a-zA-Z0-9_]+)\}", path):
            val = path_overrides.get(param, "1")
            path = path.replace(f"{{{param}}}", str(val))

        return path

    def _format_raw_output(
        self,
        suite: TestSuite,
        saved_file: Path,
        results: List[TestExecutionResult],
        passed: int,
        failed: int,
        errors: int,
        duration: float,
    ) -> str:
        """Format terminal-style execution evidence summary."""
        lines = [
            f"=== Test Suite {suite.suite_version} Execution Report ===",
            f"File: {saved_file.name}",
            f"Total Tests: {len(results)} | Passed: {passed} | Failed: {failed} | Errors: {errors}",
            f"Duration: {duration:.2f}s",
            "-" * 60,
        ]

        for r in results:
            status_tag = "[PASS]" if r.passed else "[FAIL]"
            error_info = f" - {r.error_message}" if r.error_message else ""
            lines.append(
                f"{status_tag} {r.test_id} | {r.http_method:<6} {r.endpoint_path:<20} "
                f"({r.duration_ms:.1f}ms){error_info}"
            )

        lines.append("=" * 60)
        return "\n".join(lines)
