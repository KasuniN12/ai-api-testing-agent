"""Sandbox environment manager for isolated containerized test execution with local fallback."""

import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Dict, Optional
from pydantic import BaseModel
import docker
from docker.errors import DockerException, APIError
from config.settings import get_settings


class SandboxResult(BaseModel):
    """Result of running a test execution inside a Docker sandbox or local fallback."""

    __test__ = False  # Prevent pytest from treating this as a test class

    exit_code: int
    output: str
    duration_seconds: float
    sandboxed: bool
    fallback_used: bool = False
    error: Optional[str] = None


class ExecutionSandbox:
    """Provides sandboxed execution using Docker for isolating test runs with graceful local fallback."""

    __test__ = False  # Prevent pytest from treating this as a test class

    def __init__(
        self,
        image_name: Optional[str] = None,
        mem_limit: str = "256m",
        timeout: Optional[int] = None,
    ):
        self.settings = get_settings()
        self.image_name = image_name or self.settings.DOCKER_IMAGE_NAME
        self.mem_limit = mem_limit
        self.timeout = timeout or self.settings.EXECUTION_TIMEOUT
        self._client: Optional[docker.DockerClient] = None

    def _get_client(self) -> Optional[docker.DockerClient]:
        """Lazy load and cache Docker client."""
        if self._client is None:
            try:
                self._client = docker.from_env()
            except DockerException:
                self._client = None
        return self._client

    def is_available(self) -> bool:
        """Check if Docker daemon is running and accessible."""
        client = self._get_client()
        if client is None:
            return False
        try:
            return bool(client.ping())
        except (DockerException, APIError, Exception):
            return False

    def _run_local_fallback(
        self,
        script: Path,
        environment_vars: Optional[Dict[str, str]] = None,
        reason: str = "Docker unavailable",
    ) -> SandboxResult:
        """Execute test script in local Python subprocess as a graceful fallback."""
        start_time = time.perf_counter()
        env = os.environ.copy()
        if environment_vars:
            env.update(environment_vars)

        try:
            cmd = [sys.executable, "-m", "pytest", script.name, "-v"]
            proc = subprocess.run(
                cmd,
                cwd=str(script.parent),
                capture_output=True,
                text=True,
                timeout=float(self.timeout),
                env=env,
            )
            duration = time.perf_counter() - start_time
            out_str = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")

            return SandboxResult(
                exit_code=proc.returncode,
                output=out_str.strip(),
                duration_seconds=round(duration, 3),
                sandboxed=False,
                fallback_used=True,
                error=f"{reason} (Executed via local runner)",
            )
        except subprocess.TimeoutExpired:
            duration = time.perf_counter() - start_time
            return SandboxResult(
                exit_code=1,
                output="",
                duration_seconds=round(duration, 3),
                sandboxed=False,
                fallback_used=True,
                error=f"Local execution timed out after {self.timeout}s ({reason})",
            )
        except Exception as e:
            duration = time.perf_counter() - start_time
            return SandboxResult(
                exit_code=1,
                output="",
                duration_seconds=round(duration, 3),
                sandboxed=False,
                fallback_used=True,
                error=f"Local fallback execution error: {e} ({reason})",
            )

    def run_isolated(
        self,
        test_script_path: Path,
        environment_vars: Optional[Dict[str, str]] = None,
        fallback_to_local: bool = True,
    ) -> SandboxResult:
        """Run the test script inside an isolated ephemeral Docker container, or fallback locally.

        Security constraints applied when Docker is active:
        - Read-only volume mount for test script (prevents filesystem tampering)
        - Restricted memory limit (e.g. 256MB)
        - Privilege escalation disabled (no-new-privileges)
        - Automatic container removal (ephemeral)
        - Isolated execution time tracking
        """
        script = Path(test_script_path).resolve()
        if not script.exists():
            return SandboxResult(
                exit_code=1,
                output="",
                duration_seconds=0.0,
                sandboxed=False,
                error=f"Test script not found: {script}",
            )

        if not self.is_available():
            if fallback_to_local:
                return self._run_local_fallback(
                    script=script,
                    environment_vars=environment_vars,
                    reason="Docker daemon is not reachable. Ensure Docker Desktop is running.",
                )
            return SandboxResult(
                exit_code=1,
                output="",
                duration_seconds=0.0,
                sandboxed=False,
                error="Docker daemon is not reachable. Ensure Docker Desktop is running.",
            )

        client = self._get_client()
        assert client is not None

        env = environment_vars or {}
        test_dir = str(script.parent)
        script_name = script.name

        volumes = {
            test_dir: {
                "bind": "/workspace",
                "mode": "ro",  # Read-only prevents tests from modifying host files
            }
        }

        cmd = f"python -m pytest /workspace/{script_name} -v"
        start_time = time.perf_counter()

        try:
            container_output = client.containers.run(
                image=self.image_name,
                command=cmd,
                volumes=volumes,
                environment=env,
                mem_limit=self.mem_limit,
                security_opt=["no-new-privileges:true"],
                network_mode="host",
                detach=False,
                stdout=True,
                stderr=True,
                remove=True,
            )
            duration = time.perf_counter() - start_time
            output_str = (
                container_output.decode("utf-8", errors="replace")
                if isinstance(container_output, bytes)
                else str(container_output)
            )

            return SandboxResult(
                exit_code=0,
                output=output_str,
                duration_seconds=round(duration, 3),
                sandboxed=True,
                fallback_used=False,
            )

        except docker.errors.ContainerError as e:
            duration = time.perf_counter() - start_time
            out_str = (
                e.stderr.decode("utf-8", errors="replace")
                if isinstance(e.stderr, bytes)
                else str(e)
            )
            return SandboxResult(
                exit_code=e.exit_status,
                output=out_str,
                duration_seconds=round(duration, 3),
                sandboxed=True,
                fallback_used=False,
                error=f"Container execution finished with exit code {e.exit_status}",
            )
        except Exception as e:
            duration = time.perf_counter() - start_time
            if fallback_to_local:
                return self._run_local_fallback(
                    script=script,
                    environment_vars=env,
                    reason=f"Docker sandbox error: {e}",
                )
            return SandboxResult(
                exit_code=1,
                output="",
                duration_seconds=round(duration, 3),
                sandboxed=False,
                error=f"Docker sandbox execution error: {e}",
            )
