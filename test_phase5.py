"""
Phase 5 test suite - E-invoicing (Rule 48(4)), E-way bill (Rule 138),
Return obligations (Sec 37/39/44), TDS (Sec 51), TCS (Sec 52).

Run: pytest -v test_phase5.py
"""

from datetime import date
from decimal import Decimal

import pytest

from business_profile import BusinessProfile, InvoiceRecord, OutwardSupplyRecord, RegistrationStatus
from ontology_loader import OntologyLoader
from phase5_pipeline import run_phase5
from proof_object import VerdictStatus


@pytest.fixture(scope="module")
def onto():
    return OntologyLoader()


def find(proof, rule_id):
    for e in proof.evaluations:
        if e.rule_id == rule_id:
            return e
    return None


def base_profile(**overrides) -> BusinessProfile:
    defaults = dict(
        name="Test Co", state="Karnataka", aggregate_turnover=Decimal("8000000"),
        financial_year="2025-26", business_types=["Trader"],
        registration_status=RegistrationStatus.ACTIVE,
    )
    defaults.update(overrides)
    return BusinessProfile(**defaults)


# ======================================================================
#  E-invoicing (Rule 48(4)) - the "ever crossed, stays mandatory" rule
# ======================================================================

def test_current_turnover_above_threshold_triggers_einvoicing(onto):
    p = base_profile(aggregate_turnover=Decimal("60000000"))
    proof = run_phase5(p, onto)
    assert find(proof, "Rule48_4_EInvoicingApplicability").status == VerdictStatus.SATISFIED


def test_current_turnover_below_threshold_no_history_not_applicable(onto):
    p = base_profile(aggregate_turnover=Decimal("3000000"))
    proof = run_phase5(p, onto)
    assert find(proof, "Rule48_4_EInvoicingApplicability").status == VerdictStatus.NOT_APPLICABLE


def test_past_year_crossing_keeps_einvoicing_mandatory_even_if_current_is_lower(onto):
    """The key legal nuance: turnover crossed Rs 5Cr in FY 2023-24, current
    FY 2025-26 turnover has since dropped to Rs 30L - e-invoicing must
    STILL be mandatory. A naive current-year-only check would get this
    wrong."""
    p = base_profile(
        aggregate_turnover=Decimal("3000000"),
        turnover_by_year={"2023-24": Decimal("60000000"), "2024-25": Decimal("40000000")},
    )
    proof = run_phase5(p, onto)
    ev = find(proof, "Rule48_4_EInvoicingApplicability")
    assert ev.status == VerdictStatus.SATISFIED
    assert ev.inputs_used["highest_turnover_fy"] == "2023-24"


def test_exactly_at_threshold_not_yet_mandatory(onto):
    """Threshold is 'exceeding' Rs 5Cr - exactly at Rs 5,00,00,000 must
    NOT trigger the obligation."""
    p = base_profile(aggregate_turnover=Decimal("50000000"))
    proof = run_phase5(p, onto)
    assert find(proof, "Rule48_4_EInvoicingApplicability").status == VerdictStatus.NOT_APPLICABLE


def test_one_rupee_above_threshold_triggers(onto):
    p = base_profile(aggregate_turnover=Decimal("50000001"))
    proof = run_phase5(p, onto)
    assert find(proof, "Rule48_4_EInvoicingApplicability").status == VerdictStatus.SATISFIED


# ======================================================================
#  E-way bill (Rule 138)
# ======================================================================

def test_consignment_above_50k_requires_eway_bill(onto):
    p = base_profile(outward_supplies=[
        OutwardSupplyRecord(invoice_number="EWB-1", invoice_date=date(2025, 6, 1),
                             value=Decimal("60000"), supply_type="TaxableSupply",
                             consignment_value=Decimal("60000"))
    ])
    proof = run_phase5(p, onto)
    assert find(proof, "Rule138_EWayBillApplicability_EWB-1").status == VerdictStatus.SATISFIED


def test_consignment_exactly_at_50k_not_required(onto):
    p = base_profile(outward_supplies=[
        OutwardSupplyRecord(invoice_number="EWB-2", invoice_date=date(2025, 6, 1),
                             value=Decimal("50000"), supply_type="TaxableSupply",
                             consignment_value=Decimal("50000"))
    ])
    proof = run_phase5(p, onto)
    assert find(proof, "Rule138_EWayBillApplicability_EWB-2").status == VerdictStatus.NOT_APPLICABLE


def test_consignment_below_50k_not_required(onto):
    p = base_profile(outward_supplies=[
        OutwardSupplyRecord(invoice_number="EWB-3", invoice_date=date(2025, 6, 1),
                             value=Decimal("20000"), supply_type="TaxableSupply",
                             consignment_value=Decimal("20000"))
    ])
    proof = run_phase5(p, onto)
    assert find(proof, "Rule138_EWayBillApplicability_EWB-3").status == VerdictStatus.NOT_APPLICABLE


def test_no_consignment_value_means_not_a_goods_movement_and_is_skipped(onto):
    """A pure service supply has no consignment_value - Rule 138 should
    not even produce an evaluation for it."""
    p = base_profile(outward_supplies=[
        OutwardSupplyRecord(invoice_number="EWB-4", invoice_date=date(2025, 6, 1),
                             value=Decimal("200000"), supply_type="TaxableSupply")
    ])
    proof = run_phase5(p, onto)
    assert find(proof, "Rule138_EWayBillApplicability_EWB-4") is None


# ======================================================================
#  Return obligations
# ======================================================================

def test_normal_taxpayer_gets_gstr1_3b_and_annual(onto):
    p = base_profile()
    proof = run_phase5(p, onto)
    assert find(proof, "ReturnObligation_OutwardSupplyReturn").status == VerdictStatus.SATISFIED
    assert find(proof, "ReturnObligation_SummaryReturn").status == VerdictStatus.SATISFIED
    assert find(proof, "ReturnObligation_AnnualReturn").status == VerdictStatus.SATISFIED
    assert find(proof, "ReturnObligation_CompositionReturn") is None


def test_composition_taxpayer_gets_gstr4_not_gstr1_3b(onto):
    p = base_profile(opts_for_composition=True, aggregate_turnover=Decimal("2000000"))
    proof = run_phase5(p, onto)
    assert find(proof, "ReturnObligation_CompositionReturn").status == VerdictStatus.SATISFIED
    assert find(proof, "ReturnObligation_OutwardSupplyReturn") is None
    assert find(proof, "ReturnObligation_SummaryReturn") is None


def test_isd_gets_gstr6_and_is_exempt_from_annual_return(onto):
    p = base_profile(is_input_service_distributor=True)
    proof = run_phase5(p, onto)
    assert find(proof, "ReturnObligation_ISDReturn").status == VerdictStatus.SATISFIED
    assert find(proof, "ReturnObligation_AnnualReturn").status == VerdictStatus.NOT_APPLICABLE


def test_non_resident_gets_gstr5_and_is_exempt_from_annual_return(onto):
    p = base_profile(is_non_resident_taxable_person=True)
    proof = run_phase5(p, onto)
    assert find(proof, "ReturnObligation_NonResidentReturn").status == VerdictStatus.SATISFIED
    assert find(proof, "ReturnObligation_AnnualReturn").status == VerdictStatus.NOT_APPLICABLE


def test_tds_deductor_gets_gstr7_in_addition_to_normal_returns(onto):
    """A TDS deductor that ALSO makes ordinary taxable supplies should
    get GSTR-7 in addition to GSTR-1/3B, not instead of them - and per
    Sec 44's exclusion list, being a TDS deductor exempts it from the
    annual return regardless."""
    p = base_profile(is_deductor_under_section51=True)
    proof = run_phase5(p, onto)
    assert find(proof, "ReturnObligation_TDSReturn").status == VerdictStatus.SATISFIED
    assert find(proof, "ReturnObligation_OutwardSupplyReturn").status == VerdictStatus.SATISFIED
    assert find(proof, "ReturnObligation_AnnualReturn").status == VerdictStatus.NOT_APPLICABLE


def test_unregistered_business_has_no_return_obligations(onto):
    p = base_profile(registration_status=RegistrationStatus.NOT_REGISTERED, aggregate_turnover=Decimal("500000"))
    proof = run_phase5(p, onto)
    assert find(proof, "ReturnObligation_OutwardSupplyReturn") is None
    assert find(proof, "ReturnObligation_AnnualReturn") is None


# ======================================================================
#  TDS applicability (Sec 51)
# ======================================================================

def test_non_deductor_has_no_tds_evaluations(onto):
    p = base_profile(inward_invoices=[
        InvoiceRecord(invoice_number="TDS-1", invoice_date=date(2025, 6, 1),
                       taxable_value=Decimal("500000"), tax_amount=Decimal("90000"))
    ])
    proof = run_phase5(p, onto)
    assert find(proof, "Sec51_TDSApplicability_TDS-1") is None


def test_deductor_above_threshold_and_deducted_is_satisfied(onto):
    p = base_profile(is_deductor_under_section51=True, inward_invoices=[
        InvoiceRecord(invoice_number="TDS-2", invoice_date=date(2025, 6, 1),
                       taxable_value=Decimal("500000"), tax_amount=Decimal("90000"),
                       tds_deducted=True)
    ])
    proof = run_phase5(p, onto)
    assert find(proof, "Sec51_TDSApplicability_TDS-2").status == VerdictStatus.SATISFIED


def test_deductor_above_threshold_but_not_deducted_is_violated(onto):
    p = base_profile(is_deductor_under_section51=True, inward_invoices=[
        InvoiceRecord(invoice_number="TDS-3", invoice_date=date(2025, 6, 1),
                       taxable_value=Decimal("500000"), tax_amount=Decimal("90000"),
                       tds_deducted=False)
    ])
    proof = run_phase5(p, onto)
    assert find(proof, "Sec51_TDSApplicability_TDS-3").status == VerdictStatus.VIOLATED


def test_deductor_exactly_at_threshold_not_required(onto):
    p = base_profile(is_deductor_under_section51=True, inward_invoices=[
        InvoiceRecord(invoice_number="TDS-4", invoice_date=date(2025, 6, 1),
                       taxable_value=Decimal("250000"), tax_amount=Decimal("45000"))
    ])
    proof = run_phase5(p, onto)
    assert find(proof, "Sec51_TDSApplicability_TDS-4").status == VerdictStatus.NOT_APPLICABLE


def test_deductor_below_threshold_not_required(onto):
    p = base_profile(is_deductor_under_section51=True, inward_invoices=[
        InvoiceRecord(invoice_number="TDS-5", invoice_date=date(2025, 6, 1),
                       taxable_value=Decimal("100000"), tax_amount=Decimal("18000"))
    ])
    proof = run_phase5(p, onto)
    assert find(proof, "Sec51_TDSApplicability_TDS-5").status == VerdictStatus.NOT_APPLICABLE


# ======================================================================
#  TCS applicability (Sec 52)
# ======================================================================

def test_non_ecommerce_operator_has_no_tcs_evaluation(onto):
    p = base_profile()
    proof = run_phase5(p, onto)
    assert find(proof, "Sec52_TCSObligation") is None


def test_ecommerce_operator_correctly_collecting_tcs_is_satisfied(onto):
    p = base_profile(is_ecommerce_operator=True, is_required_to_collect_tcs_under_section52=True)
    proof = run_phase5(p, onto)
    assert find(proof, "Sec52_TCSObligation").status == VerdictStatus.SATISFIED


def test_ecommerce_operator_not_collecting_tcs_is_violated(onto):
    p = base_profile(is_ecommerce_operator=True, is_required_to_collect_tcs_under_section52=False)
    proof = run_phase5(p, onto)
    assert find(proof, "Sec52_TCSObligation").status == VerdictStatus.VIOLATED
