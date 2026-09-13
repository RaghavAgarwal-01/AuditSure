"""
AuditSure Layer 2 - Phase 4 Pipeline
========================================
Layers Phase 4 (Input Tax Credit) on top of Phases 2-3 against one
BusinessProfile, returning a single combined ProofObject.
"""

from __future__ import annotations

from datetime import date

from app.models.business_profile import BusinessProfile
from app.engines.itc_engine import ITCEligibilityEngine
from app.ontology.ontology_loader import OntologyLoader, get_default_loader
from app.pipelines.phase3_pipeline import run_phase3
from app.models.proof_object import ProofObject


def run_phase4(profile: BusinessProfile, onto: OntologyLoader | None = None,
               as_of_date: date | None = None) -> ProofObject:
    onto = onto or get_default_loader()

    proof = run_phase3(profile, onto)   # Sec 22/23/24 + Sec 10 + supply classification + levy mechanism

    proof.extend(ITCEligibilityEngine(onto, as_of_date=as_of_date).evaluate(profile))

    return proof


if __name__ == "__main__":
    from decimal import Decimal

    from app.models.business_profile import InvoiceRecord

    sample = BusinessProfile(
        name="Demo Manufacturer",
        state="Karnataka",
        aggregate_turnover=Decimal("30000000"),
        financial_year="2025-26",
        business_types=["Manufacturer"],
        inward_invoices=[
            InvoiceRecord(
                invoice_number="PINV-1", invoice_date=date(2025, 6, 1),
                taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                has_tax_invoice_or_debit_note=True, invoice_details_communicated_37_38=True,
                goods_or_services_received=True, tax_paid_by_supplier_to_government=True,
                supplier_has_filed_return=True, payment_made_to_supplier=True,
                payment_date=date(2025, 8, 1),
            ),
            InvoiceRecord(
                invoice_number="PINV-2", invoice_date=date(2025, 4, 1),
                taxable_value=Decimal("50000"), tax_amount=Decimal("9000"),
                is_blocked_credit_category=True, blocked_credit_reason="Motor vehicle (seating <=13) - Sec 17(5)(a)",
                itc_claimed=True,
            ),
        ],
    )
    proof = run_phase4(sample, as_of_date=date(2026, 9, 10))
    print(proof.to_json())
