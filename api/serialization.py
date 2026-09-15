"""
AuditSure API - Serialization Helpers
===========================================
Thin, deterministic, testable adapters from domain objects to
JSON-safe structures. None of these functions make a compliance
decision - they only regroup/re-key data that ProofObject/RuleEvaluation
already computed (see app.models.proof_object).

Module -> Phase mapping is derived directly from which
ComplianceModule value each engine actually assigns (verified against
app/engines/*.py), not invented for the API.
"""

from __future__ import annotations

from app.models.proof_object import ComplianceModule, ProofObject, VerdictStatus

# One entry per ComplianceModule -> (phase number, display name).
# Phase 2: Registration + Composition
# Phase 3: Supply Classification + Levy Mechanism (both fire under the
#          single SUPPLY_CLASSIFICATION module value)
# Phase 4: Input Tax Credit
# Phase 5: Compliance Obligations (e-invoicing, e-way bill, returns, TDS/TCS)
# Phase 6: Financial Consequences (interest, penalty, refund, appeal)
_MODULE_TO_PHASE: dict[ComplianceModule, tuple[int, str]] = {
    ComplianceModule.REGISTRATION: (2, "Registration & Composition"),
    ComplianceModule.COMPOSITION: (2, "Registration & Composition"),
    ComplianceModule.SUPPLY_CLASSIFICATION: (3, "Supply & Levy"),
    ComplianceModule.INPUT_TAX_CREDIT: (4, "Input Tax Credit"),
    ComplianceModule.COMPLIANCE_OBLIGATIONS: (5, "Compliance Obligations"),
    ComplianceModule.FINANCIAL_CONSEQUENCES: (6, "Financial Consequences"),
}

_STATUS_KEY = {
    VerdictStatus.SATISFIED: "satisfied",
    VerdictStatus.VIOLATED: "violated",
    VerdictStatus.INDETERMINATE: "indeterminate",
    VerdictStatus.NOT_APPLICABLE: "not_applicable",
}


def build_phase_summary(proof: ProofObject) -> list[dict]:
    """Groups proof.evaluations by their real module, maps each module
    to its phase, and counts statuses per phase. Phases 2-6 are always
    present (zero-filled) even if a profile triggered no rules in that
    phase, so the frontend can render a stable Phase 2-6 overview
    without special-casing missing phases."""
    phases: dict[int, dict] = {
        num: {
            "phase": num,
            "name": name,
            "modules": set(),
            "satisfied": 0,
            "violated": 0,
            "indeterminate": 0,
            "not_applicable": 0,
            "total": 0,
        }
        for num, name in sorted({v for v in _MODULE_TO_PHASE.values()})
    }

    for evaluation in proof.evaluations:
        phase_num, phase_name = _MODULE_TO_PHASE[evaluation.module]
        bucket = phases[phase_num]
        bucket["modules"].add(evaluation.module.value)
        bucket["total"] += 1
        bucket[_STATUS_KEY[evaluation.status]] += 1

    result = []
    for num in sorted(phases):
        bucket = phases[num]
        bucket["modules"] = sorted(bucket["modules"])
        result.append(bucket)
    return result


def ontology_module_metadata() -> list[dict]:
    """Static (per-process) mapping of every ComplianceModule to its
    phase, for GET /api/ontology - lets the frontend build a Phase 2-6
    legend without hardcoding the module->phase relationship itself."""
    seen: dict[int, dict] = {}
    for module, (phase_num, phase_name) in _MODULE_TO_PHASE.items():
        entry = seen.setdefault(
            phase_num, {"phase": phase_num, "name": phase_name, "modules": []}
        )
        entry["modules"].append(module.value)
    return [seen[n] for n in sorted(seen)]
