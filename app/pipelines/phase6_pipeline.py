"""
AuditSure Layer 2 - Phase 6 Pipeline
========================================
Layers Phase 6 (Financial Consequences: interest, penalty, refund,
appeal pre-deposit) on top of Phases 2-5, returning a single combined
ProofObject. This is the last of the core compliance-domain phases -
Phase 7 assembles everything into the final Layer 2 -> Layer 3 bridge.

Note the changed signature for InterestEngine/PenaltyEngine: they take
the ALREADY-BUILT ProofObject from Phases 2-5 as an explicit argument
(not just the BusinessProfile), since their whole point is to consume
prior phases' verdicts rather than re-deriving them. RefundEngine and
AppealEngine, by contrast, only need BusinessProfile - Sec 54/107 don't
depend on any other module's findings.
"""

from __future__ import annotations

from datetime import date

from app.engines.appeal_engine import AppealEngine
from app.models.business_profile import BusinessProfile
from app.engines.interest_engine import InterestEngine
from app.ontology.ontology_loader import OntologyLoader, get_default_loader
from app.engines.penalty_engine import PenaltyEngine
from app.pipelines.phase5_pipeline import run_phase5
from app.models.proof_object import ProofObject
from app.engines.refund_engine import RefundEngine


def run_phase6(profile: BusinessProfile, onto: OntologyLoader | None = None,
               as_of_date: date | None = None) -> ProofObject:
    onto = onto or get_default_loader()

    proof = run_phase5(profile, onto, as_of_date=as_of_date)   # Phases 2-5

    proof.extend(InterestEngine(onto, as_of_date=as_of_date).evaluate(profile, proof))
    proof.extend(PenaltyEngine(onto).evaluate(profile, proof))
    proof.extend(RefundEngine(onto).evaluate(profile))
    proof.extend(AppealEngine(onto).evaluate(profile))

    return proof


if __name__ == "__main__":
    from decimal import Decimal

    from app.models.business_profile import InvoiceRecord, RegistrationStatus

    sample = BusinessProfile(
        name="Demo Business with Issues",
        state="Karnataka",
        aggregate_turnover=Decimal("8000000"),
        financial_year="2025-26",
        business_types=["Trader"],
        registration_status=RegistrationStatus.ACTIVE,
        inward_invoices=[
            InvoiceRecord(
                invoice_number="WI-1", invoice_date=date(2025, 6, 1),
                taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                has_tax_invoice_or_debit_note=True, invoice_details_communicated_37_38=True,
                goods_or_services_received=True, tax_paid_by_supplier_to_government=True,
                supplier_has_filed_return=False,
                itc_claimed=True, itc_utilized=True, itc_claim_date=date(2025, 7, 1),
            ),
        ],
    )
    proof = run_phase6(sample, as_of_date=date(2026, 9, 10))
    print(proof.to_json())
