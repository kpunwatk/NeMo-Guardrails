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

"""Schemas for the runtime state API endpoints (/v1/runtime/*).

These models expose the parsed configuration state of the NeMo-Guardrails
server at request time. All data is derived from RailsConfig and LLMRails
instances without runtime-specific state tracking (toggles, timestamps, etc).

Field Exclusion Rules:
- SAFE (included in responses): Flow names, rail types, model names, colang version,
  instruction content, prompt templates
- UNSAFE (excluded): API keys, environment variables, actions_server_url,
  embeddings/knowledge base connection details, authentication tokens
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RuntimeRailFlowModel(BaseModel):
    """A single flow configured for a rail type (input/output/retrieval/etc)."""

    name: str = Field(description="Name of the Colang flow implementing this rail.")
    type: str = Field(description="Rail type category: input, output, retrieval, dialog, actions, tool_input, or tool_output.")


class RuntimeModelModel(BaseModel):
    """A configured LLM model accessible to this guardrails configuration.

    Secret-bearing fields (api_key_env_var, parameters containing credentials)
    are intentionally excluded.
    """

    type: str = Field(description="Model type: 'main' for the primary LLM, 'embedding' for embeddings, etc.")
    engine: str = Field(description="LLM provider engine name: 'openai', 'azure', 'nim', 'huggingface', etc.")
    model: str = Field(description="Model identifier or name within the engine (e.g., 'gpt-4', 'llama-2-7b').")
    mode: str = Field(
        default="chat",
        description="Completion mode: 'chat' for multi-turn conversation or 'text' for single-turn text completion.",
    )


class RuntimeRailsResponse(BaseModel):
    """Configuration state for input/output/retrieval/dialog/action/tool rails in a guardrails config.

    Each rail type tracks which Colang flows are enabled via configuration.
    Rail enabled/disabled toggles do not exist at runtime; rails are enabled
    exclusively by listing their flow names in configuration.
    """

    config_id: str = Field(description="Identifier of the guardrails configuration.")

    input_rails: List[RuntimeRailFlowModel] = Field(
        default_factory=list,
        description="Flows that validate and filter user input messages.",
    )

    output_rails: List[RuntimeRailFlowModel] = Field(
        default_factory=list,
        description="Flows that validate and filter LLM-generated output messages.",
    )

    retrieval_rails: List[RuntimeRailFlowModel] = Field(
        default_factory=list,
        description="Flows that validate and filter retrieved documents in RAG workflows.",
    )

    dialog_rails: List[RuntimeRailFlowModel] = Field(
        default_factory=list,
        description="Flows that perform topical control and user intent classification.",
    )

    action_rails: List[RuntimeRailFlowModel] = Field(
        default_factory=list,
        description="Flows that control action execution policies and validation.",
    )

    tool_input_rails: List[RuntimeRailFlowModel] = Field(
        default_factory=list,
        description="Flows that validate and filter tool call results before processing.",
    )

    tool_output_rails: List[RuntimeRailFlowModel] = Field(
        default_factory=list,
        description="Flows that validate and filter tool calls before execution.",
    )

    colang_version: str = Field(
        default="1.0",
        description="Colang version used: '1.0' for Colang v1 or '2.x' for Colang v2 syntax.",
    )


class RuntimeActionModel(BaseModel):
    """Metadata for an action registered with this guardrails server.

    Actions are registered from the built-in library and custom action paths
    at server startup. No runtime mutation (registration/deregistration) is
    supported without server restart.
    """

    name: str = Field(description="Fully qualified action name (e.g., 'jailbreak_detection' or 'fetch_from_kb').")

    description: Optional[str] = Field(
        default=None,
        description="Human-readable description of what this action does.",
    )

    source: str = Field(
        default="built-in",
        description="Source of the action: 'built-in' for NeMo Guardrails library or 'custom' for user-defined actions.",
    )

    parameters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="JSON Schema describing the parameters this action accepts. Omitted if not available.",
    )


class RuntimeActionsResponse(BaseModel):
    """List of actions available to a guardrails configuration."""

    config_id: str = Field(description="Identifier of the guardrails configuration.")

    actions: List[RuntimeActionModel] = Field(
        default_factory=list,
        description="Actions registered and available for use in this configuration's flows.",
    )


class RuntimePromptModel(BaseModel):
    """A prompt template used by the LLM for a specific task.

    Prompts are defined per-task (e.g., 'jailbreak_check', 'entity_extraction').
    This schema includes task name and template structure without exposing
    dynamic runtime values or interpolated secrets.
    """

    task: str = Field(description="Task identifier for which this prompt applies (e.g., 'jailbreak_check').")

    template: str = Field(description="Prompt template in Jinja2 or similar format.")


class RuntimeDocumentMetadata(BaseModel):
    """Metadata for a document in the knowledge base."""

    format: str = Field(description="Document format: 'pdf', 'txt', 'markdown', etc.")

    size_bytes: Optional[int] = Field(
        default=None,
        description="Document size in bytes (if available).",
    )


class RuntimeKnowledgeBaseModel(BaseModel):
    """Configuration and state of the knowledge base / RAG system."""

    docs_count: int = Field(
        default=0,
        description="Total number of documents currently loaded in the knowledge base.",
    )

    embedding_model: Optional[str] = Field(
        default=None,
        description="Name of the embedding model used for document vectorization (e.g., 'text-embedding-ada-002').",
    )


class RuntimeConfigResponse(BaseModel):
    """Consolidated configuration state for a guardrails deployment.

    This endpoint returns the parsed configuration for a single config_id,
    including models, rails, flows, and metadata — consolidating data from
    /v1/rails/configs, /v1/models, and other existing endpoints into one
    typed response.

    Does NOT include:
    - Prompts with embedded secrets or business logic
    - actions_server_url with potential credentials
    - Environment variable values
    - API keys, tokens, or authentication credentials
    """

    config_id: str = Field(description="Identifier of the guardrails configuration.")

    colang_version: str = Field(
        default="1.0",
        description="Colang version: '1.0' for Colang v1 or '2.x' for Colang v2.",
    )

    models: List[RuntimeModelModel] = Field(
        default_factory=list,
        description="LLM models configured for this deployment (main model, embedding model, etc).",
    )

    rails: RuntimeRailsResponse = Field(
        description="Input/output/retrieval/dialog/action/tool rail configurations with enabled flows.",
    )

    flows: List[str] = Field(
        default_factory=list,
        description="Names of custom Colang flows defined in this configuration.",
    )

    instructions: List[str] = Field(
        default_factory=list,
        description="System instructions provided to the LLM (natural language guidelines).",
    )

    prompts_count: int = Field(
        default=0,
        description="Number of task-specific prompts configured (e.g., for jailbreak detection, entity extraction).",
    )

    knowledge_base: RuntimeKnowledgeBaseModel = Field(
        default_factory=RuntimeKnowledgeBaseModel,
        description="Knowledge base / RAG configuration and document count.",
    )
