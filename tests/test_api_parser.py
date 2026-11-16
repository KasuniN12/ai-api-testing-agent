"""Comprehensive unit tests for the OpenAPI / Swagger specification parser."""

import pytest
from pathlib import Path
from core.api_parser import OpenAPIParser


def test_parser_loads_spec():
    sample_spec = Path("examples/sample_openapi.json")
    assert sample_spec.exists(), "Sample OpenAPI spec file should exist"

    parser = OpenAPIParser(sample_spec)
    raw = parser.load_raw_spec()
    assert "openapi" in raw
    assert "paths" in raw


def test_parser_extracts_metadata():
    sample_spec = Path("examples/sample_openapi.json")
    parser = OpenAPIParser(sample_spec)
    spec = parser.parse()

    assert spec.title == "Sample User Management API"
    assert spec.version == "1.0.0"
    assert spec.base_url == "http://localhost:8000"


def test_parser_extracts_all_endpoints():
    sample_spec = Path("examples/sample_openapi.json")
    parser = OpenAPIParser(sample_spec)
    spec = parser.parse()

    # In sample_openapi.json:
    # 1. GET /api/users
    # 2. POST /api/users
    # 3. GET /api/users/{id}
    # 4. DELETE /api/users/{id}
    assert len(spec.endpoints) == 4

    routes = [(e.method, e.path) for e in spec.endpoints]
    assert ("GET", "/api/users") in routes
    assert ("POST", "/api/users") in routes
    assert ("GET", "/api/users/{id}") in routes
    assert ("DELETE", "/api/users/{id}") in routes


def test_parser_extracts_request_body_schema():
    sample_spec = Path("examples/sample_openapi.json")
    parser = OpenAPIParser(sample_spec)
    spec = parser.parse()

    post_user = next(
        e for e in spec.endpoints if e.path == "/api/users" and e.method == "POST"
    )
    assert post_user.request_body_schema is not None
    assert post_user.request_body_schema.get("type") == "object"
    assert "username" in post_user.request_body_schema.get("properties", {})
    assert "email" in post_user.request_body_schema.get("properties", {})
    assert "required" in post_user.request_body_schema
    assert set(post_user.request_body_schema["required"]) == {"username", "email"}


def test_parser_extracts_parameters():
    sample_spec = Path("examples/sample_openapi.json")
    parser = OpenAPIParser(sample_spec)
    spec = parser.parse()

    # Query param on GET /api/users
    get_users = next(
        e for e in spec.endpoints if e.path == "/api/users" and e.method == "GET"
    )
    assert len(get_users.parameters) == 1
    param = get_users.parameters[0]
    assert param["name"] == "limit"
    assert param["in"] == "query"

    # Path param on GET /api/users/{id}
    get_user = next(
        e for e in spec.endpoints if e.path == "/api/users/{id}" and e.method == "GET"
    )
    assert len(get_user.parameters) == 1
    path_param = get_user.parameters[0]
    assert path_param["name"] == "id"
    assert path_param["in"] == "path"
    assert path_param["required"] is True


def test_parser_resolves_local_refs(tmp_path):
    spec_with_refs = {
        "openapi": "3.0.0",
        "info": {"title": "Ref Test API", "version": "2.0"},
        "components": {
            "schemas": {
                "Item": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "price": {"type": "number"},
                    },
                    "required": ["name"],
                }
            }
        },
        "paths": {
            "/items": {
                "post": {
                    "summary": "Create item",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Item"}
                            }
                        }
                    },
                    "responses": {"201": {"description": "Created"}},
                }
            }
        },
    }

    import json
    spec_file = tmp_path / "spec_ref.json"
    spec_file.write_text(json.dumps(spec_with_refs), encoding="utf-8")

    parser = OpenAPIParser(spec_file)
    spec = parser.parse()
    assert len(spec.endpoints) == 1
    endpoint = spec.endpoints[0]
    assert endpoint.request_body_schema is not None
    # Verify the reference was resolved to the Item schema
    assert endpoint.request_body_schema.get("type") == "object"
    assert "price" in endpoint.request_body_schema.get("properties", {})


def test_parser_file_not_found():
    parser = OpenAPIParser("non_existent_file.yaml")
    with pytest.raises(FileNotFoundError):
        parser.parse()
