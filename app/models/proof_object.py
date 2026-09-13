"""
AuditSure Layer 2 - Proof Object Schema
==========================================
The output contract. Every constraint module (Phases 2-6) appends
RuleEvaluation entries to a shared ProofObject. Layer 3 reads the
finished ProofObject and turns it into a natural-language explanation -
it should never need to touch Z3, rdflib, or the ontology directly.

Design goals:
  1. Every verdict traces back to a legal citation (no unexplained "no").
  2. Every verdict shows the actual numbers compared (transparency /
     auditability - the whole point of a symbolic layer over an LLM).
  3. Machine-checkable (status is an enum, not free text) AND
     human-explainable (each entry carries enough detail for Layer 3
     to write a sentence without guessing).
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional


class VerdictStatus(str, Enum):
    SATISFIED = "SATISFIED"          # constraint holds / obligation met / eligible
    VIOLATED = "VIOLATED"            # constraint fails / obligation breached / not eligible
    NOT_APPLICABLE = "NOT_APPLICABLE"  # rule doesn't apply to this profile at all
    INDETERMINATE = "INDETERMINATE"  # insufficient data in the BusinessProfile to decide


class ComplianceModule(str, Enum):
    """One entry per Phase 2-6 engine; used to group/filter a ProofObject."""
    REGISTRATION = "Registration"
    COMPOSITION = "Composition"
    SUPPLY_CLASSIFICATION = "SupplyClassification"
    INPUT_TAX_CREDIT = "InputTaxCredit"
    COMPLIANCE_OBLIGATIONS = "ComplianceObligations"   # e-invoice, e-way bill, returns, TDS/TCS
    FINANCIAL_CONSEQUENCES = "FinancialConsequences"   # interest, penalty, refund, appeal


@dataclass
class RuleEvaluation:
    """One fired constraint - the atomic unit of the proof."""
    rule_id: str                      # e.g. "Sec22_RegistrationLiability"
    module: ComplianceModule
    status: VerdictStatus
    legal_citation: str                # e.g. "Sec 22(1), CGST Act 2017"
    section_number: Optional[str]      # e.g. "22" - links back to ontology gst:Section
    description: str                   # short human summary of WHAT was checked
    inputs_used: dict[str, Any] = field(default_factory=dict)      # {"aggregate_turnover": 2500000, "state": "Bihar"}
    computed_value: Optional[float] = None      # e.g. the applicant's turnover
    threshold_value: Optional[float] = None     # e.g. 2000000 (from ontology gst:Threshold)
    threshold_id: Optional[str] = None          # e.g. "ThresholdRegistrationGeneral20L"
    explanation_hint: str = ""         # one plain-English sentence template for Layer 3, e.g.
                                        # "{name}'s turnover of Rs {computed_value} exceeds the
                                        #  Rs {threshold_value} threshold under {legal_citation}."
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["module"] = self.module.value
        d["status"] = self.status.value
        d["evaluated_at"] = self.evaluated_at.isoformat()
        d["inputs_used"] = _json_safe(self.inputs_used)
        return d


@dataclass
class ProofObject:
    """The complete, aggregated evaluation for one BusinessProfile.
    This is what gets serialized to JSON and handed to Layer 3."""
    business_name: str
    financial_year: str
    evaluations: list[RuleEvaluation] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ontology_version: str = "1.0.0"

    # -- Construction ----------------------------------------------------
    def add(self, evaluation: RuleEvaluation) -> None:
        self.evaluations.append(evaluation)

    def extend(self, evaluations: list[RuleEvaluation]) -> None:
        self.evaluations.extend(evaluations)

    # -- Query helpers (what Layer 3 / a UI will actually use) -------------
    def by_module(self, module: ComplianceModule) -> list[RuleEvaluation]:
        return [e for e in self.evaluations if e.module == module]

    def by_status(self, status: VerdictStatus) -> list[RuleEvaluation]:
        return [e for e in self.evaluations if e.status == status]

    def violations(self) -> list[RuleEvaluation]:
        return self.by_status(VerdictStatus.VIOLATED)

    def indeterminates(self) -> list[RuleEvaluation]:
        """Non-empty result means the BusinessProfile was underspecified
        for at least one rule - a UI should prompt for more input."""
        return self.by_status(VerdictStatus.INDETERMINATE)

    def is_fully_compliant(self) -> bool:
        return len(self.violations()) == 0 and len(self.indeterminates()) == 0

    def summary_counts(self) -> dict[str, int]:
        counts = {s.value: 0 for s in VerdictStatus}
        for e in self.evaluations:
            counts[e.status.value] += 1
        return counts

    # -- Serialization -----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "business_name": self.business_name,
            "financial_year": self.financial_year,
            "generated_at": self.generated_at.isoformat(),
            "ontology_version": self.ontology_version,
            "summary": self.summary_counts(),
            "evaluations": [e.to_dict() for e in self.evaluations],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            f.write(self.to_json())


def _json_safe(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj
