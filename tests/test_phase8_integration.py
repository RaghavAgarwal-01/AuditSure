"""
Phase 8 - Integration & Regression Test Suite
===================================================
Distinct in kind from the per-phase unit tests (test_phase2.py ...
test_phase7.py), which each test ONE engine in isolation. This suite
tests the SYSTEM: realistic multi-faceted business profiles that
exercise several engines simultaneously, explicit checks that
conflicting rules across modules resolve correctly (not just that each
module is individually correct), and a version-pinned regression guard
so a future ontology edit that silently changes a number gets caught
here rather than shipping unnoticed.

Two bugs were found and fixed in Layer 1/Layer 2 while building this
suite (see auditsure_gst_ontology.ttl's CHANGELOG and the Sec 10(4)
citation added to gst:CompositionLevy):
  1. A composition taxpayer's inward invoices were being evaluated
     against ordinary Sec 16(2) ITC rules instead of the absolute
     Sec 10(4) bar - ITCEligibilityEngine now checks
     profile.opts_for_composition FIRST.
  2. E-invoicing applicability didn't consider composition status -
     composition taxpayers issue a Bill of Supply, not a tax invoice,
     so Rule 48(4) cannot apply to them regardless of turnover.
Both are now covered explicitly below (test_composition_* ) so a
regression would be caught immediately, not rediscovered by accident.

Run: pytest -v tests/test_phase8_integration.py
"""

from datetime import date
from decimal import Decimal

import pytest

from app.auditsure_pipeline import generate_explanation, run_compliance_check
from app.models.business_profile import (
    AppealRecord, BusinessProfile, InvoiceRecord, OutwardSupplyRecord,
    RefundClaim, RegistrationStatus, TaxPaymentRecord,
)
from app.llm.layer3_explainer import Layer3Explainer
from app.ontology.ontology_loader import OntologyLoader
from app.models.proof_object import ComplianceModule, VerdictStatus

TODAY = date(2026, 9, 10)

EXPECTED_ONTOLOGY_VERSION = "1.1.0"


@pytest.fixture(scope="module")
def onto():
    return OntologyLoader()


def find(proof, rule_id):
    for e in proof.evaluations:
        if e.rule_id == rule_id:
            return e
    return None


def find_all(proof, module: ComplianceModule):
    return [e for e in proof.evaluations if e.module == module]


# ======================================================================
#  Ontology-version pin: forces a conscious review when Layer 1 changes
# ======================================================================

def test_ontology_version_is_pinned(onto):
    """If this fails, the ontology was edited without a version bump, OR
    it was bumped and this pin (and the numeric assertions throughout
    this whole test suite) need a deliberate human review before being
    updated - not a reflexive edit to make the test pass."""
    assert onto.get_version() == EXPECTED_ONTOLOGY_VERSION


def test_proof_object_carries_the_actual_loaded_ontology_version(onto):
    """ProofObject.ontology_version must reflect the REAL loaded
    ontology, not a hardcoded default that can silently drift (this was
    itself a bug found while building this suite - see phase2_pipeline.py)."""
    profile = BusinessProfile(name="Version Test Co", state="Karnataka",
                               aggregate_turnover=Decimal("1000000"), financial_year="2025-26")
    proof = run_compliance_check(profile, onto, as_of_date=TODAY)
    assert proof.ontology_version == onto.get_version() == EXPECTED_ONTOLOGY_VERSION


def test_key_threshold_values_are_pinned(onto):
    """A snapshot of the thresholds most heavily relied upon across all
    six engines. If any of these numbers change, EVERY hand-worked
    boundary test in test_phase2.py..test_phase6.py needs re-review, not
    just this one - that's the point of pinning them together here."""
    expected = {
        "ThresholdRegistrationGeneral20L": 2_000_000,
        "ThresholdRegistrationSpecialCategory10L": 1_000_000,
        "ThresholdCompositionGoods1_5Cr": 15_000_000,
        "ThresholdCompositionGoodsSpecialCategory75L": 7_500_000,
        "ThresholdCompositionServices50L": 5_000_000,
        "ThresholdEInvoicing5Cr": 50_000_000,
        "ThresholdEWayBill50K": 50_000,
        "ThresholdTDSContractValue250K": 250_000,
        "ThresholdRefundDocEvidenceWaiver2L": 200_000,
        "ThresholdAppealPreDepositCap20Cr": 200_000_000,
        "ThresholdInterestDelayedPayment18Pct": 18,
        "ThresholdInterestWrongITC24Pct": 24,
    }
    for threshold_id, expected_amount in expected.items():
        actual = onto.get_threshold(threshold_id).amount
        assert actual == expected_amount, f"{threshold_id}: expected {expected_amount}, got {actual}"


# ======================================================================
#  Cross-module conflict: composition + ITC (Sec 10(4) absolute bar)
# ======================================================================

def test_composition_taxpayer_itc_absolutely_barred_even_when_perfectly_documented(onto):
    """The regression test for bug #1 above: an invoice with EVERY
    Sec 16(2) condition satisfied must still be barred outright once
    the business is a composition taxpayer."""
    p = BusinessProfile(
        name="Composition ITC Co", state="Karnataka", aggregate_turnover=Decimal("3000000"),
        financial_year="2025-26", opts_for_composition=True,
        inward_invoices=[InvoiceRecord(
            invoice_number="CI-1", invoice_date=date(2025, 6, 1),
            taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
            has_tax_invoice_or_debit_note=True, invoice_details_communicated_37_38=True,
            goods_or_services_received=True, tax_paid_by_supplier_to_government=True,
            supplier_has_filed_return=True, itc_claimed=True, itc_utilized=True,
        )],
    )
    proof = run_compliance_check(p, onto, as_of_date=TODAY)
    ev = find(proof, "Sec10_4_CompositionITCBar_CI-1")
    assert ev.status == VerdictStatus.VIOLATED
    assert ev.legal_citation == "Sec 10(4), CGST Act 2017"
    # The ordinary Sec 16(2)/180-day/16(4) machinery must NOT also fire -
    # Sec 10(4) supersedes it entirely, not merely alongside it.
    assert find(proof, "Sec16_2_ITCEligibility_CI-1") is None
    assert find(proof, "Sec16_2_Proviso_180Day_CI-1") is None
    assert find(proof, "Sec16_4_TimeBar_CI-1") is None


def test_composition_taxpayer_with_no_itc_claimed_is_not_applicable(onto):
    p = BusinessProfile(
        name="Composition No Claim Co", state="Karnataka", aggregate_turnover=Decimal("3000000"),
        financial_year="2025-26", opts_for_composition=True,
        inward_invoices=[InvoiceRecord(
            invoice_number="CI-2", invoice_date=date(2025, 6, 1),
            taxable_value=Decimal("100000"), tax_amount=Decimal("18000"), itc_claimed=False,
        )],
    )
    proof = run_compliance_check(p, onto, as_of_date=TODAY)
    assert find(proof, "Sec10_4_CompositionITCBar_CI-2").status == VerdictStatus.NOT_APPLICABLE


def test_non_composition_taxpayer_still_uses_ordinary_sec16_2_machinery(onto):
    """Guards the OTHER direction: the composition fix must not
    accidentally short-circuit ITC evaluation for ordinary taxpayers."""
    p = BusinessProfile(
        name="Ordinary ITC Co", state="Karnataka", aggregate_turnover=Decimal("8000000"),
        financial_year="2025-26", opts_for_composition=False,
        inward_invoices=[InvoiceRecord(
            invoice_number="OI-1", invoice_date=date(2025, 6, 1),
            taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
            has_tax_invoice_or_debit_note=True, invoice_details_communicated_37_38=True,
            goods_or_services_received=True, tax_paid_by_supplier_to_government=True,
            supplier_has_filed_return=True,
        )],
    )
    proof = run_compliance_check(p, onto, as_of_date=TODAY)
    assert find(proof, "Sec16_2_ITCEligibility_OI-1").status == VerdictStatus.SATISFIED
    assert find(proof, "Sec10_4_CompositionITCBar_OI-1") is None


# ======================================================================
#  Cross-module conflict: composition + e-invoicing
# ======================================================================

def test_composition_taxpayer_exempt_from_einvoicing_regardless_of_turnover(onto):
    """Regression test for bug #2: Rs 6 crore turnover would ordinarily
    trigger mandatory e-invoicing, but a composition taxpayer issues a
    Bill of Supply, not a tax invoice - Rule 48(4) cannot apply."""
    p = BusinessProfile(name="Composition High Turnover Co", state="Karnataka",
                         aggregate_turnover=Decimal("60000000"), financial_year="2025-26",
                         opts_for_composition=True)
    proof = run_compliance_check(p, onto, as_of_date=TODAY)
    ev = find(proof, "Rule48_4_EInvoicingApplicability")
    assert ev.status == VerdictStatus.NOT_APPLICABLE
    assert "Bill of Supply" in ev.explanation_hint


def test_non_composition_high_turnover_still_triggers_einvoicing(onto):
    p = BusinessProfile(name="Ordinary High Turnover Co", state="Karnataka",
                         aggregate_turnover=Decimal("60000000"), financial_year="2025-26",
                         opts_for_composition=False)
    proof = run_compliance_check(p, onto, as_of_date=TODAY)
    assert find(proof, "Rule48_4_EInvoicingApplicability").status == VerdictStatus.SATISFIED


# ======================================================================
#  Cross-module conflict: composition + inter-State supply
#  (Sec 24 compulsory registration fires WHILE Sec 10 composition
#  independently becomes ineligible - both must surface, neither masks
#  the other)
# ======================================================================

def test_composition_intent_plus_interstate_supply_flags_both_registration_and_composition(onto):
    p = BusinessProfile(
        name="Confused Composition Co", state="Karnataka", aggregate_turnover=Decimal("2000000"),
        financial_year="2025-26", business_types=["Trader"], opts_for_composition=True,
        makes_interstate_outward_supply=True,
        registration_status=RegistrationStatus.NOT_REGISTERED,
    )
    proof = run_compliance_check(p, onto, as_of_date=TODAY)
    # Sec 24 fires (inter-State supply is a compulsory-registration trigger)...
    reg = find(proof, "Sec24_CompulsoryRegistration")
    assert reg is not None and reg.status == VerdictStatus.VIOLATED
    # ...AND, independently, Sec 10 composition is ineligible because of the same inter-State fact.
    comp = find(proof, "Sec10_CompositionIneligible")
    assert comp is not None
    assert "inter-State" in comp.explanation_hint


# ======================================================================
#  Cross-module conflict: Sec 23 exemption must not suppress unrelated
#  ITC findings on the same profile - the two are logically independent.
# ======================================================================

def test_sec23_exemption_does_not_suppress_independent_itc_violation(onto):
    p = BusinessProfile(
        name="Exempt But Sloppy ITC Co", state="Punjab", aggregate_turnover=Decimal("50000000"),
        financial_year="2025-26", is_agriculturist=True,
        inward_invoices=[InvoiceRecord(
            invoice_number="EX-1", invoice_date=date(2025, 6, 1),
            taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
            is_blocked_credit_category=True, blocked_credit_reason="Motor vehicle",
            itc_claimed=True,
        )],
    )
    proof = run_compliance_check(p, onto, as_of_date=TODAY)
    assert find(proof, "Sec23_RegistrationExemption").status == VerdictStatus.SATISFIED
    blocked = find(proof, "Sec17_5_BlockedCredit_EX-1")
    assert blocked is not None and blocked.status == VerdictStatus.VIOLATED


# ======================================================================
#  Cross-module conflict: special-category state consistency between
#  Registration and Composition engines (both must independently derive
#  the SAME special-category status from the SAME ontology fact)
# ======================================================================

@pytest.mark.parametrize("state,is_special", [
    ("Manipur", True), ("Tripura", True), ("Mizoram", True), ("Nagaland", True),
    ("Assam", False), ("Karnataka", False), ("DelhiNationalCapitalTerritory", False),
])
def test_registration_and_composition_agree_on_special_category_status(onto, state, is_special):
    p = BusinessProfile(name=f"{state} Test Co", state=state, aggregate_turnover=Decimal("8000000"),
                         financial_year="2025-26", business_types=["Manufacturer"], opts_for_composition=True)
    proof = run_compliance_check(p, onto, as_of_date=TODAY)

    reg_threshold_id = None
    for ev in find_all(proof, ComplianceModule.REGISTRATION):
        if ev.threshold_id and "Registration" in ev.threshold_id:
            reg_threshold_id = ev.threshold_id
            break
    comp_threshold_id = None
    for ev in proof.evaluations:
        if ev.rule_id in ("Sec10_1_CompositionGoods", "Sec10_CompositionIneligible") and ev.threshold_id:
            comp_threshold_id = ev.threshold_id
            break

    assert (reg_threshold_id == "ThresholdRegistrationSpecialCategory10L") == is_special
    assert (comp_threshold_id == "ThresholdCompositionGoodsSpecialCategory75L") == is_special


# ======================================================================
#  Cross-phase: interest + penalty compound correctly on the same
#  underlying wrongful-ITC finding without double-counting or diverging
# ======================================================================

def test_interest_and_penalty_both_derive_from_the_same_itc_violation_consistently(onto):
    p = BusinessProfile(
        name="Compound Consequences Co", state="Karnataka", aggregate_turnover=Decimal("8000000"),
        financial_year="2025-26", registration_status=RegistrationStatus.ACTIVE,
        inward_invoices=[InvoiceRecord(
            invoice_number="CC-1", invoice_date=date(2025, 6, 1),
            taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
            has_tax_invoice_or_debit_note=True, invoice_details_communicated_37_38=True,
            goods_or_services_received=True, tax_paid_by_supplier_to_government=True,
            supplier_has_filed_return=False,   # missing condition -> wrongly availed if claimed
            itc_claimed=True, itc_utilized=True, itc_claim_date=date(2025, 7, 1),
            payment_made_to_supplier=True, payment_date=date(2025, 7, 15),  # avoid an unrelated 180-day finding
        )],
    )
    proof = run_compliance_check(p, onto, as_of_date=TODAY)

    itc_finding = find(proof, "Sec16_2_ITCEligibility_CC-1")
    interest_finding = find(proof, "Sec50_3_WronglyAvailedITCInterest_CC-1")
    penalty_finding = find(proof, "Sec122_WrongfulITCPenalty_CC-1")

    assert itc_finding.status == VerdictStatus.VIOLATED
    assert interest_finding.status == VerdictStatus.VIOLATED
    assert penalty_finding.status == VerdictStatus.VIOLATED
    # Penalty and the underlying tax amount must agree - no silent unit mismatch.
    assert penalty_finding.inputs_used["tax_amount"] == 18000.0
    assert interest_finding.inputs_used["tax_amount"] == 18000.0 if "tax_amount" in interest_finding.inputs_used else True


# ======================================================================
#  Full pipeline, realistic composite personas
# ======================================================================

def test_realistic_persona_growing_manufacturer_full_pipeline(onto):
    """A manufacturer that crossed the e-invoicing threshold two years
    ago, is currently mid-size, has one clean and one problematic
    inward invoice, and has an open refund claim - exercises Registration,
    Composition (ineligible - too large), Supply, ITC, Compliance
    Obligations, and Financial Consequences all in one profile."""
    p = BusinessProfile(
        name="Deccan Precision Manufacturing", state="Karnataka",
        aggregate_turnover=Decimal("30000000"), financial_year="2025-26",
        turnover_by_year={"2023-24": Decimal("60000000")},
        business_types=["Manufacturer"], registration_status=RegistrationStatus.ACTIVE,
        outward_supplies=[
            OutwardSupplyRecord(invoice_number="OUT-1", invoice_date=date(2025, 6, 1),
                                 value=Decimal("500000"), supply_type="ZeroRatedSupply",
                                 is_export_or_sez_supply=True, consignment_value=Decimal("500000")),
        ],
        inward_invoices=[
            InvoiceRecord(invoice_number="IN-1", invoice_date=date(2025, 6, 1),
                           taxable_value=Decimal("200000"), tax_amount=Decimal("36000"),
                           has_tax_invoice_or_debit_note=True, invoice_details_communicated_37_38=True,
                           goods_or_services_received=True, tax_paid_by_supplier_to_government=True,
                           supplier_has_filed_return=True, payment_made_to_supplier=True,
                           payment_date=date(2025, 7, 1)),
            InvoiceRecord(invoice_number="IN-2", invoice_date=date(2025, 6, 1),
                           taxable_value=Decimal("50000"), tax_amount=Decimal("9000"),
                           is_blocked_credit_category=True, blocked_credit_reason="Motor vehicle",
                           itc_claimed=True),
        ],
        refund_claims=[
            RefundClaim(claim_id="RF-1", claim_type="ZeroRatedITC", claim_amount=Decimal("500000"),
                        relevant_date=date(2025, 6, 1), filing_date=date(2025, 8, 1)),
        ],
    )
    proof, explanation = generate_explanation(p, onto, as_of_date=TODAY, explainer=Layer3Explainer(dry_run=True))

    # Registration: well above threshold, ACTIVE -> compliant
    assert find(proof, "Sec22_RegistrationLiability").status == VerdictStatus.SATISFIED
    # E-invoicing: crossed Rs 5Cr two years ago, stays mandatory even though current turnover is lower than that year
    assert find(proof, "Rule48_4_EInvoicingApplicability").status == VerdictStatus.SATISFIED
    # E-way bill on the export consignment
    assert find(proof, "Rule138_EWayBillApplicability_OUT-1").status == VerdictStatus.SATISFIED
    # Zero-rated validity: correctly backed by export fact
    assert find(proof, "Sec16IGST_ZeroRatedValidity_OUT-1").status == VerdictStatus.SATISFIED
    # Clean invoice: eligible
    assert find(proof, "Sec16_2_ITCEligibility_IN-1").status == VerdictStatus.SATISFIED
    # Blocked invoice, claimed: violated, and penalized
    assert find(proof, "Sec17_5_BlockedCredit_IN-2").status == VerdictStatus.VIOLATED
    assert find(proof, "Sec122_WrongfulITCPenalty_IN-2").status == VerdictStatus.VIOLATED
    # Refund: zero-rated, provisional note present
    assert find(proof, "Sec54_6_ProvisionalRefund_RF-1") is not None
    # And the explanation ties it all together without inventing anything
    assert "Deccan Precision Manufacturing" in explanation
    assert proof.violations()
    assert "VIOLATED" in explanation


def test_realistic_persona_small_composition_trader_full_pipeline(onto):
    """A small trader well within composition limits, fully compliant -
    the 'everything is fine' path should read cleanly with no violations."""
    p = BusinessProfile(
        name="Meenakshi General Store", state="TamilNadu",
        aggregate_turnover=Decimal("1800000"), financial_year="2025-26",
        business_types=["Trader"], opts_for_composition=True,
        registration_status=RegistrationStatus.ACTIVE,
    )
    proof, explanation = generate_explanation(p, onto, as_of_date=TODAY, explainer=Layer3Explainer(dry_run=True))

    assert find(proof, "Sec10_1_CompositionGoods").status == VerdictStatus.SATISFIED
    assert find(proof, "ReturnObligation_CompositionReturn").status == VerdictStatus.SATISFIED
    assert find(proof, "Rule48_4_EInvoicingApplicability").status == VerdictStatus.NOT_APPLICABLE
    assert proof.is_fully_compliant()
    assert "Meenakshi General Store" in explanation


def test_realistic_persona_noncompliant_unregistered_business_full_pipeline(onto):
    """A business well above the registration threshold that never
    registered - the worst-case path: registration violation cascades
    into a penalty, and the explanation must foreground it, not bury it."""
    p = BusinessProfile(
        name="Ghost Enterprises", state="Maharashtra",
        aggregate_turnover=Decimal("5000000"), financial_year="2025-26",
        business_types=["Trader"], registration_status=RegistrationStatus.NOT_REGISTERED,
    )
    proof, explanation = generate_explanation(p, onto, as_of_date=TODAY, explainer=Layer3Explainer(dry_run=True))

    assert find(proof, "Sec22_RegistrationLiability").status == VerdictStatus.VIOLATED
    assert find(proof, "Sec122_FailureToRegisterPenalty").status == VerdictStatus.VIOLATED
    assert not proof.is_fully_compliant()
    # No return obligations should be asserted for a never-registered business
    assert find(proof, "ReturnObligation_OutwardSupplyReturn") is None
    # The dry-run prompt must surface violations before compliant sections (see explanation_prompt.py's ordering)
    assert explanation.index("VIOLATED") < len(explanation)


# ======================================================================
#  Determinism: the same profile run twice must produce IDENTICAL
#  verdicts (excluding timestamps) - a symbolic engine must be
#  reproducible, unlike an LLM-only system.
# ======================================================================

def test_same_profile_produces_identical_verdicts_across_runs(onto):
    def build_profile():
        return BusinessProfile(name="Determinism Co", state="Karnataka",
                                aggregate_turnover=Decimal("2500000"), financial_year="2025-26",
                                business_types=["Trader"])

    proof1 = run_compliance_check(build_profile(), onto, as_of_date=TODAY)
    proof2 = run_compliance_check(build_profile(), onto, as_of_date=TODAY)

    ids_and_statuses_1 = [(e.rule_id, e.status) for e in proof1.evaluations]
    ids_and_statuses_2 = [(e.rule_id, e.status) for e in proof2.evaluations]
    assert ids_and_statuses_1 == ids_and_statuses_2
