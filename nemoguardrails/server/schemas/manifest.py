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

from typing import Dict, List

from pydantic import BaseModel, Field


class ManifestEndpoint(BaseModel):
    """A single fork-specific HTTP endpoint entry in the manifest catalog."""

    path: str = Field(description="URL path of the endpoint.")
    method: str = Field(description="HTTP method for the endpoint.")
    description: str = Field(description="Behavioral contract describing what the endpoint does.")
    deprecated: bool = Field(
        default=False,
        description="Whether FastAPI marks this route as deprecated (clients should prefer a successor).",
    )


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


class ManifestRailModule(BaseModel):
    """A built-in guardrail library module and the Colang flows it provides in this build.

    Modules excluded at build time by `scripts/filter_guardrails.py` (closed-source
    guardrails, per `scripts/provider-list.yaml`) do not appear here even though they
    exist upstream -- this is the fork/upstream rail delta.
    """

    name: str = Field(description="Guardrail library module name, e.g. 'self_check' or 'jailbreak_detection'.")
    flows: List[str] = Field(
        default_factory=list,
        description="Names of the Colang flows this module defines, usable in rails.input/output/retrieval.flows.",
    )


class ManifestEnabledFlows(BaseModel):
    """Rail flows enabled on a config, grouped by rail type."""

    input: List[str] = Field(default_factory=list, description="Flows from rails.input.flows.")
    output: List[str] = Field(default_factory=list, description="Flows from rails.output.flows.")
    retrieval: List[str] = Field(default_factory=list, description="Flows from rails.retrieval.flows.")


class ManifestConfigSummary(BaseModel):
    """Structural summary of a mounted guardrails config.

    Example::

        {
          "model_engines": ["openai"],
          "enabled_flows": {
            "input": ["self check input"],
            "output": ["self check output"],
            "retrieval": []
          }
        }
    """

    model_engines: List[str] = Field(
        default_factory=list,
        description="Distinct model engine names configured (e.g. 'openai', 'nim').",
    )
    enabled_flows: ManifestEnabledFlows = Field(
        default_factory=ManifestEnabledFlows,
        description="Rail flow names enabled on this config, grouped by input/output/retrieval.",
    )


class TrustyAINemoCRDVersion(BaseModel):
    """Stores a snapshot of the TrustyAI NemoGuardrails CRD."""

    crd: str = Field(
        default="trustyai.opendatahub.io/v1alpha1",
        description="NemoGuardrails CRD API group/version managing this deployment.",
    )
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
    integration: TrustyAINemoCRDVersion
    rails: List[ManifestRailModule] = Field(
        default_factory=list,
        description="Built-in guardrail library modules present in this build and the flows they provide.",
    )
    configs: Dict[str, ManifestConfigSummary] = Field(
        default_factory=dict,
        description=(
            "Guardrails configurations available on this server (same ids as /v1/rails/configs), "
            "each with a structural summary -- not the raw config content."
        ),
    )
