---
name: "guardrails-fork-manifest"
description: "Answers questions about this repository's TrustyAI-fork-specific behavior by querying the live capability manifest endpoint instead of guessing from static docs. Use when users ask what's different about this fork, which endpoints are fork-specific, what a fork endpoint's behavioral contract is, or how this fork integrates with the TrustyAI NemoGuardrails CRD. Trigger keywords - fork-specific, capability manifest, ai-plugin.json, upstream delta, TrustyAI integration, NemoGuardrails CRD, what's different in this fork."
license: "Apache-2.0"
---

# Guardrails Fork Manifest

Use this skill for questions about how the **TrustyAI fork** of NeMo Guardrails
differs from upstream, or about fork-specific endpoints and their behavioral
contracts. Answer from a running server's live manifest, not from memory or
static docs, since the manifest is generated from the actual route table at
startup and is the source of truth for what this deployment actually serves.

For general NeMo Guardrails product-usage questions (installation,
`config.yml`, Colang, rail catalog, etc.) that aren't specific to this fork,
use `guardrails-developer-guide` instead.

## Scope

This skill covers **Claude Code only**. It is not published to any platform
skill registry — it ships as a plugin checked into this repository and is
picked up automatically by any skill-discovering client that has the repo
checked out, per `AGENTS.md`'s "Agent Skills" section. No per-developer
install step is required beyond having the repo cloned.

## Finding The Manifest

The manifest is served at `MANIFEST_PATH` from
`nemoguardrails/server/manifest.py` — currently `/.well-known/ai-plugin.json`,
explicitly provisional pending EvalHub team alignment on a platform-wide
Agent Discoverability contract. Check that file if this doesn't resolve.

1. **Local dev server**: if the user is running `nemoguardrails server`
   locally, fetch `http://<host>:<port>/.well-known/ai-plugin.json` directly.
2. **In-cluster deployment (via the TrustyAI operator)**: the URL is not
   hardcoded. Read it from the `NemoGuardrails` CR annotation
   `trustyai.opendatahub.io/nemo-guardrails-manifest-url`, e.g.:

   ```text
   oc get nemoguardrails <cr-name> -n <namespace> \
     -o jsonpath='{.metadata.annotations.trustyai\.opendatahub\.io/nemo-guardrails-manifest-url}'
   ```

   This annotation is a cluster-internal Service URL — it is not reachable
   directly from a developer workstation outside the cluster.

## If The Manifest Is Unreachable

The manifest endpoint has no external ingress by design (NeMo-Guardrails is a
leaf component with no Route/HTTPRoute). If a direct GET fails:

1. Tell the user to port-forward to the Service before retrying, e.g.:
   `oc port-forward svc/<cr-name> <local-port>:<service-port>`, then fetch
   `http://localhost:<local-port>/.well-known/ai-plugin.json`.
2. If port-forwarding isn't possible or the user declines, say so explicitly
   and fall back to `CLAUDE.md`'s "Key fork changes" section as a
   best-effort, potentially stale answer — do not silently fabricate
   fork-specific behavior.

Do not treat an unreachable manifest as a hard failure; degrade gracefully.

## Using The Manifest Content

The manifest (`CapabilityManifest` in
`nemoguardrails/server/schemas/manifest.py`) has four sections:

- `identity` — fork name, installed `nemoguardrails` version, and a
  human-written summary of how this fork diverges from upstream.
- `endpoints` — the catalog of genuinely fork-specific HTTP endpoints (path,
  method, behavioral contract). This list is deliberately narrow: endpoints
  that exist upstream too, or that are served by the separate actions-server
  process, are excluded even if they sound fork-related. Trust this list over
  assumptions about what's "obviously" fork-specific.
- `documentation` — pointers labeled by whether they're fork-specific or
  upstream docs.
- `integration` — the NemoGuardrails CRD API group/version and configuration
  environment variables this deployment responds to.

Quote the manifest's actual field values in the answer (e.g. the exact
endpoint path and behavioral contract text) rather than paraphrasing from
general knowledge of the codebase, so the answer stays correct as the
manifest evolves.

## Related Skills

- Use `guardrails-developer-guide` for upstream/general product-usage
  questions.
- Use `guardrails-developer-create-guardrails` when the user wants to build a
  guardrails configuration rather than ask about this fork's own behavior.
