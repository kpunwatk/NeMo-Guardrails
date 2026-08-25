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

"""Fork discoverability capability manifest endpoint.

Extracted as its own module, following the pattern established by
`nemoguardrails/server/checks.py`, to keep fork-only surface area out of
api.py and reduce the conflict surface during upstream syncs. This module is
fork-only and has no upstream equivalent.
"""

import logging
import os

import yaml
from fastapi import APIRouter, Request

from nemoguardrails import __version__
from nemoguardrails.server.schemas.manifest import (
    CapabilityManifest,
    ManifestDocumentationPointer,
    ManifestEndpoint,
    ManifestIdentity,
    ManifestIntegration,
)

log = logging.getLogger(__name__)

router = APIRouter()

# NOTE: final path is pending alignment with the EvalHub team on a
# platform-wide Agent Discoverability contract (RHAI-517 AC). Treat as
# provisional until that alignment happens.
MANIFEST_PATH = "/.well-known/ai-plugin.json"

_METADATA_FILE = os.path.join(os.path.dirname(__file__), "fork_metadata.yaml")

# Fork-specific endpoints surfaced in the manifest catalog, keyed by path.
#
# Deliberately excludes:
# - /v1/checks: an upstream-inherited endpoint, not a fork delta.
# - /v1/actions/list, /v1/actions/run: served by the separate actions_server
#   process (nemoguardrails/actions_server/actions_server.py) and not part of
#   this app's route table, so they can't be introspected here.
_FORK_ENDPOINT_CONTRACTS = {
    "/v1/guardrail/checks": (
        "Evaluates messages against configured input/output rails without generating an LLM response."
    ),
}


def _load_static_metadata() -> dict:
    with open(_METADATA_FILE) as f:
        return yaml.safe_load(f)


def _iter_routes(routes):
    """Recursively flatten a FastAPI/Starlette route tree.

    Newer FastAPI versions don't eagerly flatten `include_router()` calls into
    `app.routes`; included routers show up as opaque wrapper objects (e.g.
    `_IncludedRouter`, exposing the original router via `.original_router`)
    rather than plain `APIRoute` entries. Mounts also nest via `.routes`. Walk
    both shapes generically instead of depending on FastAPI-internal class
    names, which aren't stable across versions.
    """
    for route in routes:
        nested = getattr(route, "routes", None)
        if nested is None:
            original_router = getattr(route, "original_router", None)
            nested = getattr(original_router, "routes", None)
        if nested:
            yield from _iter_routes(nested)
        else:
            yield route


def build_manifest(app) -> CapabilityManifest:
    """Build the capability manifest from static metadata and live route introspection.

    Raises if static metadata is missing/invalid so that startup fails outright
    rather than serving a stale or broken manifest.
    """
    metadata = _load_static_metadata()

    endpoints = [
        ManifestEndpoint(path=route.path, method=method, description=_FORK_ENDPOINT_CONTRACTS[route.path])
        for route in _iter_routes(app.routes)
        if getattr(route, "path", None) in _FORK_ENDPOINT_CONTRACTS
        for method in sorted(getattr(route, "methods", None) or [])
    ]

    return CapabilityManifest(
        identity=ManifestIdentity(
            name=metadata["name"],
            version=__version__,
            upstream_delta_summary=metadata["upstream_delta_summary"].strip(),
        ),
        endpoints=endpoints,
        documentation=[ManifestDocumentationPointer(**entry) for entry in metadata["documentation"]],
        integration=ManifestIntegration(**metadata["integration"]),
    )


@router.get(
    MANIFEST_PATH,
    response_model=CapabilityManifest,
    summary="Fork capability discoverability manifest.",
)
async def get_manifest(request: Request):
    """Return the fork's capability manifest, generated once at server startup."""
    return request.app.manifest
