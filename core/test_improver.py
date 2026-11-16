"""Test Improver module generating enhanced test suite (V2, V3, ...) from reflection feedback."""

import logging
import re
from typing import Dict, List, Optional, Set
from config.settings import get_settings
from core.llm_client import LLMClient
from core.test_generator import TestGenerator
from models.schemas import (
    APIEndpoint,
    APISpecification,
    ReflectionFeedback,
    ScenarioType,
    TestCase,
    TestSuite,
)
from prompts.templates import SYSTEM_PROMPT_IMPROVER, TEST_IMPROVEMENT_PROMPT

logger = logging.getLogger(__name__)


class TestImprover:
    """Generates refined Pytest test suites (V2..Vn) incorporating reflection feedback."""

    __test__ = False  # Prevent pytest from treating this as a test class

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()
        self.generator = TestGenerator(llm_client=self.llm)
        self.settings = get_settings()

    def generate_improved_suite(
        self,
        spec: APISpecification,
        current_suite: TestSuite,
        reflection: ReflectionFeedback,
        base_url: Optional[str] = None,
    ) -> TestSuite:
        """Synthesize previous test suite with reflection findings to output next iteration suite."""
        target_url = base_url or spec.base_url or self.settings.TARGET_API_BASE_URL
        next_iteration = current_suite.iteration + 1
        next_version = f"V{next_iteration}"

        # 1. Start with copy of existing test cases
        improved_test_cases: List[TestCase] = [tc.model_copy() for tc in current_suite.test_cases]
        existing_signatures: Set[str] = {
            f"{tc.http_method.upper()}:{tc.endpoint_path}:{tc.scenario_type.value}:{self._tc_payload_hash(tc)}"
            for tc in improved_test_cases
        }

        # Determine next test ID counter
        highest_id = 0
        for tc in improved_test_cases:
            match = re.search(r"TC-(\d+)", tc.test_id)
            if match:
                highest_id = max(highest_id, int(match.group(1)))
        counter = highest_id + 1

        # 2. Check identified issues to adjust any faulty expectations
        issue_endpoints = {issue.endpoint: issue for issue in reflection.identified_issues}
        for tc in improved_test_cases:
            if tc.endpoint_path in issue_endpoints:
                issue = issue_endpoints[tc.endpoint_path]
                if issue.category == "unhandled_status_code" and "expected" in issue.observation:
                    # Calibration note in description
                    tc.description = f"{tc.description} (Reflected: {issue.recommended_action})"

        # 3. Generate edge-case test cases addressing missing scenarios
        new_edge_cases = self._generate_edge_cases_from_reflection(
            spec=spec,
            reflection=reflection,
            start_counter=counter,
            existing_signatures=existing_signatures,
        )
        improved_test_cases.extend(new_edge_cases)

        # 4. If LLM is configured, query LLM for additional subtle edge cases
        is_llm_configured = (
            self.llm.is_configured()
            if callable(self.llm.is_configured)
            else bool(self.llm.is_configured)
        )
        if is_llm_configured:
            try:
                llm_cases = self._query_llm_improvements(
                    spec=spec,
                    current_suite=current_suite,
                    reflection=reflection,
                    start_counter=counter + len(new_edge_cases),
                    existing_signatures=existing_signatures,
                )
                improved_test_cases.extend(llm_cases)
            except Exception as exc:
                logger.warning(f"LLM test improvement query failed, relying on deterministic improver: {exc}")

        # 5. Build clean, application-controlled Pytest code
        generated_code = self.generator.build_pytest_code(improved_test_cases, target_url)

        return TestSuite(
            suite_version=next_version,
            iteration=next_iteration,
            generated_code=generated_code,
            test_cases=improved_test_cases,
        )

    def _generate_edge_cases_from_reflection(
        self,
        spec: APISpecification,
        reflection: ReflectionFeedback,
        start_counter: int,
        existing_signatures: Set[str],
    ) -> List[TestCase]:
        """Synthesize concrete edge-case TestCases based on reflection feedback and spec."""
        new_cases: List[TestCase] = []
        counter = start_counter
        endpoint_map: Dict[str, APIEndpoint] = {f"{ep.method.upper()} {ep.path}": ep for ep in spec.endpoints}

        # Generate from missing scenarios
        for missing in reflection.missing_scenarios:
            parts = missing.split(" missing scenario: ")
            if len(parts) != 2:
                continue
            ep_key, scenario_str = parts[0].strip(), parts[1].strip()
            ep = endpoint_map.get(ep_key)
            if not ep:
                continue

            scenario_base = scenario_str.split()[0].strip().lower()

            # A. Boundary Cases
            if scenario_base == ScenarioType.BOUNDARY.value:
                # A1. Query Parameter Boundary (e.g. limit=-1)
                if "field: query" in scenario_str or "variation: invalid_filter" in scenario_str:
                    query_params = [p.get("name") for p in ep.parameters if p.get("in") == "query"]
                    q_param = query_params[0] if query_params else "limit"
                    sig_q = f"{ep.method.upper()}:{ep.path}:{ScenarioType.BOUNDARY.value}:{q_param}_-1"
                    if sig_q not in existing_signatures:
                        new_cases.append(
                            TestCase(
                                test_id=f"TC-{counter:03d}",
                                endpoint_path=ep.path,
                                http_method=ep.method,
                                scenario_type=ScenarioType.BOUNDARY,
                                description=f"Query parameter negative boundary check '{q_param}=-1' on {ep.method} {ep.path}",
                                query_params={q_param: "-1"},
                                expected_status=400,
                                validation_rules=[f"Verify 400 Bad Request on invalid query parameter '{q_param}'"],
                            )
                        )
                        existing_signatures.add(sig_q)
                        counter += 1

                # A2. Path Parameter Boundary
                if "{" in ep.path:
                    # Negative ID
                    sig_neg = f"{ep.method.upper()}:{ep.path}:{ScenarioType.BOUNDARY.value}:id_-1"
                    if sig_neg not in existing_signatures:
                        new_cases.append(
                            TestCase(
                                test_id=f"TC-{counter:03d}",
                                endpoint_path=ep.path,
                                http_method=ep.method,
                                scenario_type=ScenarioType.BOUNDARY,
                                description=f"Negative ID boundary check on {ep.method} {ep.path}",
                                query_params={"_path_override": {"id": "-1"}},
                                expected_status=404 if ep.method in ["GET", "DELETE"] else 400,
                                validation_rules=["Verify 400/404 returned on negative entity ID"],
                            )
                        )
                        existing_signatures.add(sig_neg)
                        counter += 1

                    # Out-of-bounds large ID
                    sig_large = f"{ep.method.upper()}:{ep.path}:{ScenarioType.BOUNDARY.value}:id_999999"
                    if sig_large not in existing_signatures:
                        new_cases.append(
                            TestCase(
                                test_id=f"TC-{counter:03d}",
                                endpoint_path=ep.path,
                                http_method=ep.method,
                                scenario_type=ScenarioType.BOUNDARY,
                                description=f"Non-existent entity ID boundary check on {ep.method} {ep.path}",
                                query_params={"_path_override": {"id": "999999"}},
                                expected_status=404,
                                validation_rules=["Verify 404 Not Found returned when entity does not exist"],
                            )
                        )
                        existing_signatures.add(sig_large)
                        counter += 1

            # B. Empty Input (Empty JSON payload or missing required fields)
            elif scenario_base == ScenarioType.EMPTY_INPUT.value and ep.request_body_schema:
                # B1. Omit specific required field
                match_rf = re.search(r"field:\s*([a-zA-Z0-9_]+)", scenario_str)
                if match_rf and match_rf.group(1) != "body":
                    missing_field = match_rf.group(1)
                    sig_missing_field = f"{ep.method.upper()}:{ep.path}:{ScenarioType.EMPTY_INPUT.value}:omit_{missing_field}"
                    if sig_missing_field not in existing_signatures:
                        req_body = self.generator._generate_realistic_body(ep.request_body_schema) or {}
                        req_body.pop(missing_field, None)
                        new_cases.append(
                            TestCase(
                                test_id=f"TC-{counter:03d}",
                                endpoint_path=ep.path,
                                http_method=ep.method,
                                scenario_type=ScenarioType.EMPTY_INPUT,
                                description=f"Submit payload omitting required field '{missing_field}' to {ep.method} {ep.path}",
                                body=req_body,
                                expected_status=400,
                                validation_rules=[f"Verify 400 Bad Request when '{missing_field}' is missing"],
                            )
                        )
                        existing_signatures.add(sig_missing_field)
                        counter += 1
                else:
                    # B2. Completely empty payload {}
                    sig_empty = f"{ep.method.upper()}:{ep.path}:{ScenarioType.EMPTY_INPUT.value}:empty_body"
                    if sig_empty not in existing_signatures:
                        new_cases.append(
                            TestCase(
                                test_id=f"TC-{counter:03d}",
                                endpoint_path=ep.path,
                                http_method=ep.method,
                                scenario_type=ScenarioType.EMPTY_INPUT,
                                description=f"Send empty JSON payload to {ep.method} {ep.path}",
                                body={},
                                expected_status=400,
                                validation_rules=["Verify 400 Bad Request on empty payload"],
                            )
                        )
                        existing_signatures.add(sig_empty)
                        counter += 1

            # C. Invalid Data Types / Malformed Formats
            elif scenario_base == ScenarioType.INVALID_TYPE.value and ep.request_body_schema:
                sig_inv = f"{ep.method.upper()}:{ep.path}:{ScenarioType.INVALID_TYPE.value}:bad_type"
                if sig_inv not in existing_signatures:
                    bad_body = {"username": 12345, "email": "not-an-email-at-all", "role": "unrecognized_role"}
                    new_cases.append(
                        TestCase(
                            test_id=f"TC-{counter:03d}",
                            endpoint_path=ep.path,
                            http_method=ep.method,
                            scenario_type=ScenarioType.INVALID_TYPE,
                            description=f"Type & format violation payload sent to {ep.method} {ep.path}",
                            body=bad_body,
                            expected_status=400,
                            validation_rules=["Verify 400 Bad Request on type violation"],
                        )
                    )
                    existing_signatures.add(sig_inv)
                    counter += 1

            # D. Missing / Invalid Authentication
            elif scenario_base == ScenarioType.MISSING_AUTH.value:
                sig_auth = f"{ep.method.upper()}:{ep.path}:{ScenarioType.MISSING_AUTH.value}:no_auth"
                if sig_auth not in existing_signatures:
                    override = {"_path_override": {"id": "1"}} if "{" in ep.path else {}
                    new_cases.append(
                        TestCase(
                            test_id=f"TC-{counter:03d}",
                            endpoint_path=ep.path,
                            http_method=ep.method,
                            scenario_type=ScenarioType.MISSING_AUTH,
                            description=f"Unauthorized request without valid credentials to {ep.method} {ep.path}",
                            query_params=override,
                            headers={"Authorization": ""},
                            expected_status=401,
                            validation_rules=["Verify 401 Unauthorized when auth header is missing/invalid"],
                        )
                    )
                    existing_signatures.add(sig_auth)
                    counter += 1

        # Check coverage gaps for completely untested endpoints
        for gap in reflection.coverage_gaps:
            for ep_key, ep in endpoint_map.items():
                if ep_key in gap:
                    sig_pos = f"{ep.method.upper()}:{ep.path}:{ScenarioType.POSITIVE.value}:baseline"
                    if sig_pos not in existing_signatures:
                        new_cases.append(
                            TestCase(
                                test_id=f"TC-{counter:03d}",
                                endpoint_path=ep.path,
                                http_method=ep.method,
                                scenario_type=ScenarioType.POSITIVE,
                                description=f"Add initial coverage for untested endpoint {ep.method} {ep.path}",
                                expected_status=200 if ep.method != "POST" else 201,
                                validation_rules=["Verify baseline success"],
                            )
                        )
                        existing_signatures.add(sig_pos)
                        counter += 1

        return new_cases

    def _query_llm_improvements(
        self,
        spec: APISpecification,
        current_suite: TestSuite,
        reflection: ReflectionFeedback,
        start_counter: int,
        existing_signatures: Set[str],
    ) -> List[TestCase]:
        """Query LLM to generate targeted edge case TestCases based on reflection prompt."""
        from core.test_generator import GeneratedTestCasesPayload

        prompt = TEST_IMPROVEMENT_PROMPT.format(
            openapi_spec=spec.model_dump_json(indent=2),
            test_suite_v1=current_suite.generated_code[:2000],
            reflection_report=reflection.model_dump_json(indent=2),
        )

        payload = self.llm.structured_completion(
            prompt=prompt,
            response_model=GeneratedTestCasesPayload,
            system_prompt=SYSTEM_PROMPT_IMPROVER,
        )

        added: List[TestCase] = []
        if payload and payload.test_cases:
            cur = start_counter
            for tc in payload.test_cases:
                sig = f"{tc.http_method.upper()}:{tc.endpoint_path}:{tc.scenario_type.value}:{self._tc_payload_hash(tc)}"
                if sig not in existing_signatures:
                    tc.test_id = f"TC-{cur:03d}"
                    added.append(tc)
                    existing_signatures.add(sig)
                    cur += 1

        return added

    def _tc_payload_hash(self, tc: TestCase) -> str:
        """Helper to create a lightweight identity signature for a TestCase payload."""
        override = (
            str(tc.query_params.get("_path_override", ""))
            if isinstance(tc.query_params, dict)
            else ""
        )
        body_keys = (
            ",".join(sorted(tc.body.keys()))
            if isinstance(tc.body, dict)
            else str(type(tc.body))
        )
        return f"{override}_{body_keys}"
