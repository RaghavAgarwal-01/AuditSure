"""
AuditSure Layer 2 - Phase 3 Pipeline
========================================
Layers Phase 3 (Supply Classification + Levy Mechanism) on top of
Phase 2 (Registration + Composition) against one BusinessProfile,
returning a single combined ProofObject. Phase 4+ will continue this
same layering pattern (import the previous phase's run_* function,
extend the same ProofObject, return it).
"""

from __future__ import annotations

from business_profile import BusinessProfile
from levy_mechanism_engine import LevyMechanismEngine
from ontology_loader import OntologyLoader, get_default_loader
from phase2_pipeline import run_phase2
from proof_object import ProofObject
from supply_classification_engine import SupplyClassificationEngine


def run_phase3(profile: BusinessProfile, onto: OntologyLoader | None = None) -> ProofObject:
    onto = onto or get_default_loader()

    proof = run_phase2(profile, onto)   # Sec 22/23/24 + Sec 10 (also validates the profile)

    proof.extend(SupplyClassificationEngine().evaluate(profile))
    proof.extend(LevyMechanismEngine().evaluate(profile))

    return proof


if __name__ == "__main__":
    from datetime import date
    from decimal import Decimal

    from business_profile import OutwardSupplyRecord, RegistrationStatus

    sample = BusinessProfile(
        name="Demo Exporter",
        state="Karnataka",
        aggregate_turnover=Decimal("30000000"),
        financial_year="2025-26",
        business_types=["Trader"],
        registration_status=RegistrationStatus.ACTIVE,
        outward_supplies=[
            OutwardSupplyRecord(
                invoice_number="INV-001", invoice_date=date(2025, 6, 15),
                value=Decimal("500000"), supply_type="ZeroRatedSupply",
                is_export_or_sez_supply=True,
            ),
            OutwardSupplyRecord(
                invoice_number="INV-002", invoice_date=date(2025, 7, 1),
                value=Decimal("200000"), supply_type="ZeroRatedSupply",
                is_export_or_sez_supply=False,   # deliberately invalid, to demonstrate the check
            ),
            OutwardSupplyRecord(
                invoice_number="INV-003", invoice_date=date(2025, 7, 10),
                value=Decimal("100000"), supply_type="TaxableSupply",
                is_interstate=True, recipient_state="Maharashtra",
            ),
        ],
    )
    proof = run_phase3(sample)
    print(proof.to_json())
