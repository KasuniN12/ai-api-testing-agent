"""Test case generator implementing structured LLM generation and multi-scenario synthesis."""

import ast
import json
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from core.llm_client import LLMClient, clean_code_fence
from models.schemas import (
    APIEndpoint,
    APISpecification,
    ScenarioType,
    TestCase,
    TestSuite,
)
from prompts.templates import SYSTEM_PROMPT_GENERATOR, TEST_GENERATION_PROMPT


class GeneratedTestCasesPayload(BaseModel):
    """Container for validated test cases returned by structured LLM parsing."""

    __test__ = False
    test_cases: List[TestCase] = Field(default_factory=list)


class TestGenerator:
    """Generates comprehensive, multi-scenario Pytest test suites for an API specification."""

    __test__ = False  # Prevent pytest from treating this as a test class

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()

    def generate_initial_suite(
        self, spec: APISpecification, base_url: str
    ) -> TestSuite:
        """Generate baseline test cases (V1) using structured data and controlled code synthesis."""
        target_base_url = (base_url or spec.base_url or "http://localhost:8000").rstrip("/")

        if self.llm.is_configured():
            test_cases = self._generate_structured_with_llm(spec, target_base_url)
        else:
            test_cases = self._generate_baseline_scenarios(spec)

        # Fallback to baseline scenarios if LLM returned empty list
        if not test_cases:
            test_cases = self._generate_baseline_scenarios(spec)

        # Validate and synthesize controlled Pytest code from structured test cases
        generated_code = self.build_pytest_code(test_cases, target_base_url)

        return TestSuite(
            suite_version="V1",
            iteration=1,
            generated_code=generated_code,
            test_cases=test_cases,
        )

    def _generate_structured_with_llm(
        self, spec: APISpecification, base_url: str
    ) -> List[TestCase]:
        """Prompt LLM to return validated structured TestCase objects."""
        prompt = TEST_GENERATION_PROMPT.format(
            openapi_spec=spec.model_dump_json(indent=2),
            base_url=base_url,
        )

        try:
            payload = self.llm.generate_structured(
                prompt=prompt,
                schema=GeneratedTestCasesPayload,
                system_prompt=SYSTEM_PROMPT_GENERATOR,
            )
            return payload.test_cases
        except Exception:
            # Fallback: attempt json completion or fallback to baseline
            try:
                raw_text = self.llm.generate(
                    prompt=prompt + "\nRespond with valid JSON containing a 'test_cases' list.",
                    system_prompt=SYSTEM_PROMPT_GENERATOR,
                )
                cleaned = clean_code_fence(raw_text)
                data = json.loads(cleaned)
                if isinstance(data, dict) and "test_cases" in data:
                    return [TestCase(**item) for item in data["test_cases"]]
                if isinstance(data, list):
                    return [TestCase(**item) for item in data]
            except Exception:
                pass
            return []

    def _generate_baseline_scenarios(self, spec: APISpecification) -> List[TestCase]:
        """Generate multi-scenario test cases (positive, boundary, invalid types, empty input)."""
        test_cases: List[TestCase] = []
        counter = 1

        for ep in spec.endpoints:
            # 1. Positive Scenario
            positive_tc = self._create_positive_scenario(ep, counter)
            test_cases.append(positive_tc)
            counter += 1

            # 2. Scenarios for request bodies (POST / PUT / PATCH)
            if ep.request_body_schema and isinstance(ep.request_body_schema, dict):
                # 2a. Empty Input / Empty Body
                test_cases.append(
                    TestCase(
                        test_id=f"TC-{counter:03d}",
                        endpoint_path=ep.path,
                        http_method=ep.method,
                        scenario_type=ScenarioType.EMPTY_INPUT,
                        description=f"Submit empty payload to {ep.method} {ep.path}",
                        body={},
                        expected_status=400,
                        validation_rules=["Verify 400 Bad Request returned on empty payload"],
                    )
                )
                counter += 1

                # 2b. Missing Required Fields
                required_props = ep.request_body_schema.get("required", [])
                if required_props:
                    missing_prop = required_props[0]
                    incomplete_body = self._generate_realistic_body(ep.request_body_schema) or {}
                    incomplete_body.pop(missing_prop, None)

                    test_cases.append(
                        TestCase(
                            test_id=f"TC-{counter:03d}",
                            endpoint_path=ep.path,
                            http_method=ep.method,
                            scenario_type=ScenarioType.EMPTY_INPUT,
                            description=f"Submit payload missing required field '{missing_prop}' to {ep.method} {ep.path}",
                            body=incomplete_body,
                            expected_status=400,
                            validation_rules=[f"Verify error response when '{missing_prop}' is missing"],
                        )
                    )
                    counter += 1

                # 2c. Invalid Data Types / Format Violations
                properties = ep.request_body_schema.get("properties", {})
                for prop_name, prop_meta in properties.items():
                    if prop_meta.get("format") == "email":
                        invalid_email_body = self._generate_realistic_body(ep.request_body_schema) or {}
                        invalid_email_body[prop_name] = "invalid-email-address-no-at"
                        test_cases.append(
                            TestCase(
                                test_id=f"TC-{counter:03d}",
                                endpoint_path=ep.path,
                                http_method=ep.method,
                                scenario_type=ScenarioType.INVALID_TYPE,
                                description=f"Submit malformed email address in field '{prop_name}' to {ep.method} {ep.path}",
                                body=invalid_email_body,
                                expected_status=400,
                                validation_rules=["Verify 400 on invalid email format"],
                            )
                        )
                        counter += 1
                        break  # One format check is sufficient per endpoint

            # 3. Scenarios for Path Parameters (e.g. /api/users/{id})
            has_path_param = any(p.get("in") == "path" for p in ep.parameters)
            if has_path_param:
                # 3a. Boundary: Non-existent ID
                test_cases.append(
                    TestCase(
                        test_id=f"TC-{counter:03d}",
                        endpoint_path=ep.path,
                        http_method=ep.method,
                        scenario_type=ScenarioType.BOUNDARY,
                        description=f"Request non-existent resource ID (99999) on {ep.method} {ep.path}",
                        query_params={"_path_override": {"id": "99999"}},
                        expected_status=404,
                        validation_rules=["Verify 404 Not Found returned for non-existent ID"],
                    )
                )
                counter += 1

            # 4. Scenarios for Authentication
            if ep.requires_auth:
                test_cases.append(
                    TestCase(
                        test_id=f"TC-{counter:03d}",
                        endpoint_path=ep.path,
                        http_method=ep.method,
                        scenario_type=ScenarioType.MISSING_AUTH,
                        description=f"Attempt unauthorized access without bearer token to {ep.method} {ep.path}",
                        headers={},  # Missing Authorization
                        expected_status=401,
                        validation_rules=["Verify 401 Unauthorized returned when credentials missing"],
                    )
                )
                counter += 1

        return test_cases

    def _create_positive_scenario(self, ep: APIEndpoint, counter: int) -> TestCase:
        """Create a valid positive success TestCase for an endpoint."""
        query_params = {
            p["name"]: p.get("schema", {}).get("default", 10)
            for p in ep.parameters
            if p.get("in") == "query" and "name" in p
        }

        body = self._generate_realistic_body(ep.request_body_schema)
        expected_status = self._get_expected_status(ep)

        return TestCase(
            test_id=f"TC-{counter:03d}",
            endpoint_path=ep.path,
            http_method=ep.method,
            scenario_type=ScenarioType.POSITIVE,
            description=ep.summary or f"Verify positive success flow for {ep.method} {ep.path}",
            query_params=query_params,
            body=body,
            expected_status=expected_status,
            validation_rules=[f"Verify HTTP status code is {expected_status}"],
        )

    def _generate_realistic_body(self, schema: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Generate realistic mock request body satisfying schema types and formats."""
        if not schema or not isinstance(schema, dict):
            return None

        body: Dict[str, Any] = {}
        properties = schema.get("properties", {})

        for prop_name, prop_meta in properties.items():
            p_type = prop_meta.get("type", "string")
            p_format = prop_meta.get("format", "")
            enum_values = prop_meta.get("enum", [])

            if enum_values:
                body[prop_name] = enum_values[0]
            elif p_format == "email":
                body[prop_name] = "alice.smith@example.com"
            elif "user" in prop_name.lower():
                body[prop_name] = "alice_smith"
            elif p_type == "integer":
                body[prop_name] = prop_meta.get("default", 1)
            elif p_type == "number":
                body[prop_name] = prop_meta.get("default", 1.0)
            elif p_type == "boolean":
                body[prop_name] = True
            elif p_type == "array":
                body[prop_name] = []
            else:
                body[prop_name] = f"test_{prop_name}"

        return body if body else None

    def _get_expected_status(self, ep: APIEndpoint) -> int:
        """Derive the expected success status code from endpoint response declarations."""
        for code in ["200", "201", "204"]:
            if code in ep.responses:
                return int(code)
        return 201 if ep.method == "POST" else 200

    def build_pytest_code(self, test_cases: List[TestCase], base_url: str) -> str:
        """Controlled application-side Pytest code synthesis from validated TestCases."""
        lines = [
            '"""Controlled Pytest test suite generated by AI API Testing Agent."""',
            "",
            "import pytest",
            "import httpx",
            "",
            f'BASE_URL = "{base_url}"',
            "",
        ]

        for tc in test_cases:
            func_name = self._make_unique_func_name(tc)
            resolved_path = self._resolve_path_for_test(tc)

            lines.append(f"def {func_name}():")
            lines.append(f'    """[{tc.test_id}] {tc.http_method} {tc.endpoint_path} | Scenario: {tc.scenario_type.value}')
            lines.append(f'    {tc.description}')
            lines.append('    """')
            lines.append(f'    url = f"{{BASE_URL}}{resolved_path}"')

            # Build query params if any (excluding internal path overrides)
            clean_params = {k: v for k, v in tc.query_params.items() if k != "_path_override"}
            req_kwargs = ["timeout=10.0"]

            if tc.headers:
                req_kwargs.append(f"headers={tc.headers}")
            if clean_params:
                req_kwargs.append(f"params={clean_params}")
            if tc.body is not None:
                req_kwargs.append(f"json={tc.body}")

            args_str = ", ".join(req_kwargs)
            method_lower = tc.http_method.lower()

            lines.append(f"    response = httpx.{method_lower}(url, {args_str})")
            lines.append(
                f"    assert response.status_code == {tc.expected_status}, "
                f"f'Expected {tc.expected_status}, got {{response.status_code}}: {{response.text}}'"
            )
            lines.append("")

        return "\n".join(lines)

    def _make_unique_func_name(self, tc: TestCase) -> str:
        """Construct a unique, descriptive Python test function identifier."""
        clean_id = tc.test_id.lower().replace("-", "_")
        clean_method = tc.http_method.lower()
        clean_path = re.sub(r"[{}]", "", tc.endpoint_path).strip("/").replace("/", "_").replace("-", "_")
        clean_scenario = tc.scenario_type.value.lower()
        return f"test_{clean_id}_{clean_method}_{clean_path}_{clean_scenario}"

    def _resolve_path_for_test(self, tc: TestCase) -> str:
        """Resolve path parameter placeholders (e.g. {id}) with concrete test values."""
        path = tc.endpoint_path
        # Check if an explicit path override was set (e.g. boundary test with id=99999)
        path_overrides = tc.query_params.get("_path_override", {}) if isinstance(tc.query_params, dict) else {}

        # Replace {id} or similar
        matches = re.findall(r"\{([a-zA-Z0-9_]+)\}", path)
        for param in matches:
            override_val = path_overrides.get(param)
            val = str(override_val) if override_val is not None else "1"
            path = path.replace(f"{{{param}}}", val)

        return path

    def extract_test_cases_from_code(
        self, code: str, spec: APISpecification
    ) -> List[TestCase]:
        """Utility for inspecting or reconstructing TestCase metadata from arbitrary Pytest code."""
        test_cases: List[TestCase] = []

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return test_cases

        idx = 1
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                docstring = ast.get_docstring(node) or ""
                endpoint_match = self._match_endpoint_from_node(node, spec.endpoints)

                test_cases.append(
                    TestCase(
                        test_id=f"TC-{idx:03d}",
                        endpoint_path=endpoint_match.path if endpoint_match else "/api",
                        http_method=endpoint_match.method if endpoint_match else "GET",
                        scenario_type=ScenarioType.POSITIVE,
                        description=docstring.strip() or f"Execute {node.name}",
                        expected_status=self._get_expected_status(endpoint_match) if endpoint_match else 200,
                    )
                )
                idx += 1

        return test_cases

    def _match_endpoint_from_node(
        self, node: ast.FunctionDef, endpoints: List[APIEndpoint]
    ) -> Optional[APIEndpoint]:
        """Match a test function AST node to its corresponding APIEndpoint by method and path."""
        detected_method = None
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                attr_upper = sub.func.attr.upper()
                if attr_upper in {"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"}:
                    detected_method = attr_upper
                    break

        doc = ast.get_docstring(node) or ""
        endpoint_tag_match = re.search(r"(/api/[^\s|]+)", doc)
        detected_path = endpoint_tag_match.group(1).strip() if endpoint_tag_match else None

        if detected_method and detected_path:
            for ep in endpoints:
                if ep.method == detected_method and ep.path == detected_path:
                    return ep

        name_lower = node.name.lower()
        for ep in endpoints:
            expected = ep.path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
            if expected in name_lower:
                return ep

        return None
