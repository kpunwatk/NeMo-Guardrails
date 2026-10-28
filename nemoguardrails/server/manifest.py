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

Manifest document and config-summary cache state are owned here and attached to
the app at startup via the router lifespan (or `init_manifest()` in tests).
`api.py` only needs `include_router(router)`.
"""

from __future__ import annotations

import hashlib
import inspect
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import APIRouter, FastAPI, Request

from nemoguardrails import RailsConfig, __version__
from nemoguardrails.colang import parse_colang_file
from nemoguardrails.server.schemas.manifest import (
    CapabilityManifest,
    ManifestConfigSummary,
    ManifestDocumentationPointer,
    ManifestEnabledFlows,
    ManifestEndpoint,
    ManifestIdentity,
    ManifestRailModule,
    TrustyAINemoCRDVersion,
)

log = logging.getLogger(__name__)

# Administrative capability-discovery endpoint. Deployment-specific
# authentication and proxy routing are enforced outside the application.
MANIFEST_PATH = "/admin/info"

# Private app attribute names for fork-only state (not declared on GuardrailsApp).
_MANIFEST_ATTR = "_fork_capability_manifest"
_CACHE_ATTR = "_fork_manifest_config_cache"

# `get_manifest` is sync, so FastAPI runs concurrent requests on worker
# threads; the config cache and `document.configs` must be updated under a lock.
_CONFIG_REFRESH_LOCK = threading.Lock()

# Tag applied to TrustyAI HTTP routes that should appear in the manifest
# catalog. Upstream routes (e.g. /v1/checks) and actions-server routes are
# intentionally untagged and therefore excluded from introspection here.
FORK_MANIFEST_TAG = "TrustyAI"

_FORK_NAME = "NeMo-Guardrails (TrustyAI fork)"
_FORK_UPSTREAM_DELTA_SUMMARY = (
    "Forwards X-* request headers to the configured LLM provider (see "
    "integration.request_headers) and serves the fork-only endpoints listed in "
    "`endpoints`. /v1/guardrail/checks is deprecated in favor of upstream /v1/checks."
)
_FORK_DOCUMENTATION = [
    ManifestDocumentationPointer(
        url="https://github.com/trustyai-explainability/NeMo-Guardrails/blob/develop/CLAUDE.md",
        description=(
            "Contributor notes on TrustyAI fork changes. May lag behind "
            "this manifest, which is generated from the running server."
        ),
    ),
    ManifestDocumentationPointer(
        url="https://docs.nvidia.com/nemo/guardrails/_mcp/server",
        description=(
            "Upstream NVIDIA NeMo Guardrails documentation MCP server. Covers "
            "general/upstream behavior only -- it does not include this fork's "
            "/v1/guardrail/checks endpoint, TrustyAI CRD integration, or header "
            "forwarding behavior described in this manifest."
        ),
    ),
]
_FORK_INTEGRATION = TrustyAINemoCRDVersion(
    config_schema={
        "MAIN_MODEL_ENGINE": "LLM engine identifier for the primary model (e.g. openai).",
        "MAIN_MODEL_BASE_URL": "Base URL of the primary model's OpenAI-compatible endpoint.",
    },
    request_headers={
        "Authorization": "Used for cluster/proxy authentication; never forwarded to the LLM provider.",
        "X-Authorization": "Sent to the LLM provider as Authorization when the model has no static API key.",
        "X-*": (
            "Forwarded to the LLM provider, except X-Forwarded-*, X-Real-*, X-Request-Id, and X-Remote-* proxy headers."
        ),
    },
)


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


def _route_description(route) -> str:
    """Extract a one-line behavioral contract from FastAPI route metadata."""
    summary = getattr(route, "summary", None)
    if summary:
        return summary
    doc = inspect.getdoc(getattr(route, "endpoint", None))
    if doc:
        return doc.split("\n", maxsplit=1)[0].strip()
    return getattr(route, "description", None) or ""


def _discover_fork_endpoints(routes) -> list[ManifestEndpoint]:
    """List fork-specific endpoints tagged for manifest discovery."""
    endpoints: list[ManifestEndpoint] = []
    for route in _iter_routes(routes):
        if FORK_MANIFEST_TAG not in (getattr(route, "tags", None) or []):
            continue
        path = getattr(route, "path", None)
        if not path:
            continue
        description = _route_description(route)
        deprecated = bool(getattr(route, "deprecated", False))
        for method in sorted(getattr(route, "methods", None) or []):
            endpoints.append(
                ManifestEndpoint(
                    path=path,
                    method=method,
                    description=description,
                    deprecated=deprecated,
                )
            )
    return endpoints


# Flow discovery below only targets Colang 1.0. `LLMRails.__init__` (the code
# this mirrors) only walks the guardrails library for flow loading when
# `colang_version == "1.0"` -- it has its own `# TODO: decide on the default
# flows for 2.x`. Reporting flow availability for 2.x configs isn't a
# well-defined thing this fork resolves yet, so don't claim it here either.
_RAIL_FLOWS_COLANG_VERSION = "1.0"

_LIBRARY_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "library"))


def _discover_library_rails() -> list:
    """Discover built-in guardrail modules and the Colang flows they provide in this build.

    Mirrors the library-loading walk in `LLMRails.__init__`: parses every `.co`
    file under `nemoguardrails/library` with the same version-aware,
    dialect-detecting `parse_colang_file` used at runtime, rather than
    hand-maintaining a list that can drift from what's actually loadable.

    Modules removed at build time by `scripts/filter_guardrails.py` (per the
    closed-source list in `scripts/provider-list.yaml`) simply aren't on disk
    in this build, so they don't appear here -- that absence is the
    fork/upstream rail delta.
    """
    modules: dict = {}

    for root, dirs, files in os.walk(_LIBRARY_PATH):
        dirs.sort()
        relative_root = os.path.relpath(root, _LIBRARY_PATH)
        if relative_root == os.curdir:
            continue
        module_name = relative_root.split(os.sep)[0]

        for file in sorted(files):
            if not file.endswith(".co"):
                continue
            full_path = os.path.join(root, file)
            try:
                with open(full_path, encoding="utf-8") as f:
                    content = parse_colang_file(file, content=f.read(), version=_RAIL_FLOWS_COLANG_VERSION)
            except Exception as exc:
                log.warning(
                    "Skipping library file %s in manifest: failed to parse (%s)",
                    full_path,
                    type(exc).__name__,
                )
                continue
            if not content:
                continue
            flow_names = {flow["id"] for flow in content.get("flows", []) if flow.get("id")}
            modules.setdefault(module_name, set()).update(flow_names)

    return [ManifestRailModule(name=name, flows=sorted(flows)) for name, flows in sorted(modules.items()) if flows]


def _discover_config_ids(app) -> list:
    """List the guardrails config IDs available on this server.

    Mirrors `/v1/rails/configs` (`api.py`'s `get_rails_configs`) -- config
    discovery itself is an upstream capability, not a fork delta, but is
    aggregated into this single discoverability document for agent
    convenience. Must run after `lifespan()` finalizes `app.single_config_mode`
    / `app.single_config_id`, not before.
    """
    from nemoguardrails.server.api import _has_config_file

    if app.single_config_mode:
        return [app.single_config_id]

    config_root = app.rails_config_path
    # Missing/invalid roots must not take down server startup: the manifest
    # router lifespan calls this during init, and operators may briefly point
    # at a path that is not mounted yet.
    if not os.path.isdir(config_root):
        log.warning(
            "Rails config path %r is missing or not a directory; manifest config catalog will be empty",
            config_root,
        )
        return []

    return sorted(
        f
        for f in os.listdir(config_root)
        if os.path.isdir(os.path.join(config_root, f))
        and f[0] not in (".", "_")
        and _has_config_file(os.path.join(config_root, f))
    )


def _config_path(app, config_id: str) -> str:
    """Resolve a config id to its on-disk path, matching `_get_rails()`'s resolution in api.py."""
    if app.single_config_mode:
        return app.rails_config_path
    return os.path.join(app.rails_config_path, config_id)


def _config_fingerprint(full_path: str) -> str:
    """Cheap change detector for operator in-place config updates.

    Hashes each file's relative path and mtime under the config directory so
    additions, deletions (including of older files), renames, and content
    updates that bump mtime all invalidate the cached summary — not only
    changes that raise the single newest mtime.
    """
    if not os.path.isdir(full_path):
        return "missing"

    entries: list[str] = []
    for root, _dirs, files in os.walk(full_path):
        for name in files:
            path = os.path.join(root, name)
            try:
                rel = os.path.relpath(path, full_path)
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            entries.append(f"{rel}:{mtime}")
    entries.sort()
    digest = hashlib.sha256("\n".join(entries).encode()).hexdigest()
    return f"{len(entries)}:{digest}"


def _summarize_config(full_path: str):
    """Load a guardrails config and extract a safe structural summary.

    Catches any loading/validation error narrowly to this one config: a
    single malformed config directory must not take down manifest generation
    and server startup for the whole deployment.
    """
    try:
        rails_config = RailsConfig.from_path(full_path)
    except Exception as exc:
        # Log exception type only -- traceback / message can include config
        # content (prompts, model parameters) that must not reach logs.
        log.warning(
            "Skipping config at %s in manifest: failed to load (%s)",
            full_path,
            type(exc).__name__,
        )
        return None

    return ManifestConfigSummary(
        model_engines=sorted({model.engine for model in rails_config.models}),
        enabled_flows=ManifestEnabledFlows(
            input=sorted(rails_config.rails.input.flows),
            output=sorted(rails_config.rails.output.flows),
            retrieval=sorted(rails_config.rails.retrieval.flows),
        ),
    )


def _get_config_cache(app) -> dict[str, tuple[str, Optional[ManifestConfigSummary]]]:
    cache = getattr(app, _CACHE_ATTR, None)
    if cache is None:
        cache = {}
        setattr(app, _CACHE_ATTR, cache)
    return cache


def _get_manifest_document(app) -> Optional[CapabilityManifest]:
    return getattr(app, _MANIFEST_ATTR, None)


def _refresh_manifest_config_catalog(app) -> dict[str, ManifestConfigSummary]:
    """Rescan config ids and return summaries, caching per config id + fingerprint.

    Config id discovery mirrors `/v1/rails/configs` on every call; expensive
    `RailsConfig.from_path()` summarization runs only when an id is new or its
    on-disk fingerprint changed (operator config-change rollout). Removed ids
    are evicted from the cache.

    A failed summarization still records the fingerprint (with a None summary)
    so a previously good entry is dropped from the returned catalog and we do
    not keep serving a stale summary for a broken config.
    """
    cache = _get_config_cache(app)
    current_ids = _discover_config_ids(app)
    current_id_set = set(current_ids)

    for stale_id in set(cache) - current_id_set:
        del cache[stale_id]

    for config_id in current_ids:
        full_path = _config_path(app, config_id)
        fingerprint = _config_fingerprint(full_path)
        cached = cache.get(config_id)
        if cached is not None and cached[0] == fingerprint:
            continue
        summary = _summarize_config(full_path)
        cache[config_id] = (fingerprint, summary)

    return {config_id: summary for config_id in current_ids if (summary := cache[config_id][1]) is not None}


def refresh_manifest_configs(app) -> None:
    """Refresh the manifest's config catalog from the current server state.

    Rescans config ids on every call (same as `/v1/rails/configs`) but reuses
    cached summaries when the id and content fingerprint are unchanged. Call
    before serving `/admin/info` so newly mounted or updated configs appear
    without always re-summarizing the full catalog.
    """
    document = _get_manifest_document(app)
    if document is None:
        return
    with _CONFIG_REFRESH_LOCK:
        document.configs = _refresh_manifest_config_catalog(app)


def build_manifest(app) -> CapabilityManifest:
    """Build the capability manifest from static metadata and live route introspection.

    Missing endpoints, unparseable library files, and unloadable configs are
    logged and left out rather than raised; this runs during server startup,
    and a gap in a discovery document must not stop the guardrails server.
    """
    endpoints = _discover_fork_endpoints(app.routes)
    if not endpoints:
        log.warning(
            "No routes tagged with %r were found; the manifest endpoint catalog will be empty.",
            FORK_MANIFEST_TAG,
        )

    return CapabilityManifest(
        identity=ManifestIdentity(
            name=_FORK_NAME,
            version=__version__,
            upstream_delta_summary=_FORK_UPSTREAM_DELTA_SUMMARY,
        ),
        endpoints=endpoints,
        documentation=_FORK_DOCUMENTATION,
        integration=_FORK_INTEGRATION,
        rails=_discover_library_rails(),
        configs=_refresh_manifest_config_catalog(app),
    )


def init_manifest(app) -> CapabilityManifest:
    """Attach fork manifest state to `app` and build the startup catalog.

    Called from the router lifespan after `api.py`'s lifespan has finalized
    `single_config_mode`, and directly from tests that do not run lifespan.
    """
    setattr(app, _CACHE_ATTR, {})
    document = build_manifest(app)
    setattr(app, _MANIFEST_ATTR, document)
    return document


def reset_manifest(app) -> None:
    """Clear fork manifest state on `app` (tests)."""
    setattr(app, _MANIFEST_ATTR, None)
    setattr(app, _CACHE_ATTR, {})


@asynccontextmanager
async def _manifest_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the manifest once at startup; nested inside `api.py`'s lifespan."""
    init_manifest(app)
    yield


router = APIRouter(lifespan=_manifest_lifespan)


@router.get(
    MANIFEST_PATH,
    response_model=CapabilityManifest,
    summary="Fork capability discoverability manifest.",
)
def get_manifest(request: Request):
    """Return the fork's capability manifest.

    Sync so FastAPI runs the config-catalog refresh in a worker thread instead
    of blocking the event loop. Static sections (identity, endpoints, rails,
    integration) are generated once at startup; config ids are rescanned on
    each request and summaries are cached per id + content fingerprint so only
    new or updated configs pay summarization cost.
    """
    refresh_manifest_configs(request.app)
    return _get_manifest_document(request.app)
