"""Tests for Reflection Engine and evaluation comparison."""

from core.reflection_engine import ReflectionEngine
from evaluation.evaluator import SuiteEvaluator
from models.schemas import APISpecification, TestSuite, TestRunReport


def test_reflection_engine_interface():
    engine = ReflectionEngine()
    spec = APISpecification(title="Test API", version="1.0", endpoints=[])
    suite = TestSuite(suite_version="V1", generated_code="# v1", test_cases=[])
    report = TestRunReport(
        suite_version="V1",
        total_tests=0,
        passed_count=0,
        failed_count=0,
        error_count=0,
        execution_time_seconds=0.0,
    )
    reflection = engine.reflect(spec, suite, report)
    assert reflection is not None
    assert isinstance(reflection.reflection_summary, str)


def test_suite_evaluator_interface():
    evaluator = SuiteEvaluator()
    r1 = TestRunReport(
        suite_version="V1", total_tests=5, passed_count=5, failed_count=0, error_count=0, execution_time_seconds=1.0
    )
    r2 = TestRunReport(
        suite_version="V2", total_tests=10, passed_count=9, failed_count=1, error_count=0, execution_time_seconds=1.5
    )
    comparison = evaluator.compare_suites(r1, r2)
    assert comparison.v1_total == 5
    assert comparison.v2_total == 10
