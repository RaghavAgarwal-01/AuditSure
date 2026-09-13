"""
Phase 6 test suite - Interest (Sec 50), Penalty (Sec 122), Refund (Sec 54),
Appeal pre-deposit (Sec 107).

Run: pytest -v tests/test_phase6.py
"""

from datetime import date
from decimal import Decimal

import pytest

from app.engines.appeal_engine import AppealEngine
from app.models.business_profile import (
    AppealRecord, BusinessProfile, InvoiceRecord, RefundClaim,
    RegistrationStatus, TaxPaymentRecord,
)
from app.engines.interest_engine import InterestEngine
from app.ontology.ontology_loader import OntologyLoader
from app.engines.penalty_engine import PenaltyEngine
from app.pipelines.phase6_pipeline import run_phase6
from app.models.proof_object import ProofObject, VerdictStatus
from app.engines.refund_engine import RefundEngine

TODAY = date(2026, 9, 10)


@pytest.fixture(scope="module")
def onto():
    return OntologyLoader()


def find(evaluations, rule_id):
    for e in evaluations:
        if e.rule_id == rule_id:
            return e
    return None


def base_profile(**overrides) -> BusinessProfile:
    defaults = dict(
        name="FinTest Co", state="Karnataka", aggregate_turnover=Decimal("5000000"),
        financial_year="2025-26", registration_status=RegistrationStatus.ACTIVE,
    )
    defaults.update(overrides)
    return BusinessProfile(**defaults)


def eligible_invoice(**overrides) -> InvoiceRecord:
    defaults = dict(
        invoice_number="I1", invoice_date=date(2025, 6, 1),
        taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
        has_tax_invoice_or_debit_note=True, invoice_details_communicated_37_38=True,
        goods_or_services_received=True, tax_paid_by_supplier_to_government=True,
        supplier_has_filed_return=True,
    )
    defaults.update(overrides)
    return InvoiceRecord(**defaults)


# ======================================================================
#  Interest - Sec 50(1) delayed payment
# ======================================================================

def test_paid_after_due_date_attracts_18pct_interest(onto):
    p = base_profile(tax_payment_records=[
        TaxPaymentRecord(return_period="2025-06", due_date=date(2025, 7, 20),
                          tax_liability=Decimal("100000"), amount_paid_via_cash_ledger=Decimal("60000"),
                          payment_date=date(2025, 8, 15))
    ])
    result = InterestEngine(onto, as_of_date=TODAY).evaluate(p, ProofObject(business_name=p.name, financial_year=p.financial_year))
    ev = find(result, "Sec50_1_DelayedPaymentInterest_2025-06")
    assert ev.status == VerdictStatus.VIOLATED
    assert ev.inputs_used["days_late"] == 26


def test_paid_on_due_date_no_interest(onto):
    p = base_profile(tax_payment_records=[
        TaxPaymentRecord(return_period="2025-06", due_date=date(2025, 7, 20),
                          tax_liability=Decimal("100000"), amount_paid_via_cash_ledger=Decimal("60000"),
                          payment_date=date(2025, 7, 20))
    ])
    result = InterestEngine(onto, as_of_date=TODAY).evaluate(p, ProofObject(business_name=p.name, financial_year=p.financial_year))
    assert find(result, "Sec50_1_DelayedPaymentInterest_2025-06") is None


def test_not_yet_paid_no_finding(onto):
    p = base_profile(tax_payment_records=[
        TaxPaymentRecord(return_period="2025-06", due_date=date(2025, 7, 20),
                          tax_liability=Decimal("100000"), amount_paid_via_cash_ledger=Decimal("60000"),
                          payment_date=None)
    ])
    result = InterestEngine(onto, as_of_date=TODAY).evaluate(p, ProofObject(business_name=p.name, financial_year=p.financial_year))
    assert find(result, "Sec50_1_DelayedPaymentInterest_2025-06") is None


def test_interest_computed_on_cash_ledger_amount_not_full_liability(onto):
    """Rs 100,000 total liability but only Rs 60,000 paid via cash ledger
    (rest offset by ITC) - interest principal must be Rs 60,000, not
    Rs 100,000, per the post-2021 Sec 50(1) amendment."""
    p = base_profile(tax_payment_records=[
        TaxPaymentRecord(return_period="2025-06", due_date=date(2025, 7, 20),
                          tax_liability=Decimal("100000"), amount_paid_via_cash_ledger=Decimal("60000"),
                          payment_date=date(2025, 8, 19))  # 30 days late
    ])
    result = InterestEngine(onto, as_of_date=TODAY).evaluate(p, ProofObject(business_name=p.name, financial_year=p.financial_year))
    ev = find(result, "Sec50_1_DelayedPaymentInterest_2025-06")
    assert ev.computed_value == 60000.0
    expected_interest = 60000.0 * 0.18 * (30 / 365)
    assert "60,000.00" in ev.explanation_hint


# ======================================================================
#  Interest - Sec 50(3) wrongly availed AND utilised ITC (cross-phase)
# ======================================================================

def test_wrongly_availed_and_utilised_itc_attracts_24pct(onto):
    p = base_profile(inward_invoices=[
        eligible_invoice(supplier_has_filed_return=False, itc_claimed=True, itc_utilized=True,
                          itc_claim_date=date(2025, 7, 1))
    ])
    from app.pipelines.phase5_pipeline import run_phase5
    prior_proof = run_phase5(p, onto, as_of_date=TODAY)
    result = InterestEngine(onto, as_of_date=TODAY).evaluate(p, prior_proof)
    ev = find(result, "Sec50_3_WronglyAvailedITCInterest_I1")
    assert ev is not None
    assert ev.status == VerdictStatus.VIOLATED
    assert ev.legal_citation.startswith("Sec 50(3)")


def test_wrongly_availed_but_not_utilised_attracts_no_interest(onto):
    """Sec 50(3) requires BOTH availed AND utilised - availed alone
    (itc_utilized=False) must not attract interest."""
    from app.pipelines.phase5_pipeline import run_phase5
    p = base_profile(inward_invoices=[
        eligible_invoice(supplier_has_filed_return=False, itc_claimed=True, itc_utilized=False,
                          itc_claim_date=date(2025, 7, 1))
    ])
    prior_proof = run_phase5(p, onto, as_of_date=TODAY)
    result = InterestEngine(onto, as_of_date=TODAY).evaluate(p, prior_proof)
    assert find(result, "Sec50_3_WronglyAvailedITCInterest_I1") is None


def test_correctly_availed_itc_attracts_no_interest(onto):
    from app.pipelines.phase5_pipeline import run_phase5
    p = base_profile(inward_invoices=[
        eligible_invoice(itc_claimed=True, itc_utilized=True, itc_claim_date=date(2025, 7, 1),
                          payment_made_to_supplier=True, payment_date=date(2025, 7, 15))
    ])
    prior_proof = run_phase5(p, onto, as_of_date=TODAY)
    result = InterestEngine(onto, as_of_date=TODAY).evaluate(p, prior_proof)
    assert find(result, "Sec50_3_WronglyAvailedITCInterest_I1") is None


# ======================================================================
#  Penalty - Sec 122(1) wrongful ITC + failure to register (cross-phase)
# ======================================================================

def test_wrongful_itc_penalty_is_higher_of_10000_or_tax_amount(onto):
    from app.pipelines.phase5_pipeline import run_phase5
    p = base_profile(inward_invoices=[
        eligible_invoice(tax_amount=Decimal("18000"), supplier_has_filed_return=False,
                          itc_claimed=True, itc_utilized=True, itc_claim_date=date(2025, 7, 1))
    ])
    prior_proof = run_phase5(p, onto, as_of_date=TODAY)
    result = PenaltyEngine(onto).evaluate(p, prior_proof)
    ev = find(result, "Sec122_WrongfulITCPenalty_I1")
    assert ev.status == VerdictStatus.VIOLATED
    assert ev.computed_value == 18000.0   # tax amount (18000) > floor (10000)


def test_wrongful_itc_penalty_floor_applies_for_small_amounts(onto):
    """Rs 2,000 wrongly availed - penalty must be the Rs 10,000 FLOOR,
    not the smaller tax amount."""
    from app.pipelines.phase5_pipeline import run_phase5
    p = base_profile(inward_invoices=[
        eligible_invoice(tax_amount=Decimal("2000"), supplier_has_filed_return=False,
                          itc_claimed=True, itc_utilized=True, itc_claim_date=date(2025, 7, 1))
    ])
    prior_proof = run_phase5(p, onto, as_of_date=TODAY)
    result = PenaltyEngine(onto).evaluate(p, prior_proof)
    ev = find(result, "Sec122_WrongfulITCPenalty_I1")
    assert ev.computed_value == 10000.0


def test_blocked_credit_claimed_also_triggers_wrongful_itc_penalty(onto):
    from app.pipelines.phase5_pipeline import run_phase5
    p = base_profile(inward_invoices=[
        InvoiceRecord(invoice_number="BLK-1", invoice_date=date(2025, 6, 1),
                       taxable_value=Decimal("50000"), tax_amount=Decimal("9000"),
                       is_blocked_credit_category=True, itc_claimed=True, itc_utilized=True,
                       itc_claim_date=date(2025, 7, 1))
    ])
    prior_proof = run_phase5(p, onto, as_of_date=TODAY)
    result = PenaltyEngine(onto).evaluate(p, prior_proof)
    ev = find(result, "Sec122_WrongfulITCPenalty_BLK-1")
    assert ev is not None
    assert ev.computed_value == 10000.0   # tax amount 9000 < floor 10000


def test_no_violations_means_no_penalties(onto):
    from app.pipelines.phase5_pipeline import run_phase5
    p = base_profile(inward_invoices=[eligible_invoice()])
    prior_proof = run_phase5(p, onto, as_of_date=TODAY)
    result = PenaltyEngine(onto).evaluate(p, prior_proof)
    assert result == []


def test_failure_to_register_triggers_penalty(onto):
    from app.pipelines.phase5_pipeline import run_phase5
    p = base_profile(registration_status=RegistrationStatus.NOT_REGISTERED,
                      aggregate_turnover=Decimal("2500000"))   # above Rs 20L Karnataka threshold
    prior_proof = run_phase5(p, onto, as_of_date=TODAY)
    result = PenaltyEngine(onto).evaluate(p, prior_proof)
    ev = find(result, "Sec122_FailureToRegisterPenalty")
    assert ev is not None
    assert ev.status == VerdictStatus.VIOLATED


def test_registered_business_no_failure_to_register_penalty(onto):
    from app.pipelines.phase5_pipeline import run_phase5
    p = base_profile(registration_status=RegistrationStatus.ACTIVE, aggregate_turnover=Decimal("2500000"))
    prior_proof = run_phase5(p, onto, as_of_date=TODAY)
    result = PenaltyEngine(onto).evaluate(p, prior_proof)
    assert find(result, "Sec122_FailureToRegisterPenalty") is None


# ======================================================================
#  Refund - Sec 54
# ======================================================================

def test_refund_within_2_years_satisfied(onto):
    p = base_profile(refund_claims=[
        RefundClaim(claim_id="RF-1", claim_type="ExcessPayment", claim_amount=Decimal("100000"),
                    relevant_date=date(2024, 6, 1), filing_date=date(2026, 5, 1))
    ])
    result = RefundEngine(onto).evaluate(p)
    assert find(result, "Sec54_1_LimitationPeriod_RF-1").status == VerdictStatus.SATISFIED


def test_refund_exactly_at_2_year_deadline_satisfied(onto):
    p = base_profile(refund_claims=[
        RefundClaim(claim_id="RF-2", claim_type="ExcessPayment", claim_amount=Decimal("100000"),
                    relevant_date=date(2024, 6, 1), filing_date=date(2026, 6, 1))
    ])
    result = RefundEngine(onto).evaluate(p)
    assert find(result, "Sec54_1_LimitationPeriod_RF-2").status == VerdictStatus.SATISFIED


def test_refund_after_2_years_time_barred(onto):
    p = base_profile(refund_claims=[
        RefundClaim(claim_id="RF-3", claim_type="ExcessPayment", claim_amount=Decimal("100000"),
                    relevant_date=date(2024, 6, 1), filing_date=date(2026, 6, 2))
    ])
    result = RefundEngine(onto).evaluate(p)
    assert find(result, "Sec54_1_LimitationPeriod_RF-3").status == VerdictStatus.VIOLATED


def test_refund_missing_filing_date_is_indeterminate(onto):
    p = base_profile(refund_claims=[
        RefundClaim(claim_id="RF-4", claim_type="ExcessPayment", claim_amount=Decimal("100000"),
                    relevant_date=date(2024, 6, 1), filing_date=None)
    ])
    result = RefundEngine(onto).evaluate(p)
    assert find(result, "Sec54_1_LimitationPeriod_RF-4").status == VerdictStatus.INDETERMINATE


def test_refund_below_2_lakh_waives_documentary_evidence(onto):
    p = base_profile(refund_claims=[
        RefundClaim(claim_id="RF-5", claim_type="ExcessPayment", claim_amount=Decimal("150000"),
                    relevant_date=date(2025, 6, 1), filing_date=date(2025, 8, 1))
    ])
    result = RefundEngine(onto).evaluate(p)
    assert find(result, "Sec54_4_DocEvidenceWaiver_RF-5").status == VerdictStatus.SATISFIED


def test_refund_exactly_at_2_lakh_waives_documentary_evidence(onto):
    p = base_profile(refund_claims=[
        RefundClaim(claim_id="RF-6", claim_type="ExcessPayment", claim_amount=Decimal("200000"),
                    relevant_date=date(2025, 6, 1), filing_date=date(2025, 8, 1))
    ])
    result = RefundEngine(onto).evaluate(p)
    assert find(result, "Sec54_4_DocEvidenceWaiver_RF-6").status == VerdictStatus.SATISFIED


def test_refund_above_2_lakh_requires_documentary_evidence(onto):
    p = base_profile(refund_claims=[
        RefundClaim(claim_id="RF-7", claim_type="ExcessPayment", claim_amount=Decimal("200001"),
                    relevant_date=date(2025, 6, 1), filing_date=date(2025, 8, 1))
    ])
    result = RefundEngine(onto).evaluate(p)
    assert find(result, "Sec54_4_DocEvidenceWaiver_RF-7").status == VerdictStatus.INDETERMINATE


def test_zero_rated_claim_gets_provisional_refund_note(onto):
    p = base_profile(refund_claims=[
        RefundClaim(claim_id="RF-8", claim_type="ZeroRatedITC", claim_amount=Decimal("500000"),
                    relevant_date=date(2025, 6, 1), filing_date=date(2025, 8, 1))
    ])
    result = RefundEngine(onto).evaluate(p)
    ev = find(result, "Sec54_6_ProvisionalRefund_RF-8")
    assert ev is not None
    assert ev.computed_value == 450000.0   # 90% of 500000


def test_non_zero_rated_claim_gets_no_provisional_refund_note(onto):
    p = base_profile(refund_claims=[
        RefundClaim(claim_id="RF-9", claim_type="InvertedDuty", claim_amount=Decimal("500000"),
                    relevant_date=date(2025, 6, 1), filing_date=date(2025, 8, 1))
    ])
    result = RefundEngine(onto).evaluate(p)
    assert find(result, "Sec54_6_ProvisionalRefund_RF-9") is None


# ======================================================================
#  Appeal - Sec 107
# ======================================================================

def test_appeal_within_3_months_satisfied(onto):
    p = base_profile(appeal_records=[
        AppealRecord(appeal_id="AP-1", order_communication_date=date(2026, 1, 1),
                     admitted_amount=Decimal("50000"), disputed_tax_amount=Decimal("1000000"),
                     appeal_filed_date=date(2026, 3, 1))
    ])
    result = AppealEngine(onto).evaluate(p)
    assert find(result, "Sec107_1_AppealLimitation_AP-1").status == VerdictStatus.SATISFIED


def test_appeal_exactly_at_3_months_satisfied(onto):
    p = base_profile(appeal_records=[
        AppealRecord(appeal_id="AP-2", order_communication_date=date(2026, 1, 1),
                     admitted_amount=Decimal("50000"), disputed_tax_amount=Decimal("1000000"),
                     appeal_filed_date=date(2026, 4, 1))
    ])
    result = AppealEngine(onto).evaluate(p)
    assert find(result, "Sec107_1_AppealLimitation_AP-2").status == VerdictStatus.SATISFIED


def test_appeal_after_3_months_within_condonable_window_indeterminate(onto):
    p = base_profile(appeal_records=[
        AppealRecord(appeal_id="AP-3", order_communication_date=date(2026, 1, 1),
                     admitted_amount=Decimal("50000"), disputed_tax_amount=Decimal("1000000"),
                     appeal_filed_date=date(2026, 4, 20))
    ])
    result = AppealEngine(onto).evaluate(p)
    assert find(result, "Sec107_1_AppealLimitation_AP-3").status == VerdictStatus.INDETERMINATE


def test_appeal_after_condonable_window_time_barred(onto):
    p = base_profile(appeal_records=[
        AppealRecord(appeal_id="AP-4", order_communication_date=date(2026, 1, 1),
                     admitted_amount=Decimal("50000"), disputed_tax_amount=Decimal("1000000"),
                     appeal_filed_date=date(2026, 6, 1))
    ])
    result = AppealEngine(onto).evaluate(p)
    assert find(result, "Sec107_1_AppealLimitation_AP-4").status == VerdictStatus.VIOLATED


def test_pre_deposit_calculation_under_cap(onto):
    """Rs 50,000 admitted + 10% of Rs 30,00,000 disputed = Rs 50,000 + Rs 3,00,000 = Rs 3,50,000."""
    p = base_profile(appeal_records=[
        AppealRecord(appeal_id="AP-5", order_communication_date=date(2026, 1, 1),
                     admitted_amount=Decimal("50000"), disputed_tax_amount=Decimal("3000000"),
                     appeal_filed_date=date(2026, 2, 1))
    ])
    result = AppealEngine(onto).evaluate(p)
    ev = find(result, "Sec107_6_PreDepositCalculation_AP-5")
    assert ev.computed_value == 350000.0
    assert ev.inputs_used["cap_applied"] is False


def test_pre_deposit_calculation_hits_20cr_cap(onto):
    """10% of a Rs 500 crore disputed amount would be Rs 50 crore - must
    be capped at Rs 20 crore."""
    p = base_profile(appeal_records=[
        AppealRecord(appeal_id="AP-6", order_communication_date=date(2026, 1, 1),
                     admitted_amount=Decimal("1000000"), disputed_tax_amount=Decimal("5000000000"))
    ])
    result = AppealEngine(onto).evaluate(p)
    ev = find(result, "Sec107_6_PreDepositCalculation_AP-6")
    assert ev.inputs_used["cap_applied"] is True
    assert ev.computed_value == 1000000.0 + 200000000.0   # admitted + Rs 20 crore cap


# ======================================================================
#  Full pipeline integration
# ======================================================================

def test_full_pipeline_produces_all_financial_consequence_findings(onto):
    p = base_profile(
        inward_invoices=[eligible_invoice(supplier_has_filed_return=False, itc_claimed=True,
                                            itc_utilized=True, itc_claim_date=date(2025, 7, 1))],
        refund_claims=[RefundClaim(claim_id="RF-X", claim_type="ZeroRatedITC", claim_amount=Decimal("100000"),
                                    relevant_date=date(2025, 6, 1), filing_date=date(2025, 8, 1))],
        appeal_records=[AppealRecord(appeal_id="AP-X", order_communication_date=date(2026, 1, 1),
                                      admitted_amount=Decimal("10000"), disputed_tax_amount=Decimal("500000"),
                                      appeal_filed_date=date(2026, 2, 1))],
    )
    proof = run_phase6(p, onto, as_of_date=TODAY)
    rule_ids = {e.rule_id for e in proof.evaluations}
    assert "Sec50_3_WronglyAvailedITCInterest_I1" in rule_ids
    assert "Sec122_WrongfulITCPenalty_I1" in rule_ids
    assert "Sec54_1_LimitationPeriod_RF-X" in rule_ids
    assert "Sec107_6_PreDepositCalculation_AP-X" in rule_ids
