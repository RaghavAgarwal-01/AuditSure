# AuditSure - GST Compliance Reasoning Engine

A neuro-symbolic GST compliance verification system for Indian MSMEs. This
repository contains **Layer 1** (an OWL 2 ontology encoding CGST/IGST law),
**Layer 2** (a Python + Z3 symbolic reasoning engine), and **Layer 3** (an
LLM explanation bridge) - see `AuditSure_Project_Report.docx` for the full
technical report. Two interfaces sit on top of the same engine: a **CLI**
(`cli.py`) and an **HTTP API** (`api/`, FastAPI) for the React frontend.

```
Browser (React frontend)
        │  HTTP + JSON
        ▼
FastAPI (api/)  ──┐
                  ├──►  app.auditsure_pipeline
CLI (cli.py)  ────┘            │
                                ▼
      BusinessProfile  --[Z3 reasoning against Layer 1 ontology]-->  ProofObject  --[Groq]-->  plain-English explanation
```

The CLI and the API call the exact same `app.auditsure_pipeline` facade -
there is one compliance path, not two. Compliance verdicts are produced
entirely by deterministic rule evaluation against the ontology; the LLM
is used only to explain the resulting `ProofObject` in plain English, and
never decides compliance itself.

## Quick start

```bash
pip install -r requirements.txt --break-system-packages

# --- CLI ---
python3 cli.py --demo growing_manufacturer
python3 cli.py --profile examples/small_composition_trader.json
python3 cli.py --interactive

# --- HTTP API ---
python -m uvicorn api.main:app --reload --port 8000
# then open http://localhost:8000/docs

# Run the full test suite (Layer 2/3 engine + API layer)
python3 -m pytest -v
```

Layer 3 auto-detects whether `GROQ_API_KEY` is set. Without it, every
explanation call runs in **dry-run mode** and returns the exact prompt that
would have been sent - the whole pipeline (CLI and API alike) is fully
runnable and testable with zero external dependencies or cost.

## Architecture at a glance

| Layer | What it does | Key files |
|---|---|---|
| 1 | Sole source of legal truth: every threshold, rate, section citation | `ontology/auditsure_gst_ontology.ttl` |
| 2 | Machine-checked compliance verdicts via Z3, read out with a full citation trail | `app/ontology/ontology_loader.py`, `app/engines/*.py`, `app/pipelines/phase*_pipeline.py` |
| 3 | Rephrases Layer 2's verdict for a human - cannot introduce new legal content | `app/llm/explanation_prompt.py`, `app/llm/layer3_explainer.py` |
| - | Stable public entry point (shared by the CLI and the API) | `app/auditsure_pipeline.py` |
| - | HTTP API (thin adapter, no compliance logic) | `api/` - see `docs/api.md` and `docs/API_CONTRACT.md` |
| - | Demo CLI | `cli.py`, `app/io/profile_loader.py`, `examples/*.json` |

**Golden rule:** if you need a number, a citation, or a business-type name,
get it from `OntologyLoader` - never hard-code it. If the ontology changes,
every engine that uses `onto.get_threshold(...)` picks up the change
automatically, and so does the API (`GET /api/ontology`).

## Using it as a library

```python
from datetime import date
from decimal import Decimal
from app.models.business_profile import BusinessProfile
from app.auditsure_pipeline import generate_explanation

profile = BusinessProfile(
    name="Example Trader", state="Karnataka",
    aggregate_turnover=Decimal("2500000"), financial_year="2025-26",
    business_types=["Trader"],
)
proof, explanation = generate_explanation(profile, as_of_date=date.today())

print(proof.summary_counts())   # {'SATISFIED': .., 'VIOLATED': .., ...}
for e in proof.violations():
    print(e.legal_citation, "-", e.explanation_hint)
print(explanation)               # Layer 3's Markdown report
```

`state` and `business_types` must match the ontology's own individual IDs
(e.g. `"Karnataka"`, `"TamilNadu"`, `"DelhiNationalCapitalTerritory"`, not
display labels with spaces) - `validate_against_ontology()` catches typos
here before they reach Z3, and `auditsure_pipeline.generate_explanation`
raises `ValueError` with a clear message if validation fails.

## Writing a JSON profile

See `examples/*.json` for complete samples. Minimal shape:

```json
{
  "name": "My Business",
  "state": "Karnataka",
  "aggregate_turnover": "2500000",
  "financial_year": "2025-26",
  "business_types": ["Trader"],
  "registration_status": "ActiveStatus"
}
```

`registration_status` values: `"ActiveStatus"`, `"CancelledStatus"`,
`"SuspendedStatus"`, `"PendingForCancellationStatus"`, `"NotRegistered"`.

## HTTP API

A FastAPI backend under `api/` exposes the same engine over HTTP for the
React frontend:

```bash
uvicorn api.main:app --reload --port 8000
```

| Route | Purpose |
|---|---|
| `GET /api/health` | Liveness + ontology reachability (never calls Groq) |
| `GET /api/demos`, `GET /api/demos/{name}` | Discovers and serves the real `examples/*.json` personas |
| `GET /api/ontology`, `/api/ontology/thresholds`, `/api/ontology/sections` | Live ontology metadata |
| `POST /api/compliance/check` | Runs `app.auditsure_pipeline.generate_explanation` and returns the full `ProofObject`, a derived phase summary, and the Layer 3 explanation |

The API is a **thin adapter**: it validates HTTP input with Pydantic,
converts it to a `BusinessProfile` through the existing
`app.io.profile_loader`, and serializes the existing `ProofObject` - it
contains no GST thresholds, rates, or eligibility logic of its own. A
Groq/Layer-3 failure never discards a valid deterministic proof; it comes
back as `explanation: null` alongside a structured `explanation_error`.

See [`docs/api.md`](docs/api.md) for architecture/behavior and
[`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) for the full endpoint
reference with real request/response examples. CORS origins are
configured via `AUDITSURE_CORS_ORIGINS` in `.env` (see `.env.example`).

## Project layout

```
ontology/auditsure_gst_ontology.ttl   Layer 1 ontology (edit the .ttl - see below)

app/
├── models/business_profile.py        Input schema (BusinessProfile + nested records)
├── models/proof_object.py            Output schema (ProofObject + RuleEvaluation)
├── ontology/ontology_loader.py       Typed accessors over the ontology
├── engines/
│   ├── registration_engine.py        Sec 22/23/24
│   ├── composition_engine.py         Sec 10
│   ├── supply_classification_engine.py   Sec 7/8, Sec 16 IGST
│   ├── levy_mechanism_engine.py      Sec 9(3)/9(4)
│   ├── itc_engine.py                 Sec 16(2)/16(4)/17(5), Rule 37, Sec 10(4)
│   ├── einvoice_ewaybill_engine.py   Rule 48(4), Rule 138
│   ├── return_obligation_engine.py   Sec 37/39/44
│   ├── tds_tcs_engine.py             Sec 51/52
│   ├── interest_engine.py            Sec 50
│   ├── penalty_engine.py             Sec 122
│   ├── refund_engine.py              Sec 54
│   └── appeal_engine.py              Sec 107
├── pipelines/phase2_pipeline.py ... phase6_pipeline.py   Sequential wiring, one per phase
├── llm/explanation_prompt.py         Deterministic LLM prompt construction
├── llm/layer3_explainer.py           Groq API call (with dry-run mode)
├── io/profile_loader.py              JSON -> BusinessProfile (used by BOTH cli.py and api/)
└── auditsure_pipeline.py             Stable top-level facade - import this, not phaseN_pipeline

api/
├── main.py                           FastAPI app, CORS, exception handlers, routers
├── schemas.py                        Pydantic HTTP-boundary schemas (mirror app.models exactly)
├── serialization.py                  Phase-summary derivation from the real ProofObject
├── exceptions.py                     Structured {"error": {...}} model
├── config.py                         Env-var settings (CORS origins, host/port)
└── routes/health.py, compliance.py, demos.py, ontology.py

cli.py                                Demo CLI - shares app.auditsure_pipeline with api/
examples/*.json                       Four demo personas
tests/test_phase*.py, test_phase8_integration.py, test_phase9_cli.py   Layer 2/3 engine tests
tests/test_api_*.py                   API layer tests
docs/api.md, docs/API_CONTRACT.md     API architecture + endpoint reference
```

## Editing the ontology

After any edit to `ontology/auditsure_gst_ontology.ttl`:

```bash
python3 -c "
import rdflib
g = rdflib.Graph(); g.parse('ontology/auditsure_gst_ontology.ttl', format='turtle')
print('Triples:', len(g))
g.serialize(destination='ontology/auditsure_gst_ontology.owl', format='xml')
"
python3 -c "
import owlready2 as owl
onto = owl.get_ontology('file://' + __import__('os').path.abspath('ontology/auditsure_gst_ontology.owl')).load()
with onto: owl.sync_reasoner_hermit(debug=0)
print('Consistent:', list(onto.inconsistent_classes()) == [])
"
```

Then **bump `owl:versionInfo`** in the ontology header and update the
expected version string in `test_phase8_integration.py`
(`EXPECTED_ONTOLOGY_VERSION`) - this is a deliberate speed bump, not
friction: it forces a human to review whether any pinned threshold value
in the test suite needs to change alongside the ontology edit.

## Known limitations

See the full list in the project report (Section 8) or in the docstring of
the relevant engine. Highlights: numeric GST rate slabs are not modelled
(not in the source manual); sector-specific e-invoicing/e-way-bill
exemptions are not modelled; Sec 51 TDS is checked per-invoice, not
per-contract; QRMP return-frequency eligibility is informational only.

## License / provenance

Legal content sourced from the *GST Manual, Sixth Half-Yearly Edition, 01
January 2026* (Garg & Garg) and the public text of the CGST/IGST Acts and
Rules. No commentary text from that compilation is reproduced; all
`rdfs:comment` annotations are original paraphrase for ontology
documentation.
