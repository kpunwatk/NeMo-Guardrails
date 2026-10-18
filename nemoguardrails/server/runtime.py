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

"""Fork-specific /v1/runtime/* discovery endpoints.

Extracted from api.py to reduce the conflict surface during upstream syncs.
These stay under /v1/ so in-cluster traffic uses the regular kube-rbac-proxy
path (Service port 443), not the admin path (port 444).
"""

from typing import Optional

from fastapi import APIRouter, HTTPException

from nemoguardrails.server.api import _get_rails, app
from nemoguardrails.server.runtime_helpers import (
    build_runtime_actions_response,
    build_runtime_config_response,
    build_runtime_rails_response,
)
from nemoguardrails.server.schemas.runtime import (
    RuntimeActionsResponse,
    RuntimeConfigResponse,
    RuntimeRailsResponse,
)

router = APIRouter()


def _runtime_config_not_found(exc: ValueError) -> bool:
    """Return True when a ValueError from config load means the config_id is missing."""
    message = str(exc)
    return any(
        fragment in message
        for fragment in (
            "No valid rails configuration found",
            "Invalid config path",
            "Invalid configuration ids",
        )
    )


def _resolve_config_id(config_id: Optional[str]) -> str:
    """Resolve config_id for single-config vs multi-config modes.

    Raises:
        HTTPException 400: config_id is missing in multi-config mode.
        HTTPException 404: config_id does not match the single-config id.
    """
    if app.single_config_mode:
        if config_id is None:
            return app.single_config_id
        if config_id != app.single_config_id:
            raise HTTPException(
                status_code=404,
                detail=f"No guardrail configuration with id '{config_id}' found",
            )
        return config_id

    if config_id is None:
        raise HTTPException(
            status_code=400,
            detail="Missing required query parameter: config_id",
        )
    return config_id


async def _load_rails_or_http_error(config_id: str):
    """Load LLMRails for config_id, mapping load failures to HTTP errors."""
    try:
        return await _get_rails([config_id])
    except ValueError as exc:
        if _runtime_config_not_found(exc):
            raise HTTPException(
                status_code=404,
                detail=f"No guardrail configuration with id '{config_id}' found",
            ) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/v1/runtime/rails",
    response_model=RuntimeRailsResponse,
    summary="Get rails configuration and enabled flows.",
)
async def get_runtime_rails(config_id: Optional[str] = None):
    """Return the parsed rails configuration for a guardrails deployment.

    Args:
        config_id: Configuration ID to retrieve. Required in multi-config mode;
                   optional in single-config mode (uses default if omitted).

    Returns:
        RuntimeRailsResponse with all rail types and their enabled flows.

    Raises:
        HTTPException 400: config_id is missing in multi-config mode.
        HTTPException 404: config_id does not exist.
    """
    config_id = _resolve_config_id(config_id)
    rails = await _load_rails_or_http_error(config_id)
    return build_runtime_rails_response(config_id, rails.config)


@router.get(
    "/v1/runtime/actions",
    response_model=RuntimeActionsResponse,
    summary="Get registered actions for a configuration.",
)
async def get_runtime_actions(config_id: Optional[str] = None):
    """Return the list of actions registered for a guardrails deployment.

    Args:
        config_id: Configuration ID to retrieve. Required in multi-config mode;
                   optional in single-config mode (uses default if omitted).

    Returns:
        RuntimeActionsResponse with registered actions and their metadata.

    Raises:
        HTTPException 400: config_id is missing in multi-config mode.
        HTTPException 404: config_id does not exist.
    """
    config_id = _resolve_config_id(config_id)
    rails = await _load_rails_or_http_error(config_id)
    return build_runtime_actions_response(config_id, rails)


@router.get(
    "/v1/runtime/config",
    response_model=RuntimeConfigResponse,
    summary="Get consolidated configuration state.",
)
async def get_runtime_config(config_id: Optional[str] = None):
    """Return the complete parsed configuration for a guardrails deployment.

    This endpoint consolidates configuration data from models, rails, flows,
    instructions, and knowledge base into a single typed response.

    Args:
        config_id: Configuration ID to retrieve. Required in multi-config mode;
                   optional in single-config mode (uses default if omitted).

    Returns:
        RuntimeConfigResponse with comprehensive configuration state.

    Raises:
        HTTPException 400: config_id is missing in multi-config mode.
        HTTPException 404: config_id does not exist.
    """
    config_id = _resolve_config_id(config_id)
    rails = await _load_rails_or_http_error(config_id)
    return build_runtime_config_response(config_id, rails.config)
