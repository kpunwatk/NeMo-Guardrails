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

"""Tests for the fork discoverability capability manifest endpoint."""

import os
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytest.importorskip("openai", reason="openai is required for server tests")
from fastapi.testclient import TestClient

from nemoguardrails import utils
from nemoguardrails.server import api
from nemoguardrails.server import manifest as manifest_module
from nemoguardrails.server.manifest import MANIFEST_PATH, build_manifest, init_manifest, reset_manifest

client = TestClient(api.app)


@pytest.fixture(scope="function", autouse=True)
def setup_manifest():
    """Generate the manifest the same way the manifest router lifespan does at startup.

    TestClient does not run lifespan events unless used as a context manager,
    matching the convention already used by other server tests in this repo
    (state is set via `init_manifest` rather than relying on startup).
    """
    init_manifest(api.app)
    yield
    reset_manifest(api.app)


def test_manifest_returns_200_with_valid_document():
    """GET /admin/info returns the fork capability manifest."""
    # Outside /v1/* so the operator admin proxy (not the regular /v1 proxy) gates it.
    assert MANIFEST_PATH == "/admin/info"

    response = client.get(MANIFEST_PATH)

    assert response.status_code == 200
    identity = response.json()["identity"]
    assert identity["name"] == "NeMo-Guardrails (TrustyAI fork)"
    assert identity["version"]
    assert identity["upstream_delta_summary"]


def test_manifest_lists_guardrail_checks_with_behavioral_contract():
    """The endpoint catalog includes /v1/guardrail/checks with method, contract, and deprecation."""
    response = client.get(MANIFEST_PATH)

    endpoints = {e["path"]: e for e in response.json()["endpoints"]}
    assert "/v1/guardrail/checks" in endpoints
    assert endpoints["/v1/guardrail/checks"]["method"] == "POST"
    assert endpoints["/v1/guardrail/checks"]["description"]
    assert endpoints["/v1/guardrail/checks"]["deprecated"] is True


def test_manifest_excludes_upstream_and_actions_server_endpoints():
    """Endpoints that are upstream-inherited or served by a different process are not listed.

    /v1/checks is an upstream endpoint, not a fork delta. /v1/actions/list and
    /v1/actions/run are served by the separate actions_server process and are
    not part of this app's route table.
    """
    response = client.get(MANIFEST_PATH)

    paths = {e["path"] for e in response.json()["endpoints"]}
    assert "/v1/checks" not in paths
    assert "/v1/actions/list" not in paths
    assert "/v1/actions/run" not in paths


def test_manifest_documentation_pointers_distinguish_fork_from_upstream():
    """Documentation pointers are present and label upstream vs. fork-specific scope."""
    response = client.get(MANIFEST_PATH)

    docs = response.json()["documentation"]
    assert any("CLAUDE.md" in d["url"] for d in docs)
    upstream_entry = next(d for d in docs if urlparse(d["url"]).hostname == "docs.nvidia.com")
    assert "upstream" in upstream_entry["description"].lower()


def test_manifest_integration_metadata_present():
    """TrustyAI integration points (CRD, config schema) are populated."""
    response = client.get(MANIFEST_PATH)

    integration = response.json()["integration"]
    assert integration["crd"] == "trustyai.opendatahub.io/v1alpha1"
    assert "MAIN_MODEL_ENGINE" in integration["config_schema"]
    assert "MAIN_MODEL_BASE_URL" in integration["config_schema"]


def test_manifest_does_not_leak_env_var_values(monkeypatch):
    """The manifest describes config schema names, never actual configured values."""
    monkeypatch.setenv("MAIN_MODEL_BASE_URL", "http://internal-secret-host:1234")
    init_manifest(api.app)

    response = client.get(MANIFEST_PATH)

    assert "internal-secret-host" not in response.text


def test_manifest_lists_library_rail_modules_and_flows():
    """The rails catalog lists built-in guardrail modules with their Colang flow names.

    This is the fork/upstream rail delta: modules removed at build time by
    `scripts/filter_guardrails.py` won't appear in a filtered image, but in
    this dev checkout every library module is present on disk.
    """
    response = client.get(MANIFEST_PATH)

    rails = {r["name"]: r["flows"] for r in response.json()["rails"]}
    assert rails["self_check"] == ["self check facts", "self check input", "self check output"]
    assert rails["jailbreak_detection"] == ["jailbreak detection heuristics", "jailbreak detection model"]


def test_manifest_lists_available_configs_with_structural_summary(monkeypatch):
    """The config catalog covers the same ids as /v1/rails/configs, each with a safe summary.

    Config discovery itself is an upstream capability (dates to the 0.1.0
    release, predates this fork), not a fork delta -- it's aggregated here,
    with a structural summary per config, purely for agent convenience per a
    reviewer request on this PR.

    Explicitly pins rails_config_path/single_config_mode rather than relying
    on api.app's defaults: it's a module-level singleton shared across test
    files, and other server tests mutate it without resetting.
    """
    monkeypatch.setattr(api.app, "single_config_mode", False)
    monkeypatch.setattr(api.app, "rails_config_path", utils.get_examples_data_path("bots"))
    init_manifest(api.app)

    response = client.get(MANIFEST_PATH)
    configs_response = client.get("/v1/rails/configs")

    configs = response.json()["configs"]
    assert set(configs.keys()) == {c["id"] for c in configs_response.json()}
    assert configs["abc"]["model_engines"] == ["openai"]
    assert configs["abc"]["enabled_flows"] == {
        "input": ["self check input"],
        "output": ["self check output"],
        "retrieval": [],
    }


def test_manifest_does_not_leak_raw_config_content(monkeypatch):
    """The config summary excludes prompts/instructions -- config-author business logic."""
    monkeypatch.setattr(api.app, "single_config_mode", False)
    monkeypatch.setattr(api.app, "rails_config_path", utils.get_examples_data_path("bots"))
    init_manifest(api.app)

    response = client.get(MANIFEST_PATH)

    assert "ABC Company" not in response.text
    assert "paid vacation" not in response.text


def test_manifest_configs_reflect_single_config_mode(monkeypatch):
    """In single-config mode, the manifest summarizes the one config directly, not a directory scan."""
    single_config_path = utils.get_examples_data_path("bots/hello_world")
    monkeypatch.setattr(api.app, "single_config_mode", True)
    monkeypatch.setattr(api.app, "single_config_id", "hello_world")
    monkeypatch.setattr(api.app, "rails_config_path", single_config_path)
    init_manifest(api.app)

    response = client.get(MANIFEST_PATH)

    configs = response.json()["configs"]
    assert set(configs.keys()) == {"hello_world"}
    assert configs["hello_world"]["model_engines"] == ["openai"]


def test_manifest_configs_refresh_after_new_config_added(tmp_path, monkeypatch):
    """Configs added after startup appear in /admin/info without rebuilding the manifest."""
    bots_path = Path(utils.get_examples_data_path("bots"))
    configs_root = tmp_path / "configs"
    shutil.copytree(bots_path / "abc", configs_root / "abc")

    monkeypatch.setattr(api.app, "single_config_mode", False)
    monkeypatch.setattr(api.app, "rails_config_path", str(configs_root))
    init_manifest(api.app)

    initial_response = client.get(MANIFEST_PATH)
    assert set(initial_response.json()["configs"].keys()) == {"abc"}

    shutil.copytree(bots_path / "hello_world", configs_root / "hello_world")

    refreshed_response = client.get(MANIFEST_PATH)
    assert set(refreshed_response.json()["configs"].keys()) == {"abc", "hello_world"}


def test_build_manifest_fails_when_no_fork_endpoints(monkeypatch):
    """Startup fails if no routes carry the TrustyAI manifest tag."""
    monkeypatch.setattr(manifest_module, "_discover_fork_endpoints", lambda routes: [])

    with pytest.raises(RuntimeError, match="TrustyAI"):
        build_manifest(api.app)


def test_refresh_manifest_configs_only_summarizes_unseen_config_ids(tmp_path, monkeypatch):
    """Rescanning config ids reuses cached summaries; only new ids are summarized."""
    bots_path = Path(utils.get_examples_data_path("bots"))
    configs_root = tmp_path / "configs"
    shutil.copytree(bots_path / "abc", configs_root / "abc")

    summarize_calls: list[str] = []
    original_summarize = manifest_module._summarize_config

    def counting_summarize(full_path: str):
        summarize_calls.append(full_path)
        return original_summarize(full_path)

    monkeypatch.setattr(manifest_module, "_summarize_config", counting_summarize)
    monkeypatch.setattr(api.app, "single_config_mode", False)
    monkeypatch.setattr(api.app, "rails_config_path", str(configs_root))
    init_manifest(api.app)

    assert len(summarize_calls) == 1

    summarize_calls.clear()
    client.get(MANIFEST_PATH)
    assert summarize_calls == []

    shutil.copytree(bots_path / "hello_world", configs_root / "hello_world")

    client.get(MANIFEST_PATH)
    assert len(summarize_calls) == 1
    document = manifest_module._get_manifest_document(api.app)
    assert document is not None
    assert set(document.configs.keys()) == {"abc", "hello_world"}


def test_refresh_manifest_configs_resummarizes_when_config_content_changes(tmp_path, monkeypatch):
    """In-place config updates (same id, new content) invalidate the cached summary."""
    bots_path = Path(utils.get_examples_data_path("bots"))
    configs_root = tmp_path / "configs"
    shutil.copytree(bots_path / "abc", configs_root / "abc")

    summarize_calls: list[str] = []
    original_summarize = manifest_module._summarize_config

    def counting_summarize(full_path: str):
        summarize_calls.append(full_path)
        return original_summarize(full_path)

    monkeypatch.setattr(manifest_module, "_summarize_config", counting_summarize)
    monkeypatch.setattr(api.app, "single_config_mode", False)
    monkeypatch.setattr(api.app, "rails_config_path", str(configs_root))
    init_manifest(api.app)
    assert len(summarize_calls) == 1

    summarize_calls.clear()
    config_yml = configs_root / "abc" / "config.yml"
    # Bump mtime after a short delay so the fingerprint changes on all filesystems.
    time.sleep(0.05)
    config_yml.write_text(config_yml.read_text() + "\n# operator rollout update\n")

    response = client.get(MANIFEST_PATH)
    assert len(summarize_calls) == 1
    assert response.json()["configs"]["abc"]["enabled_flows"]["input"] == ["self check input"]


def test_refresh_manifest_configs_drops_summary_when_config_becomes_unloadable(tmp_path, monkeypatch):
    """A config that later fails to load must not keep serving its old summary."""
    bots_path = Path(utils.get_examples_data_path("bots"))
    configs_root = tmp_path / "configs"
    shutil.copytree(bots_path / "abc", configs_root / "abc")

    monkeypatch.setattr(api.app, "single_config_mode", False)
    monkeypatch.setattr(api.app, "rails_config_path", str(configs_root))
    init_manifest(api.app)

    initial = client.get(MANIFEST_PATH)
    assert "abc" in initial.json()["configs"]

    # Corrupt the config and bump mtime so the fingerprint changes.
    time.sleep(0.05)
    (configs_root / "abc" / "config.yml").write_text("models: [::invalid::yaml")

    refreshed = client.get(MANIFEST_PATH)
    assert "abc" not in refreshed.json()["configs"]

    # Same broken fingerprint should not be re-summarized every request.
    summarize_calls: list[str] = []
    original_summarize = manifest_module._summarize_config

    def counting_summarize(full_path: str):
        summarize_calls.append(full_path)
        return original_summarize(full_path)

    monkeypatch.setattr(manifest_module, "_summarize_config", counting_summarize)
    client.get(MANIFEST_PATH)
    assert summarize_calls == []


def test_summarize_config_does_not_log_exception_details(tmp_path, caplog):
    """Failed config loads log exception type only, not traceback or message body."""
    bad_config = tmp_path / "broken"
    bad_config.mkdir()
    (bad_config / "config.yml").write_text("models: [::invalid::yaml")

    with caplog.at_level("WARNING", logger="nemoguardrails.server.manifest"):
        assert manifest_module._summarize_config(str(bad_config)) is None

    assert "failed to load" in caplog.text
    assert "Traceback" not in caplog.text
    assert "exc_info" not in caplog.text


def test_manifest_is_wired_through_app_lifespan():
    """Manifest is built by router lifespan, not only by the test fixture."""
    reset_manifest(api.app)
    with TestClient(api.app) as lifespan_client:
        response = lifespan_client.get(MANIFEST_PATH)
        assert response.status_code == 200
        assert response.json()["endpoints"]


def test_admin_route_exposes_only_manifest():
    """Only /admin/info is mounted under /admin (admin-proxy surface)."""
    admin_paths = {
        path
        for route in manifest_module._iter_routes(api.app.routes)
        if (path := getattr(route, "path", None)) and path.startswith("/admin")
    }
    assert admin_paths == {MANIFEST_PATH}


def test_lifespan_tolerates_missing_rails_config_path(monkeypatch):
    """Server startup must not crash when rails_config_path does not exist.

    The manifest router lifespan builds the config catalog at startup; a
    missing mount must yield an empty catalog rather than FileNotFoundError.
    """
    monkeypatch.setattr(api.app, "rails_config_path", "/nonexistent/path")
    monkeypatch.setattr(api.app, "single_config_mode", False)

    with TestClient(api.app) as live_client:
        assert live_client.get("/v1/rails/configs").status_code == 200
        manifest = live_client.get(MANIFEST_PATH)
        assert manifest.status_code == 200
        assert manifest.json()["configs"] == {}


def test_config_fingerprint_changes_when_older_file_deleted(tmp_path):
    """Deleting any file in a config dir must change the fingerprint.

    Newest-mtime-only fingerprints miss deletions of older files (e.g. a
    ConfigMap key removed on remount while other files keep a later mtime).
    """
    config_dir = tmp_path / "abc"
    shutil.copytree(utils.get_examples_data_path("bots/abc"), config_dir)
    files = sorted(p for p in config_dir.rglob("*") if p.is_file())
    assert len(files) >= 2

    fp_before = manifest_module._config_fingerprint(str(config_dir))
    oldest = min(files, key=lambda p: p.stat().st_mtime)
    os.utime(oldest, (1, 1))
    oldest.unlink()

    assert fp_before != manifest_module._config_fingerprint(str(config_dir))
