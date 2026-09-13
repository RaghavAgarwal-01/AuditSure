"""
AuditSure Layer 2 - Phase 5 Pipeline
========================================
Layers Phase 5 (Compliance Obligations: e-invoicing, e-way bill, return
type/frequency, TDS/TCS) on top of Phases 2-4, returning a single
combined ProofObject.
"""

from __future__ import annotations

from datetime import date

from app.models.business_profile import BusinessProfile
from app.engines.einvoice_ewaybill_engine import EInvoicingEWayBillEngine
from app.ontology.ontology_loader import OntologyLoader, get_default_loader
from app.pipelines.phase4_pipeline import run_phase4
from app.models.proof_object import ProofObject
from app.engines.return_obligation_engine import ReturnObligationEngine
from app.engines.tds_tcs_engine import TCSApplicabilityEngine, TDSApplicabilityEngine


def run_phase5(profile: BusinessProfile, onto: OntologyLoader | None = None,
               as_of_date: date | None = None) -> ProofObject:
    onto = onto or get_default_loader()

    proof = run_phase4(profile, onto, as_of_date=as_of_date)

    proof.extend(EInvoicingEWayBillEngine(onto).evaluate(profile))
    proof.extend(ReturnObligationEngine(onto).evaluate(profile))
    proof.extend(TDSApplicabilityEngine(onto).evaluate(profile))
    proof.extend(TCSApplicabilityEngine(onto).evaluate(profile))

    return proof


if __name__ == "__main__":
    from decimal import Decimal

    from app.models.business_profile import OutwardSupplyRecord, RegistrationStatus

    sample = BusinessProfile(
        name="Demo Growing Business",
        state="Karnataka",
        aggregate_turnover=Decimal("30000000"),
        financial_year="2025-26",
        turnover_by_year={"2023-24": Decimal("60000000")},   # crossed Rs 5Cr two years ago
        business_types=["Trader"],
        registration_status=RegistrationStatus.ACTIVE,
        outward_supplies=[
            OutwardSupplyRecord(invoice_number="INV-1", invoice_date=date(2025, 6, 1),
                                 value=Decimal("80000"), supply_type="TaxableSupply",
                                 consignment_value=Decimal("80000")),
        ],
    )
    proof = run_phase5(sample, as_of_date=date(2026, 9, 10))
    print(proof.to_json())
