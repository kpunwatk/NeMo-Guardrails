# Runtime State API Schema Design (RHAI-520, Phase 1)

## Overview

This document outlines the schema design for the `/v1/runtime/*` endpoints that expose parsed configuration state from NeMo-Guardrails deployments. These schemas are defined in `runtime.py` and used by the three runtime state endpoints planned for RHAI-521.

## Key Design Principles

### 1. Configuration-Driven, Not Runtime-Mutable State

**Finding from Gap Analysis**: NeMo-Guardrails has no runtime-only state distinct from parsed configuration. There are no:
- Rail enable/disable toggles
- Action registration timestamps
- Last-reload times
- Health/integration status

Therefore, `/v1/runtime/*` endpoints expose **parsed configuration state**, not "runtime-only" state. All data is read directly from `RailsConfig` and `LLMRails` at request time.

### 2. Secrets Filtering: Hybrid Allowlist + Denylist

**Approach**: Use Pydantic field exclusion (explicit allowlist) combined with environment variable pattern filtering.

#### What is Safe (Included in Responses)

- **Rail metadata**: Flow names, rail types (input, output, retrieval, dialog, etc.)
- **Model metadata**: Model type, engine, model name, mode (chat vs. text)
- **Colang version**: Language version in use
- **Flow names**: User-defined and built-in Colang flow identifiers
- **Action names**: Action identifiers and source (built-in vs. custom)
- **Counts**: Document counts, prompt counts, flow counts

#### What is Unsafe (Excluded)

- **API Keys**: `OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.
- **Environment variables**: Any field that interpolates `$ENV_VAR` syntax
- **Credentials**: `api_key_env_var` field on Model, database connection strings
- **URLs with auth**: `actions_server_url`, embedding provider endpoints that embed secrets
- **Sensitive prompts**: System instructions or prompt templates that encode business logic or PII handling rules
- **Parameters dicts**: The `parameters` dict on Model may contain `base_url` with internal network details

#### Implementation: Pydantic Field Exclusion

Each runtime schema model explicitly includes safe fields and omits unsafe ones:

```python
class RuntimeModelModel(BaseModel):
    # Safe: model identifier and provider info
    type: str
    engine: str
    model: str
    mode: str
    
    # NOT included (even though they exist in rails/llm/config.Model):
    # - api_key_env_var
    # - parameters (contains potential credentials/internal URLs)
```

### 3. Multi-Config Support

**Design Decision**: Endpoints return state for a single `config_id`. 

- In single-config mode: The endpoint returns the single config's state
- In multi-config mode: Callers must specify `config_id` query parameter (e.g., `GET /v1/runtime/rails?config_id=config_a`)
- If no config found: Return HTTP 404 with message "No guardrail configuration with id '{config_id}' found"

**Rationale**: 
- Prevents ambiguous responses when multiple configs are loaded
- Aligns with existing `/v1/rails/configs` endpoint behavior
- Allows agents to query specific configs in multi-config deployments

### 4. No OpenAPI Spec Filtering

**Design Decision**: Field descriptions and response schemas are comprehensive and safe to expose in OpenAPI spec.

- All descriptions avoid exposing sensitive information
- No special filtering needed for OpenAPI spec generation (Pydantic Field descriptions are safe)
- Agents can consume OpenAPI spec directly to discover endpoint contract

## Schema Models

### 1. RuntimeRailsResponse

**Purpose**: Expose the rail configuration for a single config_id.

**Structure**:
```
RuntimeRailsResponse
├── config_id: str
├── input_rails: List[RuntimeRailFlowModel]
├── output_rails: List[RuntimeRailFlowModel]
├── retrieval_rails: List[RuntimeRailFlowModel]
├── dialog_rails: List[RuntimeRailFlowModel]
├── action_rails: List[RuntimeRailFlowModel]
├── tool_input_rails: List[RuntimeRailFlowModel]
├── tool_output_rails: List[RuntimeRailFlowModel]
└── colang_version: str
```

**Source Data**:
- Derived from `RailsConfig.rails` (input, output, retrieval, dialog, actions, tool_input, tool_output)
- Each rail type contains `flows: List[str]` → converted to `List[RuntimeRailFlowModel]`

**Endpoint**: `GET /v1/runtime/rails?config_id=<config_id>`

---

### 2. RuntimeActionsResponse

**Purpose**: List all actions (built-in and custom) registered for a config.

**Structure**:
```
RuntimeActionsResponse
├── config_id: str
└── actions: List[RuntimeActionModel]
    └── RuntimeActionModel
        ├── name: str
        ├── description: Optional[str]
        ├── source: str (built-in | custom)
        └── parameters: Optional[Dict[str, Any]]
```

**Source Data**:
- Calls `ActionDispatcher.get_registered_actions()` for the config
- Each action can be marked as "built-in" (from library) or "custom" (user-defined)
- Parameters schema extracted via introspection (if available)

**Endpoint**: `GET /v1/runtime/actions?config_id=<config_id>`

**Note**: Currently, `/v1/actions/list` exists on the separate `actions_server` FastAPI app. RuntimeActionsResponse is designed for integration into the main server API.

---

### 3. RuntimeConfigResponse

**Purpose**: Consolidated view of configuration state for a single config_id.

**Structure**:
```
RuntimeConfigResponse
├── config_id: str
├── colang_version: str
├── models: List[RuntimeModelModel]
├── rails: RuntimeRailsResponse (nested)
├── flows: List[str]
├── instructions: List[str]
├── prompts_count: int
└── knowledge_base: RuntimeKnowledgeBaseModel
    ├── docs_count: int
    └── embedding_model: Optional[str]
```

**Source Data**:
- `config_id` from request parameter
- `colang_version` from `RailsConfig.colang_version`
- `models` from `RailsConfig.models` (excluding unsafe fields)
- `rails` from `RailsConfig.rails` (same as RuntimeRailsResponse)
- `flows` from `RailsConfig.flows` (flow names only)
- `instructions` from `RailsConfig.instructions` (instruction content)
- `prompts_count` from `len(RailsConfig.prompts)`
- `knowledge_base` from `RailsConfig.knowledge_base` and `docs` count

**Endpoint**: `GET /v1/runtime/config?config_id=<config_id>`

**Design Rationale**:
- Consolidates multiple existing endpoints (`/v1/rails/configs`, `/v1/models`, `/v1/challenges`) into one typed response
- Provides comprehensive configuration discoverability in a single call
- Simplifies AI agent integration by reducing number of API calls needed

---

## Field Descriptions for OpenAPI Spec

Each field includes a `description` parameter in Pydantic `Field()` that:
1. **Explains the field's purpose** in plain language
2. **Documents constraints** (e.g., enum values, ranges)
3. **Notes when data is unavailable** (e.g., "Omitted if not available")
4. **Avoids exposing secrets** (no mention of API keys, credentials, internal URLs)

### Example

```python
colang_version: str = Field(
    default="1.0",
    description="Colang version: '1.0' for Colang v1 or '2.x' for Colang v2."
)
```

This description tells consumers exactly what values to expect without exposing internal details.

---

## Edge Cases and Error Handling

### Multi-Config Mode

**Query Parameter Behavior**:
- `GET /v1/runtime/rails` → Error: "Missing required query parameter: config_id"
- `GET /v1/runtime/rails?config_id=nonexistent` → HTTP 404 with message
- `GET /v1/runtime/rails?config_id=valid_id` → HTTP 200 with RuntimeRailsResponse

### Single-Config Mode

**Query Parameter Behavior** (when server is in single-config mode):
- `GET /v1/runtime/rails` → HTTP 200 (uses the single config automatically)
- `GET /v1/runtime/rails?config_id=<id>` → HTTP 200 if `<id>` matches the single config, else HTTP 404

### Zero Configs

**Behavior**:
- If server has no configs loaded: `GET /v1/runtime/rails` → HTTP 404 "No guardrail configuration found"

---

## Backward Compatibility

These schemas are **net-new endpoints** and do not modify existing endpoints:
- `/v1/rails/configs` remains unchanged
- `/v1/models` remains unchanged
- `/v1/actions/list` remains unchanged

Future work (RHAI-521) may **optionally enhance** these existing endpoints with metadata, but the runtime schemas stand alone.

---

## Validation and Testing Strategy

### Pydantic Validation

Each model uses:
- Required fields: `type`, `engine`, `model`, `colang_version`, etc. (no Optional)
- Optional fields: `description`, `parameters`, `embedding_model`, etc. (Optional[T])
- Default values: `default_factory=list` for empty collections
- No extra fields allowed (via future ConfigDict if needed)

### Integration Testing (RHAI-521)

Test cases needed:
1. **Single config**: Response includes all fields
2. **Multi-config**: Response includes correct config when specified
3. **Missing config**: HTTP 404 with correct message
4. **No unsafe fields**: Verify api_key_env_var, parameters, actions_server_url are excluded
5. **Empty rails**: Response includes empty lists for unconfigured rail types
6. **OpenAPI spec**: Generated spec is complete and readable

---

## Future Extensions

### Fields to Add in Future Phases

- `RuntimeRailModel.is_enabled: bool` — if runtime toggles are added later
- `RuntimeRailModel.registered_at: datetime` — if registration tracking is added
- `RuntimeIntegrationModel` — if operator/TrustyAI integration surface is exposed at app level (currently not viable; dropped from scope)

### Endpoints to Add

- `GET /v1/runtime/rails` — list all rails (net-new)
- `GET /v1/runtime/actions` — list all actions (move from actions_server)
- `GET /v1/runtime/config` — consolidated config (net-new)
- `/v1/runtime/integrations` — dropped (integration is at K8s/operator level)

---

## References

- **Gap Analysis**: `/Users/kpunwatk/Downloads/RHAI-520-gap-analysis.md`
  - Section 6: LLMRails Runtime Accessibility Audit
  - Section 7: Endpoint Classification and Recommendations
  - Section 5: Secrets Filtering Approach

- **Existing Endpoints Audit**:
  - `/v1/rails/configs` — static config discovery
  - `/v1/models` — upstream provider models
  - `/v1/actions/list` — action dispatcher registry
  - `/v1/challenges` — red-teaming challenges

- **Related Code**:
  - `nemoguardrails/rails/llm/config.py:RailsConfig` — source of truth for config data
  - `nemoguardrails/rails/llm/llmrails.py:LLMRails` — runtime instance holder
  - `nemoguardrails/server/api.py` — FastAPI route handlers
