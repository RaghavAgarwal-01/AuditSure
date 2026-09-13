# AuditSure Layer 2 - GST Compliance Reasoning Engine

A neuro-symbolic GST compliance verification system for Indian MSMEs. This
repository contains **Layer 1** (an OWL 2 ontology encoding CGST/IGST law),
**Layer 2** (a Python + Z3 symbolic reasoning engine), and **Layer 3** (an
LLM explanation bridge) - see `AuditSure_Project_Report.docx` for the full
technical report.

```
BusinessProfile  --[Z3 reasoning against Layer 1 ontology]-->  ProofObject  --[LLM]-->  plain-English explanation
```

## Quick start

```bash
pip install rdflib owlready2 z3-solver anthropic rich pytest --break-system-packages

# Run a built-in demo persona
python3 cli.py --demo growing_manufacturer

# Run your own profile
python3 cli.py --profile examples/small_composition_trader.json

# Build one interactively
python3 cli.py --interactive

# Run the full test suite (184 tests)
python3 -m pytest test_phase2.py test_phase3.py test_phase4.py test_phase5.py \
                   test_phase6.py test_phase7.py test_phase8_integration.py \
                   test_phase9_cli.py -v
```

Layer 3 auto-detects whether `ANTHROPIC_API_KEY` is set. Without it, every
explanation call runs in **dry-run mode** and returns the exact prompt that
would have been sent - the whole pipeline is fully runnable and testable
with zero external dependencies or cost.

## Architecture at a glance

| Layer | What it does | Key files |
|---|---|---|
| 1 | Sole source of legal truth: every threshold, rate, section citation | `auditsure_gst_ontology.ttl` / `.owl` |
| 2 | Machine-checked compliance verdicts via Z3, read out with a full citation trail | `ontology_loader.py`, `*_engine.py`, `phase*_pipeline.py` |
| 3 | Rephrases Layer 2's verdict for a human - cannot introduce new legal content | `explanation_prompt.py`, `layer3_explainer.py` |
| - | Stable public entry point | `auditsure_pipeline.py` |
| - | Demo interface | `cli.py`, `profile_loader.py`, `examples/*.json` |

**Golden rule:** if you need a number, a citation, or a business-type name,
get it from `OntologyLoader` - never hard-code it. If the ontology changes,
every engine that uses `onto.get_threshold(...)` picks up the change
automatically.

## Using it as a library

```python
from datetime import date
from decimal import Decimal
from business_profile import BusinessProfile
from auditsure_pipeline import generate_explanation

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

## Project layout

```
auditsure_gst_ontology.ttl/.owl   Layer 1 ontology (edit the .ttl; regenerate .owl - see below)
ontology_loader.py                Typed accessors over the ontology
business_profile.py               Input schema (BusinessProfile + nested records)
proof_object.py                   Output schema (ProofObject + RuleEvaluation)
registration_engine.py            Sec 22/23/24
composition_engine.py             Sec 10
supply_classification_engine.py   Sec 7/8, Sec 16 IGST
levy_mechanism_engine.py          Sec 9(3)/9(4)
itc_engine.py                     Sec 16(2)/16(4)/17(5), Rule 37, Sec 10(4)
einvoice_ewaybill_engine.py       Rule 48(4), Rule 138
return_obligation_engine.py       Sec 37/39/44
tds_tcs_engine.py                 Sec 51/52
interest_engine.py                Sec 50
penalty_engine.py                 Sec 122
refund_engine.py                  Sec 54
appeal_engine.py                  Sec 107
phase2_pipeline.py ... phase6_pipeline.py   Sequential wiring, one per phase
explanation_prompt.py             Deterministic LLM prompt construction
layer3_explainer.py               LLM API call (with dry-run mode)
auditsure_pipeline.py             Stable top-level facade - import this, not phaseN_pipeline
cli.py, profile_loader.py         Demo CLI + JSON deserializer
examples/*.json                   Four demo personas
test_*.py                         184 tests
```

## Editing the ontology

After any edit to `auditsure_gst_ontology.ttl`:

```bash
python3 -c "
import rdflib
g = rdflib.Graph(); g.parse('auditsure_gst_ontology.ttl', format='turtle')
print('Triples:', len(g))
g.serialize(destination='auditsure_gst_ontology.owl', format='xml')
"
python3 -c "
import owlready2 as owl
onto = owl.get_ontology('file://' + __import__('os').path.abspath('auditsure_gst_ontology.owl')).load()
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
