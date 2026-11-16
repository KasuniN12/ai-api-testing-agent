"""Reflection Engine analyzing execution evidence to find gaps, edge cases, and quality metrics."""

import logging
from typing import Any, Dict, List, Optional, Set
from core.llm_client import LLMClient
from models.schemas import (
    APIEndpoint,
    APISpecification,
    IterationResult,
    ReflectionFeedback,
    ReflectionFinding,
    ScenarioType,
    TestCase,
    TestSuite,
)
from prompts.templates import REFLECTION_PROMPT, SYSTEM_PROMPT_REFLECTOR

logger = logging.getLogger(__name__)


class ReflectionEngine:
    """Core Reflection Agent implementing the Critic component of the pattern.

    Examines actual execution evidence (failures, status codes, latencies) and
    evaluates test suite quality independently from API health.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()

    def reflect(
        self,
        spec: APISpecification,
        test_suite: TestSuite,
        execution_report: IterationResult,
    ) -> ReflectionFeedback:
        """Analyze test results against specification, classify issues, and compute decoupled quality metrics."""
        heuristic_feedback = self._analyze_heuristically(spec, test_suite, execution_report)

        is_llm_configured = (
            self.llm.is_configured()
            if callable(self.llm.is_configured)
            else bool(self.llm.is_configured)
        )
        if is_llm_configured:
            try:
                prompt = REFLECTION_PROMPT.format(
                    openapi_spec=spec.model_dump_json(indent=2),
                    test_suite_v1=test_suite.generated_code,
                    execution_results=execution_report.model_dump_json(indent=2),
                )
                llm_feedback = self.llm.structured_completion(
                    prompt=prompt,
                    response_model=ReflectionFeedback,
                    system_prompt=SYSTEM_PROMPT_REFLECTOR,
                )
                if llm_feedback:
                    return self._merge_feedback(heuristic_feedback, llm_feedback, test_suite.iteration)
            except Exception as exc:
                logger.warning(f"LLM reflection failed, using heuristic reflection: {exc}")

        return heuristic_feedback

    def _analyze_heuristically(
        self,
        spec: APISpecification,
        test_suite: TestSuite,
        report: IterationResult,
    ) -> ReflectionFeedback:
        """Perform evidence-based analysis: granular coverage, confidence triage, decoupled scoring."""
        identified_issues: List[ReflectionFinding] = []
        coverage_gaps: List[str] = []
        missing_scenarios: List[str] = []

        # 1. Map existing test cases with granular signatures:
        # endpoint_key: { (scenario_type, target_field, variation) }
        tested_endpoints: Set[str] = set()
        endpoint_granular_coverage: Dict[str, Set[str]] = {}

        tc_map = {tc.test_id: tc for tc in test_suite.test_cases}

        for tc in test_suite.test_cases:
            key = f"{tc.http_method.upper()} {tc.endpoint_path}"
            tested_endpoints.add(key)
            if key not in endpoint_granular_coverage:
                endpoint_granular_coverage[key] = set()

            # Derive field/variation signature
            variation = self._derive_tc_variation(tc)
            endpoint_granular_coverage[key].add(f"{tc.scenario_type.value}:{variation}")

        # 2. Granular Gap Discovery per Endpoint
        for ep in spec.endpoints:
            key = f"{ep.method.upper()} {ep.path}"
            if key not in tested_endpoints:
                coverage_gaps.append(f"Endpoint {key} has no tests.")

            covered_sigs = endpoint_granular_coverage.get(key, set())

            # A. Parameters: Boundary checks (negative ID and non-existent large ID)
            if ep.parameters and "{" in ep.path:
                if not any("boundary:negative" in s for s in covered_sigs):
                    missing_scenarios.append(f"{key} missing scenario: boundary (field: id, variation: negative_value)")
                    identified_issues.append(
                        ReflectionFinding(
                            category="missing_edge_case",
                            classification="missing_boundary_check",
                            confidence="HIGH",
                            endpoint=ep.path,
                            observation=f"{key} contains path parameters but lacks negative value boundary testing.",
                            evidence=f"Parameters: {[p.get('name') for p in ep.parameters]}",
                            recommended_action=f"Generate boundary test with negative ID (e.g. -1) for {key}.",
                        )
                    )
                if not any("boundary:out_of_bounds" in s for s in covered_sigs):
                    missing_scenarios.append(f"{key} missing scenario: boundary (field: id, variation: out_of_bounds)")

            # B. Query Parameters Boundary (e.g. limit=-1)
            query_params = [p for p in ep.parameters if p.get("in") == "query"]
            if query_params and not any("boundary:query" in s for s in covered_sigs):
                missing_scenarios.append(f"{key} missing scenario: boundary (field: query, variation: invalid_filter)")
                identified_issues.append(
                    ReflectionFinding(
                        category="missing_edge_case",
                        classification="missing_boundary_check",
                        confidence="MEDIUM",
                        endpoint=ep.path,
                        observation=f"{key} contains query parameters but lacks boundary/filter testing.",
                        evidence=f"Query Parameters: {[p.get('name') for p in query_params]}",
                        recommended_action=f"Generate query parameter boundary test (e.g. limit=-1) for {key}.",
                    )
                )

            # C. Request Body Schemas: Granular empty payload, missing required fields, and format checks
            if ep.request_body_schema and isinstance(ep.request_body_schema, dict):
                # Empty body check
                if not any("empty_input:empty_body" in s for s in covered_sigs):
                    missing_scenarios.append(f"{key} missing scenario: empty_input (field: body, variation: empty_payload)")
                    identified_issues.append(
                        ReflectionFinding(
                            category="missing_edge_case",
                            classification="missing_validation_check",
                            confidence="HIGH",
                            endpoint=ep.path,
                            observation=f"{key} accepts a JSON body but lacks empty body testing.",
                            evidence="No empty payload test in current suite.",
                            recommended_action=f"Add empty payload test case expecting 400 Bad Request for {key}.",
                        )
                    )

                # Missing required fields check
                required_fields = ep.request_body_schema.get("required", [])
                for rf in required_fields:
                    if not any(f"empty_input:missing_{rf}" in s for s in covered_sigs):
                        missing_scenarios.append(f"{key} missing scenario: empty_input (field: {rf}, variation: missing_field)")
                        identified_issues.append(
                            ReflectionFinding(
                                category="missing_edge_case",
                                classification="missing_validation_check",
                                confidence="HIGH",
                                endpoint=ep.path,
                                observation=f"{key} requires '{rf}' in request body but lacks omission test.",
                                evidence=f"Schema required fields: {required_fields}",
                                recommended_action=f"Add test case submitting payload omitting required field '{rf}' for {key}.",
                            )
                        )

                # Type / Format violation check
                properties = ep.request_body_schema.get("properties", {})
                for prop_name, prop_meta in properties.items():
                    if prop_meta.get("format") == "email" and not any(f"invalid_type:{prop_name}" in s for s in covered_sigs):
                        missing_scenarios.append(f"{key} missing scenario: invalid_type (field: {prop_name}, variation: invalid_format)")
                        identified_issues.append(
                            ReflectionFinding(
                                category="missing_edge_case",
                                classification="missing_format_validation",
                                confidence="HIGH",
                                endpoint=ep.path,
                                observation=f"{key} specifies format 'email' on field '{prop_name}' but lacks malformed format test.",
                                evidence=f"Field '{prop_name}' declared format: email",
                                recommended_action=f"Add test submitting malformed string in field '{prop_name}' expecting 400 Bad Request for {key}.",
                            )
                        )

            # D. Security / Authentication
            if ep.requires_auth and not any("missing_auth" in s for s in covered_sigs):
                missing_scenarios.append(f"{key} missing scenario: missing_auth (header: Authorization, variation: empty_token)")
                identified_issues.append(
                    ReflectionFinding(
                        category="untested_security",
                        classification="missing_auth_check",
                        confidence="HIGH",
                        endpoint=ep.path,
                        observation=f"{key} requires authentication but lacks unauthenticated request verification.",
                        evidence="No missing authentication test in current suite.",
                        recommended_action=f"Add unauthenticated request test expecting 401 Unauthorized for {key}.",
                    )
                )

        # 3. Confidence-Based Failure Classification
        defects_detected_count = 0
        for res in report.execution_results:
            orig_tc = tc_map.get(res.test_id)
            expected_status = orig_tc.expected_status if orig_tc else None
            if not res.passed:
                # 3a. HTTP 500 response -> High confidence API defect (unhandled server crash)
                if res.status_code == 500:
                    defects_detected_count += 1
                    identified_issues.append(
                        ReflectionFinding(
                            category="server_error",
                            classification="potential_api_defect",
                            confidence="HIGH",
                            endpoint=res.endpoint_path,
                            observation=(
                                f"Server crashed with HTTP 500 Internal Server Error (expected HTTP {expected_status}). "
                                f"Indicates unhandled exception instead of graceful validation or error handling."
                            ),
                            evidence=f"Test {res.test_id}: Status 500, Response: {str(res.response_body)[:150]}",
                            recommended_action="File high-priority defect report for unhandled exception; verify input sanitization.",
                        )
                    )

                # 3b. Expected 401/403, received 200/201 -> Potential Auth Bypass Defect
                elif expected_status in [401, 403] and res.status_code in [200, 201]:
                    defects_detected_count += 1
                    identified_issues.append(
                        ReflectionFinding(
                            category="security_bypass",
                            classification="potential_auth_defect",
                            confidence="HIGH",
                            endpoint=res.endpoint_path,
                            observation=f"Unauthorized request unexpectedly succeeded with HTTP {res.status_code}.",
                            evidence=f"Test {res.test_id}: Received {res.status_code} on unauthenticated request",
                            recommended_action="Security alert: Verify authentication guard middleware is enforced.",
                        )
                    )

                # 3c. Expected 400/422, received 200/201 -> Potential Validation Defect
                elif expected_status in [400, 422] and res.status_code in [200, 201]:
                    defects_detected_count += 1
                    identified_issues.append(
                        ReflectionFinding(
                            category="missing_validation",
                            classification="potential_validation_defect",
                            confidence="HIGH",
                            endpoint=res.endpoint_path,
                            observation=f"Malformed or empty input was unexpectedly accepted with HTTP {res.status_code}.",
                            evidence=f"Test {res.test_id}: Accepted invalid input",
                            recommended_action="Verify schema validation on endpoint request body / query parameters.",
                        )
                    )

                # 3d. Connection Failure / Timeout -> Infrastructure
                elif res.status_code is None:
                    identified_issues.append(
                        ReflectionFinding(
                            category="network_timeout",
                            classification="infrastructure_failure",
                            confidence="HIGH",
                            endpoint=res.endpoint_path,
                            observation="Request failed due to network unreachable or connection timeout.",
                            evidence=f"Test {res.test_id}: {res.error_message}",
                            recommended_action="Verify service availability and network routing.",
                        )
                    )

                # 3e. Expected 200, received 404 -> Test data or contract mismatch
                elif expected_status in [200, 204] and res.status_code == 404:
                    identified_issues.append(
                        ReflectionFinding(
                            category="entity_not_found",
                            classification="contract_mismatch",
                            confidence="MEDIUM",
                            endpoint=res.endpoint_path,
                            observation=f"Expected resource to exist (HTTP {expected_status}), but received 404 Not Found.",
                            evidence=f"Test {res.test_id}: 404 for {res.endpoint_path}",
                            recommended_action="Check if prerequisite test entity was deleted or requires pre-seeding.",
                        )
                    )

                # 3f. Other status mismatch
                else:
                    identified_issues.append(
                        ReflectionFinding(
                            category="status_code_mismatch",
                            classification="contract_mismatch",
                            confidence="LOW",
                            endpoint=res.endpoint_path,
                            observation=f"Status code mismatch: expected {expected_status}, received {res.status_code}.",
                            evidence=f"Test {res.test_id}: {res.error_message}",
                            recommended_action="Review API specification contract and calibrate test expectation.",
                        )
                    )

        # 4. Decoupled Quality Scoring Formula
        total_tests = max(1, report.total_tests)
        total_scenarios = max(1, report.total_scenarios)

        # Component A: Scenario Coverage (C)
        cov_rate = min(1.0, report.covered_scenarios / total_scenarios) if total_scenarios > 0 else 0.0

        # Component B: Scenario Diversity (D)
        # Proportion of distinct ScenarioTypes present in suite (out of 5 primary: positive, boundary, empty_input, invalid_type, missing_auth)
        distinct_types = {tc.scenario_type for tc in test_suite.test_cases}
        diversity_rate = min(1.0, len(distinct_types) / 5.0)

        # Component C: Edge-Case Density (E)
        edge_rate = min(1.0, report.edge_cases_count / total_tests)

        # Component D: Defect-Detection Effectiveness (F)
        # Reward the test suite for discovering validation gaps / defects instead of penalizing it!
        defect_power = min(1.0, defects_detected_count / max(1, report.edge_cases_count)) if defects_detected_count > 0 else 0.0

        # Composite Test Suite Quality Formula:
        # Q = 0.35 * Coverage + 0.30 * Diversity + 0.20 * EdgeCaseRatio + 0.15 * DefectDetectionPower
        raw_quality = (0.35 * cov_rate) + (0.30 * diversity_rate) + (0.20 * edge_rate) + (0.15 * defect_power)
        quality_score = max(0.0, min(1.0, round(raw_quality, 2)))

        score_breakdown = {
            "scenario_coverage": round(cov_rate, 3),
            "scenario_diversity": round(diversity_rate, 3),
            "edge_case_density": round(edge_rate, 3),
            "defect_detection_effectiveness": round(defect_power, 3),
            "composite_quality_score": quality_score,
        }

        # 5. Separate API Health Metrics
        pass_rate = round(report.passed_count / total_tests, 3)
        server_errors = sum(1 for r in report.execution_results if r.status_code == 500)
        timeouts = sum(1 for r in report.execution_results if r.status_code is None)

        health_status = "HEALTHY"
        if server_errors > 0 or timeouts > 0:
            health_status = "DEGRADED" if server_errors > 0 else "OFFLINE"
        elif report.failed_count > 0:
            health_status = "VALIDATION_MISMATCH"

        api_health = {
            "health_status": health_status,
            "pass_rate": pass_rate,
            "passed_tests": report.passed_count,
            "failed_tests": report.failed_count,
            "potential_defects_found": defects_detected_count,
            "server_500_errors": server_errors,
            "timeouts_or_refusals": timeouts,
        }

        # 6. Formulate Executive Reflection Summary
        summary_lines = [
            f"=== Iteration {test_suite.iteration} Evidence-Based Reflection Audit ===",
            f"Test Suite Quality Score: {quality_score:.2f} / 1.00",
            f"  [Coverage: {cov_rate*100:.1f}% | Diversity: {diversity_rate*100:.1f}% | Edge Density: {edge_rate*100:.1f}% | Defect Power: {defect_power*100:.1f}%]",
            f"Target API Health: {health_status} (Pass Rate: {pass_rate*100:.1f}%, Defects Discovered: {defects_detected_count})",
            f"Tests Executed: {report.total_tests} (Passed: {report.passed_count}, Failed: {report.failed_count}, Errors: {report.error_count})",
            f"Edge Cases Tested: {report.edge_cases_count} across {len(distinct_types)} scenario types.",
            f"Identified Actionable Findings: {len(identified_issues)} (Missing Scenarios: {len(missing_scenarios)}).",
        ]

        return ReflectionFeedback(
            iteration=test_suite.iteration,
            identified_issues=identified_issues,
            missing_scenarios=missing_scenarios,
            coverage_gaps=coverage_gaps,
            reflection_summary="\n".join(summary_lines),
            quality_score=quality_score,
            score_breakdown=score_breakdown,
            api_health=api_health,
        )

    def _derive_tc_variation(self, tc: TestCase) -> str:
        """Derive a granular variation key for a test case."""
        if tc.scenario_type == ScenarioType.POSITIVE:
            return "happy_path"

        # Check path override
        overrides = (
            tc.query_params.get("_path_override", {})
            if isinstance(tc.query_params, dict)
            else {}
        )
        for val in overrides.values():
            if str(val) == "-1":
                return "negative"
            if str(val) in ["999999", "99999"]:
                return "out_of_bounds"

        # Check query params
        if tc.query_params and any(k != "_path_override" for k in tc.query_params):
            return "query"

        # Check body
        if tc.body == {}:
            return "empty_body"
        if isinstance(tc.body, dict):
            for k, v in tc.body.items():
                if "invalid" in str(v) or "@" not in str(v) and "email" in k:
                    return f"{k}:malformed"
                if isinstance(v, (int, float)) and k in ["username", "name"]:
                    return f"{k}:numeric_type"

        # Check auth
        if tc.headers and "Authorization" in tc.headers and not tc.headers["Authorization"]:
            return "missing_auth"

        return tc.scenario_type.value

    def _merge_feedback(
        self,
        heuristic: ReflectionFeedback,
        llm: ReflectionFeedback,
        iteration: int,
    ) -> ReflectionFeedback:
        """Merge LLM-derived insights with ground-truth execution evidence."""
        combined_issues = list(heuristic.identified_issues)
        existing_signatures = {
            (issue.endpoint, issue.category, issue.observation)
            for issue in combined_issues
        }

        for issue in llm.identified_issues:
            sig = (issue.endpoint, issue.category, issue.observation)
            if sig not in existing_signatures:
                combined_issues.append(issue)
                existing_signatures.add(sig)

        combined_missing = sorted(list(set(heuristic.missing_scenarios + llm.missing_scenarios)))
        combined_gaps = sorted(list(set(heuristic.coverage_gaps + llm.coverage_gaps)))

        # Average quality score if valid, bounded [0.0, 1.0]
        final_score = heuristic.quality_score
        if 0.0 <= llm.quality_score <= 1.0 and llm.quality_score > 0.0:
            final_score = round((heuristic.quality_score + llm.quality_score) / 2.0, 2)

        summary = (
            f"{llm.reflection_summary}\n\n[Ground-Truth Evidence Alignment]\n"
            f"- Evaluated {len(combined_issues)} total issues and {len(combined_missing)} missing scenario paths."
        ) if llm.reflection_summary else heuristic.reflection_summary

        return ReflectionFeedback(
            iteration=iteration,
            identified_issues=combined_issues,
            missing_scenarios=combined_missing,
            coverage_gaps=combined_gaps,
            reflection_summary=summary,
            quality_score=max(0.0, min(1.0, final_score)),
            score_breakdown=heuristic.score_breakdown,
            api_health=heuristic.api_health,
        )
