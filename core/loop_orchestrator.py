"""Iterative Loop Orchestrator managing self-improving API testing cycles."""

import logging
from typing import Any, Callable, List, Optional, Tuple
from config.settings import get_settings
from core.api_parser import OpenAPIParser
from core.llm_client import LLMClient
from core.reflection_engine import ReflectionEngine
from core.test_generator import TestGenerator
from core.test_improver import TestImprover
from evaluation.evaluator import SuiteEvaluator
from execution.test_executor import TestExecutor
from models.schemas import (
    APISpecification,
    EvaluationComparison,
    IterationResult,
    StoppingConditionReason,
    TestSuite,
)

logger = logging.getLogger(__name__)


class IterativeQAOrchestrator:
    """Orchestrates the Reflection Design Pattern loop across multiple iterations.

    Pipeline:
    1. Parse OpenAPI Spec
    2. Generate Initial Test Suite (V1)
    3. Loop:
       - Execute Test Suite against Target API
       - Analyze Execution Evidence with Reflection Engine
       - Check Stopping Conditions (Target Met, Convergence, Max Iterations)
       - If stopped: Terminate loop
       - Else: Generate Improved Suite (V2..Vn) targeting missing edge cases
    4. Quantitative Evaluation & Trajectory Comparison (V1 vs Final)
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        timeout: Optional[int] = None,
        enable_sandbox: Optional[bool] = None,
    ):
        self.settings = get_settings()
        self.llm = llm_client or LLMClient()
        self.timeout = timeout if timeout is not None else self.settings.EXECUTION_TIMEOUT
        self.enable_sandbox = (
            enable_sandbox
            if enable_sandbox is not None
            else self.settings.ENABLE_DOCKER_SANDBOX
        )

        self.generator = TestGenerator(llm_client=self.llm)
        self.executor = TestExecutor(
            timeout=self.timeout, enable_sandbox=self.enable_sandbox
        )
        self.reflector = ReflectionEngine(llm_client=self.llm)
        self.improver = TestImprover(llm_client=self.llm)
        self.evaluator = SuiteEvaluator()

    def run(
        self,
        spec_path: Optional[str] = None,
        target_url: Optional[str] = None,
        max_iterations: Optional[int] = None,
        target_coverage: Optional[float] = None,
        target_quality: Optional[float] = None,
        callback: Optional[Callable[[str, Any], None]] = None,
    ) -> Tuple[APISpecification, List[IterationResult], EvaluationComparison]:
        """Execute the self-improving API testing lifecycle until stopping conditions are met."""
        active_spec_path = spec_path or self.settings.OPENAPI_SPEC_PATH
        active_target_url = target_url or self.settings.TARGET_API_BASE_URL
        max_iter = max_iterations or self.settings.MAX_REFLECTION_ITERATIONS
        target_cov = target_coverage if target_coverage is not None else self.settings.TARGET_COVERAGE_PERCENT
        target_qual = target_quality if target_quality is not None else self.settings.TARGET_QUALITY_SCORE

        def notify(event: str, data: Any = None):
            if callback:
                try:
                    callback(event, data)
                except Exception as e:
                    logger.warning(f"Orchestrator callback error: {e}")

        # Step 1: Parse API Specification
        notify("spec_parsing", {"spec_path": active_spec_path})
        parser = OpenAPIParser(active_spec_path)
        spec = parser.parse()
        notify("spec_parsed", spec)

        # Step 2: Generate Initial Suite (V1)
        notify("v1_generation_start", {"endpoints_count": len(spec.endpoints)})
        current_suite = self.generator.generate_initial_suite(spec, active_target_url)
        notify("v1_generated", current_suite)

        iteration_history: List[IterationResult] = []

        # Step 3: Iterative Reflection & Refinement Loop
        for iteration in range(1, max_iter + 1):
            notify("iteration_start", {"iteration": iteration, "suite_version": current_suite.suite_version})

            # 3a. Execute Test Suite
            notify("execution_start", {"iteration": iteration, "tests_count": len(current_suite.test_cases)})
            iteration_result = self.executor.execute(current_suite, active_target_url)
            notify("execution_completed", iteration_result)

            # 3b. Reflection Analysis
            notify("reflection_start", {"iteration": iteration})
            reflection = self.reflector.reflect(spec, current_suite, iteration_result)
            iteration_result.reflection_feedback = reflection
            notify("reflection_completed", reflection)

            # 3c. Evaluate Stopping Conditions
            stopping_reason: Optional[StoppingConditionReason] = None

            # Condition 1: Target Coverage & Quality Achieved
            if (
                iteration_result.coverage_percentage >= target_cov
                and reflection.quality_score >= target_qual
            ):
                stopping_reason = StoppingConditionReason.TARGET_REACHED

            # Condition 2: Convergence (no edge case growth and no coverage delta)
            elif iteration > 1:
                prev = iteration_history[-1]
                prev_q = (
                    prev.reflection_feedback.quality_score
                    if prev.reflection_feedback
                    else 0.0
                )
                no_new_edge_cases = iteration_result.edge_cases_count <= prev.edge_cases_count
                no_coverage_gain = iteration_result.coverage_percentage <= prev.coverage_percentage
                no_quality_gain = reflection.quality_score <= prev_q

                if no_new_edge_cases and no_coverage_gain and no_quality_gain:
                    stopping_reason = StoppingConditionReason.CONVERGENCE

            # Condition 3: Maximum Iterations Reached
            if not stopping_reason and iteration >= max_iter:
                stopping_reason = StoppingConditionReason.MAX_ITERATIONS

            # Check if stopping
            if stopping_reason:
                iteration_result.stopping_condition_met = True
                iteration_result.stopping_reason = stopping_reason
                iteration_history.append(iteration_result)
                notify("iteration_halted", {
                    "iteration": iteration,
                    "reason": stopping_reason.value,
                    "result": iteration_result,
                })
                break
            else:
                iteration_result.stopping_condition_met = False
                iteration_history.append(iteration_result)
                notify("iteration_completed", iteration_result)

                # 3d. Generate Improved Suite for Next Iteration
                notify("improvement_start", {"iteration": iteration + 1})
                current_suite = self.improver.generate_improved_suite(
                    spec=spec,
                    current_suite=current_suite,
                    reflection=reflection,
                    base_url=active_target_url,
                )
                notify("improvement_completed", current_suite)

        # Step 4: Final Evaluation Comparison (V1 vs Final)
        notify("evaluation_start", None)
        final_comparison = self.evaluator.compare_suites(
            report_v1=iteration_history[0],
            report_v2=iteration_history[-1],
        )
        notify("evaluation_completed", final_comparison)

        return spec, iteration_history, final_comparison
