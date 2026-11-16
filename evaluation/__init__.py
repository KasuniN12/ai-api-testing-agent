"""Evaluation package for comparing V1 vs V2 test suites and computing QA metrics."""

from .evaluator import SuiteEvaluator
from .metrics import calculate_coverage_delta, calculate_defect_detection_rate

__all__ = [
    "SuiteEvaluator",
    "calculate_coverage_delta",
    "calculate_defect_detection_rate",
]
