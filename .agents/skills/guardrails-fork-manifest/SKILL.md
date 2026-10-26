---
name: "guardrails-fork-manifest"
description: "Answers questions about this repository's TrustyAI-fork-specific behavior by querying the live capability manifest endpoint instead of guessing from static docs. Use when users ask what's different about this fork, which endpoints or guardrail flows are fork-specific, what guardrails configs are available, or how this fork integrates with the TrustyAI NemoGuardrails CRD. Trigger keywords - fork-specific, capability manifest, /admin/info endpoint, upstream delta, TrustyAI integration, NemoGuardrails CRD, what's different in this fork."
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
`nemoguardrails/server/manifest.py` — currently `/admin/info`, explicitly
provisional pending EvalHub team alignment on a platform-wide Agent
Discoverability contract. Check that file if this doesn't resolve.

1. **Local dev server**: if the user is running `nemoguardrails server`
   locally, fetch `http://<host>:<port>/admin/info` directly (plain HTTP;
   no kube-rbac-proxy).
2. **In-cluster deployment (via the TrustyAI operator)**: the URL is not
   hardcoded. Read it from the `NemoGuardrails` CR annotation
   `trustyai.opendatahub.io/nemo-guardrails-manifest-url`, e.g.:

   ```text
   oc get nemoguardrails <cr-name> -n <namespace> \
     -o jsonpath='{.metadata.annotations.trustyai\.opendatahub\.io/nemo-guardrails-manifest-url}'
   ```

   This annotation is a cluster-internal **HTTPS** Service URL on the admin
   port (**444** → kube-rbac-proxy-admin on 8444; see
   trustyai-service-operator PR #995). It is not reachable directly from a
   developer workstation outside the cluster. Regular API traffic stays on
   Service port 443; do not use that port for `/admin/info`.

## Handling Failures

Do not treat an unreachable or incomplete manifest as a hard failure; degrade
gracefully and say which step failed.

| Failure | What to do |
| --- | --- |
| No server / connection refused / DNS failure | Tell the user the NeMo Guardrails server is not reachable at the URL you tried. Ask them to start `nemoguardrails server` locally or confirm the in-cluster Service/pod is up. Do not invent fork-specific endpoints. |
| Manifest path 404 | Re-check `MANIFEST_PATH` in `nemoguardrails/server/manifest.py`. If still 404, say the deployment may not include the capability-manifest change yet (needs PR #69 / a build that ships it). |
| HTTP 401 / 403 (caller lacks access) | Explain that `/admin/info` is gated by the operator admin kube-rbac-proxy (`create` on the NeMoGuardrails CR). Ask the user to use a token with that permission, or to port-forward with `oc whoami -t` as below. Do not retry endlessly. |
| TLS / certificate errors on the admin URL | Expected for cluster-internal serving certs when port-forwarding; retry with TLS verify disabled (`curl -k`). If that still fails, report the TLS error verbatim. |
| Annotation missing on the CR | Say the operator may not yet publish `trustyai.opendatahub.io/nemo-guardrails-manifest-url` (see trustyai-service-operator PR #1007). Fall back to constructing `https://<service>.<ns>.svc:444/admin/info` only if the user confirms the admin Service port, or use port-forward guidance. |
| Port-forward not possible / user declines | Fall back to `CLAUDE.md`'s "Key fork changes" as a best-effort, potentially stale answer — and say so explicitly. Never silently fabricate fork-specific behavior. |
| Server starts but config catalog is empty | Report that `configs` is empty; it may mean `rails_config_path` is missing/unmounted or no valid `config.yml` dirs were found. Still use `identity` / `endpoints` / `rails` if present. |

## If The Manifest Is Unreachable

The manifest endpoint has no external ingress by design (NeMo-Guardrails is a
leaf component with no Route/HTTPRoute). If a direct GET fails, prefer the
table above. For in-cluster access from a workstation, the usual recovery is:

```text
oc port-forward svc/<cr-name> 4444:444 -n <namespace>
curl -k -H "Authorization: Bearer $(oc whoami -t)" \
  https://localhost:4444/admin/info
```

## Using The Manifest Content

Do **not** hardcode the manifest field list in your reasoning. Before
interpreting a response:

1. Read the live schema in
   `nemoguardrails/server/schemas/manifest.py` (`CapabilityManifest` and nested
   models) for the current section names, field meanings, and descriptions.
2. Fetch the live JSON from `/admin/info`.
3. Quote the manifest's actual field values in the answer (e.g. the exact
   endpoint path and behavioral contract text). Prefer the live payload over
   static docs or memory so answers stay correct as the schema evolves.

If the schema file and the live payload disagree (older deployment), trust the
live payload for facts about that deployment, and note the version skew.

## Related Skills

- Use `guardrails-developer-guide` for upstream/general product-usage
  questions.
- Use `guardrails-developer-create-guardrails` when the user wants to build a
  guardrails configuration rather than ask about this fork's own behavior.
