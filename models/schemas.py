"""Pydantic schemas representing domain entities across the reflection lifecycle.

Models:
- APIEndpoint: Stores API endpoint information
- APISpecification: Stores parsed OpenAPI information
- TestCase: Represents an AI-generated test
- TestExecutionResult: Stores test execution evidence
- ReflectionFeedback: Stores the AI's review and suggestions
- IterationResult: Stores the results of each improvement cycle
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ScenarioType(str, Enum):
    """Categorization of API test scenarios."""
    POSITIVE = "positive"
    BOUNDARY = "boundary"
    INVALID_TYPE = "invalid_type"
    MISSING_AUTH = "missing_auth"
    EMPTY_INPUT = "empty_input"
    MALFORMED_JSON = "malformed_json"


class StoppingConditionReason(str, Enum):
    """Reasons for halting the iterative improvement loop."""
    TARGET_REACHED = "Target quality metrics achieved"
    CONVERGENCE = "Convergence reached (no new edge cases identified)"
    MAX_ITERATIONS = "Maximum iteration limit reached"
    REGRESSION_DETECTED = "Regression detected in test suite"
    USER_INTERRUPT = "Execution halted by user"


class APIEndpoint(BaseModel):
    """Stores API endpoint information extracted from OpenAPI specs."""
    path: str
    method: str
    summary: Optional[str] = None
    description: Optional[str] = None
    parameters: List[Dict[str, Any]] = Field(default_factory=list)
    request_body_schema: Optional[Dict[str, Any]] = None
    responses: Dict[str, Any] = Field(default_factory=dict)
    requires_auth: bool = False

    @property
    def request_body(self) -> Optional[Dict[str, Any]]:
        """Alias for request_body_schema."""
        return self.request_body_schema

    @property
    def operation_id(self) -> Optional[str]:
        """Optional operation identifier."""
        return None


class APISpecification(BaseModel):
    """Stores parsed OpenAPI specification information."""
    title: str
    version: str
    base_url: Optional[str] = None
    endpoints: List[APIEndpoint] = Field(default_factory=list)


class TestCase(BaseModel):
    """Represents an AI-generated API test case."""
    __test__ = False  # Prevent pytest from treating this as a test class

    test_id: str
    endpoint_path: str
    http_method: str
    scenario_type: ScenarioType = ScenarioType.POSITIVE
    description: str
    headers: Dict[str, str] = Field(default_factory=dict)
    query_params: Dict[str, Any] = Field(default_factory=dict)
    body: Optional[Any] = None
    expected_status: int
    validation_rules: List[str] = Field(default_factory=list)


class TestExecutionResult(BaseModel):
    """Stores test execution evidence from running a test against the target API."""
    __test__ = False  # Prevent pytest from treating this as a test class

    test_id: str
    endpoint_path: str = ""
    http_method: str = ""
    passed: bool
    status_code: Optional[int] = None
    response_body: Optional[Any] = None
    error_message: Optional[str] = None
    duration_ms: float = 0.0

    @property
    def duration_seconds(self) -> float:
        """Duration in seconds for backward compatibility."""
        return self.duration_ms / 1000.0


# Backward compatibility alias
ExecutionResult = TestExecutionResult


class TestSuite(BaseModel):
    """Collection of test cases for a specific iteration cycle."""
    __test__ = False  # Prevent pytest from treating this as a test class

    suite_version: str = Field(default="V1", description="e.g. V1, V2, V3...")
    iteration: int = 1
    generated_code: str = Field(default="", description="Executable Pytest Python code")
    test_cases: List[TestCase] = Field(default_factory=list)


class ReflectionFinding(BaseModel):
    """Individual reflection feedback item based on execution evidence."""
    category: str = Field(
        default="missing_edge_case",
        description="e.g. missing_edge_case, invalid_assumption, unhandled_status_code",
    )
    classification: str = Field(
        default="investigate",
        description="e.g. potential_api_defect, contract_mismatch, infrastructure_failure, auth_defect, validation_defect",
    )
    confidence: str = Field(
        default="MEDIUM",
        description="e.g. HIGH, MEDIUM, LOW",
    )
    endpoint: str = ""
    observation: str = ""
    evidence: str = ""
    recommended_action: str = ""


class ReflectionFeedback(BaseModel):
    """Stores the AI's review, gap analysis, and improvement suggestions."""
    iteration: int = 1
    identified_issues: List[ReflectionFinding] = Field(default_factory=list)
    missing_scenarios: List[str] = Field(default_factory=list)
    coverage_gaps: List[str] = Field(default_factory=list)
    reflection_summary: str = ""
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    score_breakdown: Dict[str, float] = Field(default_factory=dict)
    api_health: Dict[str, Any] = Field(default_factory=dict)


# Backward compatibility alias
ReflectionReport = ReflectionFeedback


class IterationResult(BaseModel):
    """Stores the results of each improvement cycle in the reflection loop."""
    __test__ = False

    iteration: int = 1
    suite_version: str = "V1"
    total_tests: int = 0
    passed_count: int = 0
    failed_count: int = 0
    error_count: int = 0
    total_scenarios: int = 0
    covered_scenarios: int = 0
    edge_cases_count: int = 0
    coverage_percentage: float = 0.0
    execution_time_seconds: float = 0.0
    execution_results: List[TestExecutionResult] = Field(default_factory=list)
    reflection_feedback: Optional[ReflectionFeedback] = None
    stopping_condition_met: bool = False
    stopping_reason: Optional[StoppingConditionReason] = None
    raw_output: str = ""


# Backward compatibility alias
TestRunReport = IterationResult


class EvaluationComparison(BaseModel):
    """Quantitative comparison across improvement cycles (e.g., V1 vs Final)."""
    initial_iteration: int = 1
    final_iteration: int = 2
    v1_total: int = 0
    v1_passed: int = 0
    v1_failed: int = 0
    v2_total: int = 0
    v2_passed: int = 0
    v2_failed: int = 0
    v1_coverage_percent: float = 0.0
    v2_coverage_percent: float = 0.0
    coverage_delta_percent: float = 0.0
    new_edge_cases_count: int = 0
    defects_detected_delta: int = 0
    stopping_reason: Optional[StoppingConditionReason] = None
    summary: str = ""
