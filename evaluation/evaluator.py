"""Suite Evaluator comparing initial (V1) and reflected/improved (V2..Vn) test runs."""

from models.schemas import EvaluationComparison, IterationResult


class SuiteEvaluator:
    """Computes comparative metrics between V1 and subsequent test execution runs."""

    def compare_suites(
        self, report_v1: IterationResult, report_v2: IterationResult
    ) -> EvaluationComparison:
        """Compare results between V1 and a later iteration to measure reflection benefits."""
        v1_total = report_v1.total_tests
        v1_passed = report_v1.passed_count
        v1_failed = report_v1.failed_count
        v2_total = report_v2.total_tests
        v2_passed = report_v2.passed_count
        v2_failed = report_v2.failed_count

        v1_cov = report_v1.coverage_percentage
        v2_cov = report_v2.coverage_percentage
        cov_delta = round(v2_cov - v1_cov, 1)

        new_edge_cases = max(0, report_v2.edge_cases_count - report_v1.edge_cases_count)
        defects_delta = max(0, report_v2.failed_count - report_v1.failed_count)

        stopping_str = (
            f" [Halt Reason: {report_v2.stopping_reason.value}]"
            if report_v2.stopping_reason
            else ""
        )

        sign = "+" if cov_delta >= 0 else ""
        test_diff = v2_total - v1_total
        test_sign = "+" if test_diff >= 0 else ""

        summary = (
            f"Reflection Cycle Evolution ({report_v1.suite_version} -> {report_v2.suite_version}): "
            f"Test suite expanded from {v1_total} to {v2_total} tests ({test_sign}{test_diff}). "
            f"Scenario coverage shifted from {v1_cov:.1f}% to {v2_cov:.1f}% ({sign}{cov_delta}%). "
            f"Edge cases added: {new_edge_cases}. Defects surfaced: {defects_delta}."
            f"{stopping_str}"
        )

        return EvaluationComparison(
            initial_iteration=report_v1.iteration,
            final_iteration=report_v2.iteration,
            v1_total=v1_total,
            v1_passed=v1_passed,
            v1_failed=v1_failed,
            v2_total=v2_total,
            v2_passed=v2_passed,
            v2_failed=v2_failed,
            v1_coverage_percent=v1_cov,
            v2_coverage_percent=v2_cov,
            coverage_delta_percent=cov_delta,
            new_edge_cases_count=new_edge_cases,
            defects_detected_delta=defects_delta,
            stopping_reason=report_v2.stopping_reason,
            summary=summary,
        )
