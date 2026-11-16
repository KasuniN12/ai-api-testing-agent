"""OpenAPI / Swagger specification parser module.

Extracts endpoints, methods, parameters, request body schemas,
responses, and security configurations into strongly typed Pydantic models.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import json
import yaml
import httpx
from models.schemas import APISpecification, APIEndpoint


class OpenAPIParser:
    """Parses JSON or YAML OpenAPI/Swagger specifications into structured APISpecification models."""

    SUPPORTED_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}

    def __init__(self, spec_path_or_url: Union[str, Path]):
        self.spec_source = str(spec_path_or_url)
        self.raw_spec: Dict[str, Any] = {}

    def load_raw_spec(self) -> Dict[str, Any]:
        """Read and decode the specification file from local disk or remote HTTP/HTTPS URL."""
        source = self.spec_source.strip()

        # Handle remote URL
        if source.startswith(("http://", "https://")):
            response = httpx.get(source, timeout=15.0)
            response.raise_for_status()
            text = response.text
            try:
                self.raw_spec = json.loads(text)
            except json.JSONDecodeError:
                self.raw_spec = yaml.safe_load(text) or {}
            return self.raw_spec

        # Handle local file
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"OpenAPI specification file not found: {source}")

        content = path.read_text(encoding="utf-8")
        if path.suffix.lower() in [".yaml", ".yml"]:
            self.raw_spec = yaml.safe_load(content) or {}
        else:
            try:
                self.raw_spec = json.loads(content)
            except json.JSONDecodeError:
                self.raw_spec = yaml.safe_load(content) or {}

        return self.raw_spec

    def resolve_ref(self, ref: str) -> Dict[str, Any]:
        """Resolve a local JSON Pointer reference (e.g. #/components/schemas/User)."""
        if not ref.startswith("#/"):
            return {"$ref": ref}  # External or non-standard refs preserved as-is

        parts = ref.lstrip("#/").split("/")
        curr = self.raw_spec
        for part in parts:
            if isinstance(curr, dict) and part in curr:
                curr = curr[part]
            else:
                return {}
        return curr if isinstance(curr, dict) else {}

    def dereference_schema(self, schema: Any, depth: int = 0) -> Any:
        """Recursively dereference $ref in schemas up to a maximum depth to prevent loops."""
        if depth > 10 or not isinstance(schema, dict):
            return schema

        if "$ref" in schema:
            resolved = self.resolve_ref(schema["$ref"])
            if resolved and resolved != schema:
                return self.dereference_schema(resolved, depth + 1)
            return schema

        result = {}
        for k, v in schema.items():
            if isinstance(v, dict):
                result[k] = self.dereference_schema(v, depth + 1)
            elif isinstance(v, list):
                result[k] = [
                    self.dereference_schema(item, depth + 1) if isinstance(item, dict) else item
                    for item in v
                ]
            else:
                result[k] = v
        return result

    def _extract_base_url(self) -> Optional[str]:
        """Extract default base URL from OpenAPI 3.x servers or Swagger 2.0 host/basePath."""
        # OpenAPI 3.x
        servers = self.raw_spec.get("servers", [])
        if servers and isinstance(servers, list):
            first_url = servers[0].get("url")
            if first_url:
                return first_url

        # Swagger 2.0
        host = self.raw_spec.get("host")
        if host:
            schemes = self.raw_spec.get("schemes", ["http"])
            base_path = self.raw_spec.get("basePath", "")
            scheme = schemes[0] if schemes else "http"
            return f"{scheme}://{host}{base_path}".rstrip("/")

        return None

    def _extract_parameters(
        self, op_params: List[Dict[str, Any]], path_params: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Merge path-level parameters with operation-level parameters, resolving refs."""
        merged: Dict[str, Dict[str, Any]] = {}

        # Add path-level first
        for p in path_params:
            if isinstance(p, dict):
                if "$ref" in p:
                    p = self.resolve_ref(p["$ref"])
                name = p.get("name")
                location = p.get("in")
                if name and location:
                    key = f"{location}:{name}"
                    merged[key] = self.dereference_schema(p)

        # Override / add operation-level
        for p in op_params:
            if isinstance(p, dict):
                if "$ref" in p:
                    p = self.resolve_ref(p["$ref"])
                name = p.get("name")
                location = p.get("in")
                if name and location:
                    key = f"{location}:{name}"
                    merged[key] = self.dereference_schema(p)

        return list(merged.values())

    def _extract_request_body(self, operation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract and dereference request body schema for OpenAPI 3.x or Swagger 2.0."""
        # OpenAPI 3.x: requestBody
        request_body = operation.get("requestBody")
        if request_body:
            if "$ref" in request_body:
                request_body = self.resolve_ref(request_body["$ref"])
            content = request_body.get("content", {})
            for media_type in ["application/json", "application/x-www-form-urlencoded", "*/*"]:
                if media_type in content and "schema" in content[media_type]:
                    return self.dereference_schema(content[media_type]["schema"])
            if content:
                first_media = next(iter(content.values()))
                if isinstance(first_media, dict) and "schema" in first_media:
                    return self.dereference_schema(first_media["schema"])

        # Swagger 2.0: parameter with in: "body"
        for p in operation.get("parameters", []):
            if isinstance(p, dict):
                if "$ref" in p:
                    p = self.resolve_ref(p["$ref"])
                if p.get("in") == "body" and "schema" in p:
                    return self.dereference_schema(p["schema"])

        return None

    def _has_security(self, operation: Dict[str, Any], global_security: List[Any]) -> bool:
        """Determine if endpoint requires authentication."""
        if "security" in operation:
            # An empty list explicitly overrides global security to none
            return len(operation["security"]) > 0
        return len(global_security) > 0

    def parse(self) -> APISpecification:
        """Parse raw spec into strongly-typed APISpecification and APIEndpoint models."""
        raw = self.load_raw_spec()

        info = raw.get("info", {})
        title = info.get("title", "Target API")
        version = info.get("version", "1.0.0")
        base_url = self._extract_base_url()
        global_security = raw.get("security", [])

        endpoints: List[APIEndpoint] = []
        paths = raw.get("paths", {})

        for path_pattern, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue

            path_params = path_item.get("parameters", [])

            for method_name, operation in path_item.items():
                method_lower = method_name.lower()
                if method_lower not in self.SUPPORTED_METHODS or not isinstance(operation, dict):
                    continue

                op_params = operation.get("parameters", [])
                parameters = self._extract_parameters(op_params, path_params)
                body_schema = self._extract_request_body(operation)

                # Dereference responses
                responses = {}
                for status_code, resp_obj in operation.get("responses", {}).items():
                    if isinstance(resp_obj, dict):
                        if "$ref" in resp_obj:
                            resp_obj = self.resolve_ref(resp_obj["$ref"])
                        responses[str(status_code)] = self.dereference_schema(resp_obj)

                requires_auth = self._has_security(operation, global_security)

                endpoint = APIEndpoint(
                    path=path_pattern,
                    method=method_lower.upper(),
                    summary=operation.get("summary"),
                    description=operation.get("description"),
                    parameters=parameters,
                    request_body_schema=body_schema,
                    responses=responses,
                    requires_auth=requires_auth,
                )
                endpoints.append(endpoint)

        return APISpecification(
            title=title,
            version=version,
            base_url=base_url,
            endpoints=endpoints,
        )
