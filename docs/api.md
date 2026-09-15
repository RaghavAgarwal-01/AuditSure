# AuditSure API

A thin FastAPI HTTP layer over the existing AuditSure compliance engine.
**This document describes the actual implementation under `api/` -
nothing here is aspirational.**

## Architecture

```
Browser / React frontend
        │  HTTP + JSON
        ▼
   FastAPI (api/main.py)
        │  Pydantic validation (api/schemas.py)
        ▼
app.io.profile_loader.load_profile_from_dict   <- the ONE canonical
        │                                          JSON -> BusinessProfile
        ▼                                          conversion path
   BusinessProfile (app.models.business_profile)
        │
        ▼
app.auditsure_pipeline.run_compliance_check / generate_explanation
        │
        ├─► Phase 2 (Registration, Composition)
        ├─► Phase 3 (Supply Classification, Levy Mechanism)
        ├─► Phase 4 (Input Tax Credit)
        ├─► Phase 5 (E-Invoicing/E-Way Bill, Returns, TDS, TCS)
        └─► Phase 6 (Interest, Penalty, Refund, Appeal)
        │
        ▼
   ProofObject (app.models.proof_object)
        │
        ▼
app.llm.layer3_explainer.Layer3Explainer  (Groq, or dry-run)
        │
        ▼
   JSON response
```

`cli.py` and `api/` both call into `app.auditsure_pipeline` - there is
one compliance path, not two. The API contains **no GST business
logic**: no thresholds, no rates, no eligibility rules. Every legal
number, citation, and status in an API response was computed by the
existing Phase 2-6 engines and read out of the ontology
(`app.ontology.ontology_loader`).

## Running it

```bash
pip install -r requirements.txt --break-system-packages

# from the project root
python -m uvicorn api.main:app --reload --port 8000
# or
uvicorn api.main:app --reload --port 8000
```

Then open `http://localhost:8000/docs` for interactive Swagger docs.

The ontology path and `examples/` directory are resolved relative to
the project root (`api/config.py: PROJECT_ROOT`), so the API works the
same from the project root, from an IDE, under pytest, or under
uvicorn - no `cwd`-dependent behavior.

## Environment variables

See `.env.example`. None of these are required to run the API in
dry-run mode.

| Variable | Purpose | Default |
|---|---|---|
| `GROQ_API_KEY` | Enables real Layer 3 explanations. Without it, every explanation is dry-run (see below). Never returned in any response, log line, or error message. | unset |
| `GROQ_MODEL` | Groq model id used for explanations. | `llama-3.3-70b-versatile` (see `app/llm/layer3_explainer.py` for the code-level default if unset) |
| `AUDITSURE_CORS_ORIGINS` | Comma-separated list of allowed browser origins. | `http://localhost:5173` |
| `AUDITSURE_ENV` | `development` \| `production` - informational only. | `development` |
| `API_HOST` / `API_PORT` | Used only if you write your own run script; `uvicorn`'s own `--host`/`--port` flags take precedence when passed on the command line. | `127.0.0.1` / `8000` |

## Endpoints

All routes are mounted under `/api`. Full request/response shapes and
examples are in [`API_CONTRACT.md`](./API_CONTRACT.md); this section
covers behavior.

### `GET /api` and `GET /api/health`

`GET /api` is a trivial liveness ping. `GET /api/health` additionally
confirms the ontology can be loaded and reports its version:

```json
{"status": "ok", "service": "AuditSure", "version": "0.1.0", "ontology_version": "1.1.0"}
```

`status` is `"degraded"` (still HTTP 200) if the ontology file can't
be loaded - the frontend distinguishes this from a fully offline
backend (which never responds at all) to render CONNECTED / DEGRADED
/ OFFLINE. **This endpoint never calls Groq** - it costs nothing and
never blocks on an external service.

### `GET /api/demos` and `GET /api/demos/{name}`

Discovers actual files under `examples/` at request time - nothing is
hardcoded. The listing returns small presentation metadata read
directly from each JSON file (name, state, turnover, etc. - not
processed through the domain loader, to keep the payload small). The
detail endpoint resolves `{name}` against a strict `[A-Za-z0-9_-]+`
pattern, loads it through the real `app.io.profile_loader`, and
returns `BusinessProfile.to_dict()` (the domain's own canonical JSON
representation). A request like `/api/demos/..%2F..%2F.env` never
reaches the filesystem outside `examples/` - it 404s.

### `GET /api/ontology`, `GET /api/ontology/thresholds`, `GET /api/ontology/sections`

Everything is read live from `app.ontology.ontology_loader.get_default_loader()`,
which is itself a process-wide, internally-`lru_cache`d singleton - the
API does not build a second cache. If the `.ttl` file is edited, these
endpoints reflect the change without a code deploy.

### `POST /api/compliance/check`

The primary endpoint. Request:

```json
{
  "profile": { "...BusinessProfile fields...": "..." },
  "as_of": "2026-09-10"
}
```

`as_of` is optional (defaults to today, per `app.auditsure_pipeline`'s
own default). `profile` supports every field on `BusinessProfile` and
its nested records (`OutwardSupplyRecord`, `InvoiceRecord`,
`TaxPaymentRecord`, `RefundClaim`, `AppealRecord`) - see
`api/schemas.py`, which mirrors `app/models/business_profile.py`
field-for-field.

Flow:

1. Pydantic validates the request shape (`api/schemas.py`).
2. The validated model is dumped to a plain JSON-safe dict
   (`model_dump(mode="json", exclude_unset=True)`) and handed to
   `app.io.profile_loader.load_profile_from_dict` - the same converter
   `cli.py` uses.
3. `app.auditsure_pipeline.run_compliance_check` runs the real Phase
   2-6 pipeline and produces the real `ProofObject`. Ontology-level
   validation failures (unknown state, business type, supply type, or
   registration status) surface as `422 PROFILE_VALIDATION_ERROR`.
4. `Layer3Explainer().explain(proof)` generates the explanation. A
   Groq/config failure here does **not** discard the proof - see
   below.
5. The response is assembled from `ProofObject.to_dict()` (the
   domain's own serialization, including its `summary_counts()`) plus
   a derived phase summary (`api/serialization.py: build_phase_summary`,
   which only re-groups `RuleEvaluation.module` values that the real
   engines already assigned - it invents no new legal facts).

No "overall compliance score" or percentage is ever returned, because
the domain model does not define one (`ProofObject` has no such
field) - per the explicit instruction not to invent one.

#### Decimal and date handling

Request JSON may send monetary fields as either a JSON number or a
JSON string (`"2500000"` or `2500000`); Pydantic parses either into a
`Decimal`. Financial values are never converted to `float` anywhere in
the request path. Dates are plain `YYYY-MM-DD` ISO strings, parsed
into Python `date` objects - never timezone-shifted.

Response monetary/date values follow whatever the underlying domain
object's own serialization already does: `RuleEvaluation.computed_value`
/ `threshold_value` are domain-typed as `float` already (that is an
existing Phase 2-6 engine decision, not something the API layer
introduces), and `ProofObject.to_dict()` / `BusinessProfile.to_dict()`
are used as-is rather than re-implemented.

#### Explanation failure vs. compliance failure

These are deliberately different things:

- **Compliance analysis failure** (bad input, e.g. an unknown state) →
  the whole request fails with `422 PROFILE_VALIDATION_ERROR` - there
  is no proof to return.
- **Explanation failure** (Groq unreachable/misconfigured, `Layer3ConfigurationError`) →
  the request still returns `200`. The real, already-computed
  `ProofObject` is returned in full; `explanation` is `null`; and
  `explanation_error` carries `{"code": "EXPLANATION_UNAVAILABLE", "message": "..."}`.

A Groq outage never makes a valid deterministic compliance result
disappear.

#### Dry-run mode

If `GROQ_API_KEY` is unset, `Layer3Explainer` runs in its own built-in
dry-run mode (unchanged - the API does not add a second mock LLM) and
`explanation` is populated with the literal prompt that would have
been sent, prefixed with `[DRY RUN - ...]`. This is not treated as an
error; `explanation_error` stays `null`.

## Error format

Every error response has the shape:

```json
{"error": {"code": "...", "message": "...", "details": null_or_array}}
```

| Code | HTTP status | When |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Request JSON fails Pydantic schema validation (wrong type, missing required field, unknown field, malformed date) |
| `PROFILE_VALIDATION_ERROR` | 422 | Well-formed JSON that fails `BusinessProfile` conversion or ontology-aware validation (unknown state/business type/supply type/registration status) |
| `DEMO_NOT_FOUND` | 404 | `GET /api/demos/{name}` for a name that doesn't resolve to a real file under `examples/` |
| `ONTOLOGY_ERROR` | 503 | The ontology `.ttl` file could not be loaded, or a requested ontology individual doesn't exist |
| `COMPLIANCE_ANALYSIS_ERROR` | 500 | The Phase 2-6 pipeline raised something other than a profile validation `ValueError` (should not happen against a valid profile - engines are deterministic) |
| `INTERNAL_SERVER_ERROR` | 500 | Anything else unexpected. Full detail is logged server-side (`logger.exception`); the client never sees a traceback. |

`GROQ_API_KEY` is never included in any response, error message, or
log line - see `app/llm/layer3_explainer.py`, which is the only module
in the codebase that touches it.

## CORS

Configured via `AUDITSURE_CORS_ORIGINS` (`api/config.py`, applied in
`api/main.py` via `CORSMiddleware`). Not hardcoded to `["*"]`. Verified
against `http://localhost:5173` (the Vite dev server default) and
against a disallowed origin.

## Logging

Each request logs method, path, response status, and duration, tagged
with a generated request ID (also returned as the `X-Request-ID`
response header). Request bodies (which may carry PAN/GSTIN) and
`GROQ_API_KEY` are never logged.

## Testing

```bash
# original AuditSure suite - must stay green
python3 -m pytest tests/test_phase2.py tests/test_phase3.py tests/test_phase4.py \
                   tests/test_phase5.py tests/test_phase6.py tests/test_phase7.py \
                   tests/test_phase8_integration.py tests/test_phase9_cli.py -v

# API suite - offline, no GROQ_API_KEY required
python3 -m pytest tests/test_api_health.py tests/test_api_compliance.py \
                   tests/test_api_demos.py tests/test_api_ontology.py -v

# everything
python3 -m pytest -v
```

At the time this document was written: **205 passed, 1 skipped**
(184 passed / 1 skipped from the original suite, unchanged; 21 new API
tests, all passing).

A real Groq-backed request is not part of the automated suite (it
would cost money and require network access); it's a manual check:
set `GROQ_API_KEY`, hit `POST /api/compliance/check`, and confirm
`explanation` contains real prose rather than the `[DRY RUN ...]`
prefix while `explanation_error` stays `null`.

## What the API deliberately does NOT do

- No database (no persistent request history).
- No authentication (local/project-stage application).
- No file upload endpoint (the frontend can add one later on top of
  the same `POST /api/compliance/check` contract).
- No PDF/report generation endpoint.
- No background jobs / WebSockets / fabricated progress events - the
  compliance endpoint is synchronous request/response.
- No second copy of GST thresholds, rates, or eligibility rules
  anywhere under `api/`.
