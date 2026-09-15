# AuditSure API Contract

Base URL (local dev): `http://localhost:8000`

Every example below was captured from the actual running implementation
(`api/`) - none of it is aspirational. See [`api.md`](./api.md) for
architecture and behavior notes.

---

## `GET /api`

Trivial liveness ping.

**Response `200`**
```json
{"service": "AuditSure API", "status": "ok", "docs": "/docs"}
```

---

## `GET /api/health`

**Response `200` (ontology loaded)**
```json
{
  "status": "ok",
  "service": "AuditSure",
  "version": "0.1.0",
  "ontology_version": "1.1.0",
  "detail": null
}
```

**Response `200` (ontology unavailable - still 200, `status` signals degradation)**
```json
{
  "status": "degraded",
  "service": "AuditSure",
  "version": "0.1.0",
  "ontology_version": null,
  "detail": "Ontology unavailable: <exception message>"
}
```

Never calls Groq. No error status codes - a response arriving at all
means the process is up; `status` communicates the rest.

---

## `GET /api/demos`

Discovers `examples/*.json` at request time.

**Response `200`**
```json
[
  {
    "id": "growing_manufacturer",
    "name": "Deccan Precision Manufacturing",
    "state": "Karnataka",
    "financial_year": "2025-26",
    "business_types": ["Manufacturer"],
    "aggregate_turnover": "30000000",
    "registration_status": "ActiveStatus"
  },
  {
    "id": "small_composition_trader",
    "name": "Meenakshi General Store",
    "state": "TamilNadu",
    "financial_year": "2025-26",
    "business_types": ["Trader"],
    "aggregate_turnover": "1800000",
    "registration_status": "ActiveStatus"
  },
  {
    "id": "special_category_interstate",
    "name": "Manipur Handloom Exports",
    "state": "Manipur",
    "financial_year": "2025-26",
    "business_types": ["Manufacturer"],
    "aggregate_turnover": "1200000",
    "registration_status": "NotRegistered"
  },
  {
    "id": "unregistered_noncompliant",
    "name": "Ghost Enterprises",
    "state": "Maharashtra",
    "financial_year": "2025-26",
    "business_types": ["Trader"],
    "aggregate_turnover": "5000000",
    "registration_status": "NotRegistered"
  }
]
```

---

## `GET /api/demos/{name}`

`{name}` is one of the ids from the listing above (validated against
`^[A-Za-z0-9_-]+$`; anything else, or a name that doesn't resolve to a
real file under `examples/`, 404s - no exception).

**Response `200`** (`GET /api/demos/small_composition_trader`, abridged - full BusinessProfile field set is present)
```json
{
  "id": "small_composition_trader",
  "profile": {
    "name": "Meenakshi General Store",
    "pan": null,
    "gstin": null,
    "state": "TamilNadu",
    "registration_status": "ActiveStatus",
    "registration_date": null,
    "voluntarily_registered": false,
    "aggregate_turnover": 1800000.0,
    "financial_year": "2025-26",
    "turnover_by_year": {},
    "annual_return_filed_dates": {},
    "business_types": ["Trader"],
    "opts_for_composition": true,
    "makes_interstate_outward_supply": false,
    "outward_supplies": [],
    "inward_invoices": [],
    "tax_payment_records": [],
    "refund_claims": [],
    "appeal_records": [],
    "extra": {}
  }
}
```
(This is `BusinessProfile.to_dict()` verbatim - the domain's own
canonical representation, which serializes `Decimal` as `float`. Every
field can be sent straight into `POST /api/compliance/check`.)

**Response `404`**
```json
{"error": {"code": "DEMO_NOT_FOUND", "message": "No demo persona named 'does_not_exist'.", "details": null}}
```

---

## `GET /api/ontology`

**Response `200` (abridged - `states` has 31 entries, `business_types` 12, etc.)**
```json
{
  "ontology_version": "1.1.0",
  "states": [
    {"id": "AndhraPradesh", "label": "Andhra Pradesh", "is_special_category": false},
    "... 30 more ..."
  ],
  "special_category_states": ["Manipur", "Mizoram", "Nagaland", "Tripura"],
  "business_types": ["Agriculturist", "CasualTaxablePerson", "ECommerceOperator", "Exporter", "GoodsTransportAgency", "Importer", "InputServiceDistributor", "MSME", "Manufacturer", "NonResidentTaxablePerson", "ServiceProvider", "Trader"],
  "supply_types": ["CompositeSupply", "DeemedExport", "ExemptSupply", "InterStateSupply", "IntraStateSupply", "MixedSupply", "NilRatedSupply", "NonTaxableSupply", "TaxableSupply", "WhollyExemptSupply", "ZeroRatedSupply"],
  "registration_statuses": ["ActiveStatus", "CancelledStatus", "PendingForCancellationStatus", "SuspendedStatus"],
  "return_frequencies": ["AnnualFrequency", "MonthlyFrequency", "QuarterlyFrequency"],
  "modules": [
    {"phase": 2, "name": "Registration & Composition", "modules": ["Registration", "Composition"]},
    {"phase": 3, "name": "Supply & Levy", "modules": ["SupplyClassification"]},
    {"phase": 4, "name": "Input Tax Credit", "modules": ["InputTaxCredit"]},
    {"phase": 5, "name": "Compliance Obligations", "modules": ["ComplianceObligations"]},
    {"phase": 6, "name": "Financial Consequences", "modules": ["FinancialConsequences"]}
  ],
  "threshold_count": 20,
  "section_count": 215
}
```

`registration_statuses` intentionally does NOT include `"NotRegistered"` -
that is a domain sentinel (`RegistrationStatus.NOT_REGISTERED`) for "never
registered," not a real ontology individual (see
`app/models/business_profile.py`).

---

## `GET /api/ontology/thresholds`

**Response `200`** (1 of 20 entries shown)
```json
[
  {
    "id": "ThresholdAppealLimitation3Months",
    "amount": 3.0,
    "unit": "MONTHS",
    "label": "Appeal Limitation Period (3 Months, +1 month condonable)",
    "citation": "Sec 107(1), CGST Act 2017",
    "source_note": null
  }
]
```

---

## `GET /api/ontology/sections`

**Response `200`** (1 of 215 entries shown)
```json
[
  {
    "id": "CGST_Section1",
    "number": "1",
    "title": "Short title, extent and commencement",
    "act": "CGSTAct2017",
    "chapter": "CGST_ChapterI",
    "comment": null,
    "threshold_ids": []
  }
]
```

---

## `POST /api/compliance/check`

**Request**
```json
{
  "profile": {
    "name": "Meenakshi General Store",
    "state": "TamilNadu",
    "aggregate_turnover": "1800000",
    "financial_year": "2025-26",
    "business_types": ["Trader"],
    "opts_for_composition": true,
    "registration_status": "ActiveStatus"
  },
  "as_of": "2026-09-10"
}
```

`as_of` is optional; omitting it defaults to today. `profile` accepts
every `BusinessProfile` field (see `api/schemas.py` /
`app/models/business_profile.py`) - the example above only shows the
fields this particular demo persona sets; nested lists like
`outward_supplies`, `inward_invoices`, `tax_payment_records`,
`refund_claims`, and `appeal_records` are all supported.

**Response `200`** (real output for the request above, evaluations list trimmed to 2 of 5 for brevity)
```json
{
  "proof": {
    "business_name": "Meenakshi General Store",
    "financial_year": "2025-26",
    "generated_at": "2026-09-13T12:15:37.261103+00:00",
    "ontology_version": "1.1.0",
    "summary": {"SATISFIED": 4, "VIOLATED": 0, "NOT_APPLICABLE": 1, "INDETERMINATE": 0},
    "evaluations": [
      {
        "rule_id": "Sec22_RegistrationLiability",
        "module": "Registration",
        "status": "SATISFIED",
        "legal_citation": "Sec 22(1) first proviso omitted / main provision, CGST Act 2017",
        "section_number": "22",
        "description": "Turnover-threshold registration check against Registration Threshold - General (Rs 20 Lakh).",
        "inputs_used": {"aggregate_turnover": 1800000.0, "state": "TamilNadu"},
        "computed_value": 1800000.0,
        "threshold_value": 2000000.0,
        "threshold_id": "ThresholdRegistrationGeneral20L",
        "explanation_hint": "Meenakshi General Store's aggregate turnover of Rs 1,800,000 does not exceed the Rs 2,000,000 threshold under Sec 22(1) first proviso omitted / main provision, CGST Act 2017, so registration is not mandatory (voluntary registration remains an option under Sec 25(3)).",
        "evaluated_at": "2026-09-13T12:15:37.272666+00:00"
      },
      {
        "rule_id": "Sec10_1_CompositionGoods",
        "module": "Composition",
        "status": "SATISFIED",
        "legal_citation": "Sec 10(1), CGST Act 2017",
        "section_number": "10",
        "description": "Composition levy eligibility check (goods/restaurant scheme).",
        "inputs_used": {"aggregate_turnover": 1800000.0, "state": "TamilNadu", "makes_interstate_outward_supply": false, "supplies_via_ecommerce_collecting_tcs": false},
        "computed_value": 1800000.0,
        "threshold_value": 15000000.0,
        "threshold_id": "ThresholdCompositionGoods1_5Cr",
        "explanation_hint": "Meenakshi General Store is eligible to opt for the goods/restaurant composition levy under Sec 10(1), CGST Act 2017: turnover of Rs 1,800,000 is within the Rs 15,000,000 threshold (Composition Threshold - Goods, General States (Rs 1.5 Crore)), with no inter-State outward supply and no disqualifying e-commerce/TCS supply.",
        "evaluated_at": "2026-09-13T12:15:37.274183+00:00"
      }
    ]
  },
  "summary": {"SATISFIED": 4, "VIOLATED": 0, "NOT_APPLICABLE": 1, "INDETERMINATE": 0},
  "phases": [
    {"phase": 2, "name": "Registration & Composition", "modules": ["Composition", "Registration"], "satisfied": 2, "violated": 0, "indeterminate": 0, "not_applicable": 0, "total": 2},
    {"phase": 3, "name": "Supply & Levy", "modules": [], "satisfied": 0, "violated": 0, "indeterminate": 0, "not_applicable": 0, "total": 0},
    {"phase": 4, "name": "Input Tax Credit", "modules": [], "satisfied": 0, "violated": 0, "indeterminate": 0, "not_applicable": 0, "total": 0},
    {"phase": 5, "name": "Compliance Obligations", "modules": ["ComplianceObligations"], "satisfied": 2, "violated": 0, "indeterminate": 0, "not_applicable": 1, "total": 3},
    {"phase": 6, "name": "Financial Consequences", "modules": [], "satisfied": 0, "violated": 0, "indeterminate": 0, "not_applicable": 0, "total": 0}
  ],
  "explanation": "[DRY RUN - no GROQ_API_KEY configured; showing the exact prompt that would be sent instead of a real explanation]\n\n--- SYSTEM PROMPT ---\n...\n\n--- USER MESSAGE ---\n...",
  "explanation_error": null,
  "metadata": {
    "ontology_version": "1.1.0",
    "generated_at": "2026-09-13T12:15:37.261103+00:00",
    "financial_year": "2025-26",
    "business_name": "Meenakshi General Store",
    "as_of": "2026-09-10"
  }
}
```

`phases` always lists Phase 2 through Phase 6, even when a phase fired
zero rules for this profile (e.g. Phase 3/4/6 above) - `total: 0` is
truthful, not a gap to special-case in the frontend.

There is no `"overall_score"`, `"compliance_score"`, or any percentage
anywhere in the response - `ProofObject` defines no such field, so the
API does not invent one.

### Errors

**`422 VALIDATION_ERROR`** - request JSON fails Pydantic schema validation
(missing required field, wrong type, unknown field, malformed date):
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request body failed schema validation.",
    "details": [
      {"type": "missing", "loc": ["body", "profile", "name"], "msg": "Field required", "input": {}}
    ]
  }
}
```

**`422 PROFILE_VALIDATION_ERROR`** - well-formed JSON that fails
ontology-aware validation:
```json
{
  "error": {
    "code": "PROFILE_VALIDATION_ERROR",
    "message": "BusinessProfile 'Bad Co' failed ontology validation: [\"state 'uttar pradesh' is not a known gst:State individual.\"]",
    "details": null
  }
}
```

**`500 COMPLIANCE_ANALYSIS_ERROR`** / **`500 INTERNAL_SERVER_ERROR`** -
unexpected failure; message is generic, full detail is server-logged only:
```json
{"error": {"code": "INTERNAL_SERVER_ERROR", "message": "An unexpected error occurred while processing the request.", "details": null}}
```

### Explanation failure (Groq unavailable) - still `200`

```json
{
  "proof": { "...": "full ProofObject, unaffected..." },
  "summary": { "SATISFIED": 4, "VIOLATED": 0, "NOT_APPLICABLE": 1, "INDETERMINATE": 0 },
  "phases": [ "..." ],
  "explanation": null,
  "explanation_error": {
    "code": "EXPLANATION_UNAVAILABLE",
    "message": "Groq API request failed: <underlying error>"
  },
  "metadata": { "...": "..." }
}
```

---

## Status code summary

| Status | Meaning |
|---|---|
| `200` | Successful read, or a completed compliance analysis (even if the explanation failed - see above) |
| `404` | `GET /api/demos/{name}` for an unknown or invalid name |
| `422` | Request schema validation failure, or profile/ontology validation failure |
| `500` | Unexpected server-side failure |
| `503` | Ontology dependency unavailable (`ONTOLOGY_ERROR`) |
