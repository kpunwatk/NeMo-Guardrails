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

"""Schemas for the fork discoverability manifest endpoint (fork-specific)."""

from typing import List

from pydantic import BaseModel, Field


class ManifestEndpoint(BaseModel):
    """A single fork-specific HTTP endpoint entry in the manifest catalog."""

    path: str = Field(description="URL path of the endpoint.")
    method: str = Field(description="HTTP method for the endpoint.")
    description: str = Field(description="Behavioral contract describing what the endpoint does.")


class ManifestIdentity(BaseModel):
    """Fork identity and version information."""

    name: str = Field(description="Name identifying this as the TrustyAI fork of NeMo Guardrails.")
    version: str = Field(description="Installed nemoguardrails package version.")
    upstream_delta_summary: str = Field(description="Summary of how this fork diverges from upstream NeMo Guardrails.")


class ManifestDocumentationPointer(BaseModel):
    """A single documentation reference, labeled by scope."""

    url: str = Field(description="Documentation URL.")
    description: str = Field(
        description="What this documentation covers, including whether it is fork-specific or upstream."
    )


class ManifestIntegration(BaseModel):
    """TrustyAI platform integration points."""

    crd: str = Field(description="NemoGuardrails CRD API group/version managing this deployment.")
    config_schema: dict[str, str] = Field(
        default_factory=dict,
        description="Configuration environment variables and what they control.",
    )


class CapabilityManifest(BaseModel):
    """Top-level fork discoverability manifest document."""

    identity: ManifestIdentity
    endpoints: List[ManifestEndpoint] = Field(
        default_factory=list,
        description="Catalog of fork-specific HTTP endpoints with behavioral contracts.",
    )
    documentation: List[ManifestDocumentationPointer] = Field(default_factory=list)
    integration: ManifestIntegration
