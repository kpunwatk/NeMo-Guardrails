# SPDX-FileCopyrightText: Copyright (c) 2023-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Integration tests for runtime state API endpoints (/v1/runtime/*)."""

import os

import pytest
from fastapi.testclient import TestClient

from nemoguardrails.server import api


@pytest.fixture(scope="function", autouse=True)
def set_rails_config_path():
    """Set up test config path and clean up after tests."""
    original_path = api.app.rails_config_path
    original_engine = os.environ.get("MAIN_MODEL_ENGINE")
    api.app.rails_config_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "test_configs"))
    os.environ["MAIN_MODEL_ENGINE"] = "custom_llm"
    api.llm_rails_instances.clear()
    yield
    api.app.rails_config_path = original_path
    api.llm_rails_instances.clear()
    if original_engine is not None:
        os.environ["MAIN_MODEL_ENGINE"] = original_engine
    else:
        os.environ.pop("MAIN_MODEL_ENGINE", None)


@pytest.fixture
def client_single_config():
    """Test client in single-config mode."""
    original_single_config_mode = api.app.single_config_mode
    original_single_config_id = api.app.single_config_id
    original_rails_config_path = api.app.rails_config_path

    api.app.single_config_mode = True
    api.app.single_config_id = "simple_rails"
    # In single-config mode, rails_config_path points directly to the config directory
    api.app.rails_config_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "test_configs", "simple_rails"))

    client = TestClient(api.app)
    yield client

    api.app.single_config_mode = original_single_config_mode
    api.app.single_config_id = original_single_config_id
    api.app.rails_config_path = original_rails_config_path
    api.llm_rails_instances.clear()


@pytest.fixture
def client_multi_config():
    """Test client in multi-config mode."""
    original_single_config_mode = api.app.single_config_mode
    original_single_config_id = api.app.single_config_id

    api.app.single_config_mode = False
    api.app.single_config_id = None

    client = TestClient(api.app)
    yield client

    api.app.single_config_mode = original_single_config_mode
    api.app.single_config_id = original_single_config_id
    api.llm_rails_instances.clear()


class TestRuntimeRailsEndpoint:
    """Tests for GET /v1/runtime/rails endpoint."""

    def test_endpoint_exists(self, client_single_config):
        """Endpoint is available and returns 200."""
        response = client_single_config.get("/v1/runtime/rails")
        assert response.status_code == 200

    def test_single_config_no_param_returns_default(self, client_single_config):
        """In single-config mode, config_id is optional and uses default."""
        response = client_single_config.get("/v1/runtime/rails")
        assert response.status_code == 200
        data = response.json()
        assert data["config_id"] == "simple_rails"

    def test_single_config_with_matching_param(self, client_single_config):
        """In single-config mode, correct config_id returns 200."""
        response = client_single_config.get("/v1/runtime/rails?config_id=simple_rails")
        assert response.status_code == 200
        data = response.json()
        assert data["config_id"] == "simple_rails"

    def test_single_config_with_mismatched_param(self, client_single_config):
        """In single-config mode, wrong config_id returns 404."""
        response = client_single_config.get("/v1/runtime/rails?config_id=nonexistent")
        assert response.status_code == 404
        data = response.json()
        # Check for error message in either 'detail' or 'error.message' depending on exception handler
        error_msg = data.get("detail") or data.get("error", {}).get("message", "")
        assert "No guardrail configuration" in error_msg

    def test_multi_config_missing_param_returns_400(self, client_multi_config):
        """In multi-config mode, missing config_id returns 400."""
        response = client_multi_config.get("/v1/runtime/rails")
        assert response.status_code == 400
        data = response.json()
        error_msg = data.get("detail") or data.get("error", {}).get("message", "")
        assert "Missing required query parameter" in error_msg

    def test_multi_config_with_valid_config(self, client_multi_config):
        """In multi-config mode, valid config_id returns 200."""
        response = client_multi_config.get("/v1/runtime/rails?config_id=simple_rails")
        assert response.status_code == 200
        data = response.json()
        assert data["config_id"] == "simple_rails"

    def test_multi_config_with_invalid_config(self, client_multi_config):
        """In multi-config mode, invalid config_id returns 404."""
        response = client_multi_config.get("/v1/runtime/rails?config_id=nonexistent")
        assert response.status_code == 404
        data = response.json()
        error_msg = data.get("detail") or data.get("error", {}).get("message", "")
        assert "No guardrail configuration" in error_msg

    def test_response_schema_compliance(self, client_single_config):
        """Response matches RuntimeRailsResponse schema."""
        response = client_single_config.get("/v1/runtime/rails")
        data = response.json()

        # Validate response structure
        assert "config_id" in data
        assert "input_rails" in data
        assert "output_rails" in data
        assert "retrieval_rails" in data
        assert "dialog_rails" in data
        assert "action_rails" in data
        assert "tool_input_rails" in data
        assert "tool_output_rails" in data
        assert "colang_version" in data

    def test_rails_with_flows_are_lists(self, client_single_config):
        """Each rail type is a list of flow objects."""
        response = client_single_config.get("/v1/runtime/rails")
        data = response.json()

        for rail_type in ["input_rails", "output_rails", "retrieval_rails", "tool_input_rails", "tool_output_rails"]:
            assert isinstance(data[rail_type], list)
            for flow in data[rail_type]:
                assert "name" in flow
                assert "type" in flow


class TestRuntimeActionsEndpoint:
    """Tests for GET /v1/runtime/actions endpoint."""

    def test_endpoint_exists(self, client_single_config):
        """Endpoint is available and returns 200."""
        response = client_single_config.get("/v1/runtime/actions")
        assert response.status_code == 200

    def test_single_config_no_param_returns_default(self, client_single_config):
        """In single-config mode, config_id is optional."""
        response = client_single_config.get("/v1/runtime/actions")
        assert response.status_code == 200
        data = response.json()
        assert data["config_id"] == "simple_rails"

    def test_multi_config_missing_param_returns_400(self, client_multi_config):
        """In multi-config mode, missing config_id returns 400."""
        response = client_multi_config.get("/v1/runtime/actions")
        assert response.status_code == 400
        data = response.json()
        error_msg = data.get("detail") or data.get("error", {}).get("message", "")
        assert "Missing required query parameter" in error_msg

    def test_response_schema_compliance(self, client_single_config):
        """Response matches RuntimeActionsResponse schema."""
        response = client_single_config.get("/v1/runtime/actions")
        data = response.json()

        assert "config_id" in data
        assert "actions" in data
        assert isinstance(data["actions"], list)
        # Live ActionDispatcher should register at least one built-in action
        assert len(data["actions"]) > 0
        for action in data["actions"]:
            assert "name" in action
            assert isinstance(action["name"], str)
            assert action["name"]
            assert "source" in action
            assert action["source"] in {"built-in", "custom", "unknown"}
            assert "description" in action  # null is ok
            assert "parameters" in action  # null is ok

    def test_unknown_config_returns_404(self, client_multi_config):
        """Unknown config_id returns 404."""
        response = client_multi_config.get("/v1/runtime/actions?config_id=nonexistent")
        assert response.status_code == 404

    def test_action_source_classification(self, client_single_config):
        """Actions have source field with valid classification."""
        response = client_single_config.get("/v1/runtime/actions")
        data = response.json()

        sources = {action["source"] for action in data["actions"]}
        # Should have at least one built-in action from manifest
        assert len(sources & {"built-in", "custom", "unknown"}) > 0


class TestRuntimeConfigEndpoint:
    """Tests for GET /v1/runtime/config endpoint."""

    def test_endpoint_exists(self, client_single_config):
        """Endpoint is available and returns 200."""
        response = client_single_config.get("/v1/runtime/config")
        assert response.status_code == 200

    def test_single_config_no_param_returns_default(self, client_single_config):
        """In single-config mode, config_id is optional."""
        response = client_single_config.get("/v1/runtime/config")
        assert response.status_code == 200
        data = response.json()
        assert data["config_id"] == "simple_rails"

    def test_multi_config_missing_param_returns_400(self, client_multi_config):
        """In multi-config mode, missing config_id returns 400."""
        response = client_multi_config.get("/v1/runtime/config")
        assert response.status_code == 400
        data = response.json()
        error_msg = data.get("detail") or data.get("error", {}).get("message", "")
        assert "Missing required query parameter" in error_msg

    def test_response_schema_compliance(self, client_single_config):
        """Response matches RuntimeConfigResponse schema."""
        response = client_single_config.get("/v1/runtime/config")
        data = response.json()

        assert "config_id" in data
        assert "colang_version" in data
        assert "models" in data
        assert "rails" in data
        assert "flows" in data
        assert "instructions" in data
        assert "prompts_count" in data
        assert "knowledge_base" in data

    def test_models_list(self, client_single_config):
        """Models list contains valid RuntimeModelModel objects."""
        response = client_single_config.get("/v1/runtime/config")
        data = response.json()

        assert isinstance(data["models"], list)
        for model in data["models"]:
            assert "type" in model
            assert "engine" in model
            assert "model" in model  # May be null if model is in parameters
            # Secrets should not be included
            assert "api_key_env_var" not in model
            assert "parameters" not in model

    def test_model_can_be_null(self, client_single_config):
        """Model field can be null for configs with model in parameters."""
        # This test validates that RuntimeModelModel.model is Optional
        # Actual null models depend on test config — just ensure no 500
        response = client_single_config.get("/v1/runtime/config")
        assert response.status_code == 200
        data = response.json()
        # If any model has null model field, that's valid (no error)
        assert "models" in data

    def test_knowledge_base_structure(self, client_single_config):
        """Knowledge base has valid structure."""
        response = client_single_config.get("/v1/runtime/config")
        data = response.json()

        kb = data["knowledge_base"]
        assert isinstance(kb, dict)
        assert "docs_count" in kb
        assert "embedding_model" in kb
        # embedding_model can be null (extracted from provider.name if available)
        assert kb["embedding_model"] is None or isinstance(kb["embedding_model"], str)


class TestSecretsFiltering:
    """Tests to verify secrets are not exposed in responses."""

    def test_no_api_key_env_var_in_models(self, client_single_config):
        """RuntimeModelModel does not expose api_key_env_var."""
        response = client_single_config.get("/v1/runtime/config")
        data = response.json()

        for model in data["models"]:
            assert "api_key_env_var" not in model

    def test_no_parameters_dict_in_models(self, client_single_config):
        """RuntimeModelModel does not expose parameters field."""
        response = client_single_config.get("/v1/runtime/config")
        data = response.json()

        for model in data["models"]:
            assert "parameters" not in model


class TestErrorResponses:
    """Tests for error responses."""

    def test_missing_config_in_single_config_mode(self, client_single_config):
        """Wrong config_id in single-config mode returns 404 with detail."""
        response = client_single_config.get("/v1/runtime/rails?config_id=wrong")
        assert response.status_code == 404
        data = response.json()
        error_msg = data.get("detail") or data.get("error", {}).get("message", "")
        assert error_msg  # Just verify we have an error message

    def test_missing_param_in_multi_config_mode(self, client_multi_config):
        """Missing config_id in multi-config mode returns 400 for all endpoints."""
        for endpoint in ["/v1/runtime/rails", "/v1/runtime/actions", "/v1/runtime/config"]:
            response = client_multi_config.get(endpoint)
            assert response.status_code == 400
            data = response.json()
            error_msg = data.get("detail") or data.get("error", {}).get("message", "")
            assert "Missing required query parameter" in error_msg


class TestOpenAPISchema:
    """Tests for OpenAPI schema generation."""

    def test_openapi_spec_includes_runtime_endpoints(self, client_single_config):
        """OpenAPI spec includes all 3 runtime endpoints with field descriptions."""
        response = client_single_config.get("/openapi.json")
        assert response.status_code == 200
        spec = response.json()

        paths = spec.get("paths", {})
        assert "/v1/runtime/rails" in paths
        assert "/v1/runtime/actions" in paths
        assert "/v1/runtime/config" in paths

        # Verify schemas have field descriptions
        schemas = spec.get("components", {}).get("schemas", {})
        for schema_name in ["RuntimeRailsResponse", "RuntimeActionsResponse", "RuntimeConfigResponse"]:
            assert schema_name in schemas, f"Missing schema {schema_name}"
            schema = schemas[schema_name]
            # All properties should have descriptions
            for prop_name, prop_schema in schema.get("properties", {}).items():
                assert "description" in prop_schema, f"{schema_name}.{prop_name} missing description"
                assert prop_schema["description"], f"{schema_name}.{prop_name} has empty description"
