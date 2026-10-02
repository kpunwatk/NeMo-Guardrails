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

"""Helper functions for constructing runtime state API responses.

These helpers convert RailsConfig instances into typed response models
defined in nemoguardrails.server.schemas.runtime.
"""

from typing import List, Optional

from nemoguardrails import LLMRails
from nemoguardrails.rails.llm.config import RailsConfig
from nemoguardrails.server.schemas.runtime import (
    RuntimeActionModel,
    RuntimeActionsResponse,
    RuntimeConfigResponse,
    RuntimeKnowledgeBaseModel,
    RuntimeModelModel,
    RuntimeRailFlowModel,
    RuntimeRailsResponse,
)


def _build_runtime_rail_flows(flows: List[str], rail_type: str) -> List[RuntimeRailFlowModel]:
    """Convert a list of flow names to RuntimeRailFlowModel instances."""
    return [RuntimeRailFlowModel(name=flow, type=rail_type) for flow in flows]


def build_runtime_rails_response(config_id: str, config: RailsConfig) -> RuntimeRailsResponse:
    """Build RuntimeRailsResponse from a RailsConfig instance.

    Args:
        config_id: Configuration identifier
        config: RailsConfig instance loaded from YAML

    Returns:
        RuntimeRailsResponse with all rail types and their flows
    """
    return RuntimeRailsResponse(
        config_id=config_id,
        input_rails=_build_runtime_rail_flows(config.rails.input.flows, "input"),
        output_rails=_build_runtime_rail_flows(config.rails.output.flows, "output"),
        retrieval_rails=_build_runtime_rail_flows(config.rails.retrieval.flows, "retrieval"),
        dialog_rails=[],  # Dialog rails use RailsConfigData, not flows list
        action_rails=_build_runtime_rail_flows(config.rails.actions.instant_actions or [], "actions"),
        tool_input_rails=_build_runtime_rail_flows(config.rails.tool_input.flows, "tool_input"),
        tool_output_rails=_build_runtime_rail_flows(config.rails.tool_output.flows, "tool_output"),
        colang_version=config.colang_version,
    )


def build_runtime_models_list(config: RailsConfig) -> List[RuntimeModelModel]:
    """Build list of RuntimeModelModel from RailsConfig models.

    Args:
        config: RailsConfig instance

    Returns:
        List of RuntimeModelModel (secrets filtered)
    """
    runtime_models = []
    for model in config.models:
        # Exclude models with api_key_env_var set (indicates a sensitive integration)
        runtime_models.append(
            RuntimeModelModel(
                type=model.type,
                engine=model.engine,
                model=model.model,
                mode=model.mode,
            )
        )
    return runtime_models


def build_runtime_knowledge_base(config: RailsConfig) -> RuntimeKnowledgeBaseModel:
    """Build RuntimeKnowledgeBaseModel from RailsConfig knowledge base config.

    Args:
        config: RailsConfig instance

    Returns:
        RuntimeKnowledgeBaseModel with doc count and embedding info
    """
    docs_count = len(config.docs) if config.docs else 0
    embedding_model = None

    # Try to extract embedding model name from knowledge_base config
    if hasattr(config.knowledge_base, 'embedding_model'):
        embedding_model = config.knowledge_base.embedding_model

    return RuntimeKnowledgeBaseModel(
        docs_count=docs_count,
        embedding_model=embedding_model,
    )


def build_runtime_config_response(config_id: str, config: RailsConfig) -> RuntimeConfigResponse:
    """Build RuntimeConfigResponse from a RailsConfig instance.

    Args:
        config_id: Configuration identifier
        config: RailsConfig instance loaded from YAML

    Returns:
        RuntimeConfigResponse with comprehensive configuration state
    """
    rails_response = build_runtime_rails_response(config_id, config)

    # Extract flow names (not types)
    flow_names = [flow.get("id", str(i)) if isinstance(flow, dict) else str(flow) for i, flow in enumerate(config.flows)]

    # Extract instruction content
    instruction_content = []
    if config.instructions:
        for instruction in config.instructions:
            instruction_content.append(instruction.content)

    prompts_count = len(config.prompts) if config.prompts else 0

    return RuntimeConfigResponse(
        config_id=config_id,
        colang_version=config.colang_version,
        models=build_runtime_models_list(config),
        rails=rails_response,
        flows=flow_names,
        instructions=instruction_content,
        prompts_count=prompts_count,
        knowledge_base=build_runtime_knowledge_base(config),
    )


def build_runtime_actions_response(config_id: str, rails: LLMRails) -> RuntimeActionsResponse:
    """Build RuntimeActionsResponse from the config's live ActionDispatcher.

    Args:
        config_id: Configuration identifier
        rails: Loaded LLMRails instance for this config

    Returns:
        RuntimeActionsResponse with registered action names.
        description/parameters are omitted (null) until richer metadata is in scope.
    """
    names = rails.runtime.action_dispatcher.get_registered_actions()
    return RuntimeActionsResponse(
        config_id=config_id,
        actions=[
            RuntimeActionModel(name=name, description=None, source="unknown", parameters=None)
            for name in sorted(names)
        ],
    )
