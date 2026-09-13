"""
Phase 4 test suite - Input Tax Credit (Sec 16(2), Sec 16(4), Sec 17(5), Rule 37).

Run: pytest -v test_phase4.py
"""

from datetime import date
from decimal import Decimal

import pytest

from business_profile import BusinessProfile, InvoiceRecord
from itc_engine import ITCEligibilityEngine, financial_year_of, sec16_4_deadline
from ontology_loader import OntologyLoader
from proof_object import VerdictStatus


@pytest.fixture(scope="module")
def onto():
    return OntologyLoader()


TODAY = date(2026, 9, 10)


def engine(onto):
    return ITCEligibilityEngine(onto, as_of_date=TODAY)


def find(evaluations, rule_id):
    for e in evaluations:
        if e.rule_id == rule_id:
            return e
    return None


def full_conditions(**overrides) -> dict:
    base = dict(
        has_tax_invoice_or_debit_note=True,
        invoice_details_communicated_37_38=True,
        goods_or_services_received=True,
        tax_paid_by_supplier_to_government=True,
        supplier_has_filed_return=True,
    )
    base.update(overrides)
    return base


def profile_with(*invoices) -> BusinessProfile:
    return BusinessProfile(name="ITC Test Co", state="Karnataka",
                            aggregate_turnover=Decimal("5000000"), financial_year="2025-26",
                            inward_invoices=list(invoices))


# ======================================================================
#  Sec 16(2) - all five conditions
# ======================================================================

def test_all_conditions_met_is_eligible(onto):
    inv = InvoiceRecord(invoice_number="I1", invoice_date=date(2025, 6, 1),
                         taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                         **full_conditions())
    result = engine(onto).evaluate(profile_with(inv))
    assert find(result, "Sec16_2_ITCEligibility_I1").status == VerdictStatus.SATISFIED


def test_one_missing_condition_not_claimed_is_indeterminate(onto):
    """Supplier hasn't filed their return yet, ITC not claimed -> nothing
    wrong has happened, just not eligible yet."""
    inv = InvoiceRecord(invoice_number="I2", invoice_date=date(2025, 6, 1),
                         taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                         **full_conditions(supplier_has_filed_return=False))
    result = engine(onto).evaluate(profile_with(inv))
    ev = find(result, "Sec16_2_ITCEligibility_I2")
    assert ev.status == VerdictStatus.INDETERMINATE
    assert "supplier_has_filed_return" in ev.inputs_used["failed_conditions"]


def test_one_missing_condition_but_claimed_is_violated(onto):
    """Same missing condition, but ITC WAS claimed anyway -> wrongly availed."""
    inv = InvoiceRecord(invoice_number="I3", invoice_date=date(2025, 6, 1),
                         taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                         itc_claimed=True,
                         **full_conditions(supplier_has_filed_return=False))
    result = engine(onto).evaluate(profile_with(inv))
    assert find(result, "Sec16_2_ITCEligibility_I3").status == VerdictStatus.VIOLATED


def test_no_conditions_met_at_all_is_indeterminate_when_unclaimed(onto):
    inv = InvoiceRecord(invoice_number="I4", invoice_date=date(2025, 6, 1),
                         taxable_value=Decimal("100000"), tax_amount=Decimal("18000"))
    result = engine(onto).evaluate(profile_with(inv))
    ev = find(result, "Sec16_2_ITCEligibility_I4")
    assert ev.status == VerdictStatus.INDETERMINATE
    assert len(ev.inputs_used["failed_conditions"]) == 5


@pytest.mark.parametrize("missing_field", [
    "has_tax_invoice_or_debit_note",
    "invoice_details_communicated_37_38",
    "goods_or_services_received",
    "tax_paid_by_supplier_to_government",
    "supplier_has_filed_return",
])
def test_each_individual_condition_is_load_bearing(onto, missing_field):
    """Sec 16(2) requires ALL five conditions - dropping ANY single one
    (holding the rest true) must break eligibility. Guards against a
    conjunction accidentally being encoded as some subset."""
    conditions = full_conditions(**{missing_field: False})
    inv = InvoiceRecord(invoice_number="I5", invoice_date=date(2025, 6, 1),
                         taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                         **conditions)
    result = engine(onto).evaluate(profile_with(inv))
    ev = find(result, "Sec16_2_ITCEligibility_I5")
    assert ev.status != VerdictStatus.SATISFIED
    assert ev.inputs_used["failed_conditions"] == [missing_field]


# ======================================================================
#  Sec 17(5) - blocked credit (absolute bar)
# ======================================================================

def test_blocked_credit_not_claimed_is_not_applicable(onto):
    inv = InvoiceRecord(invoice_number="I6", invoice_date=date(2025, 6, 1),
                         taxable_value=Decimal("50000"), tax_amount=Decimal("9000"),
                         is_blocked_credit_category=True, blocked_credit_reason="Motor vehicle",
                         **full_conditions())
    result = engine(onto).evaluate(profile_with(inv))
    ev = find(result, "Sec17_5_BlockedCredit_I6")
    assert ev.status == VerdictStatus.NOT_APPLICABLE


def test_blocked_credit_claimed_is_violated_even_if_all_16_2_conditions_met(onto):
    """The key test: Sec 17(5) is an INDEPENDENT, absolute bar. Even with
    all five Sec 16(2) conditions perfectly satisfied, a blocked category
    that has been claimed is still a violation - Sec 16(2) eligibility
    does not override Sec 17(5)."""
    inv = InvoiceRecord(invoice_number="I7", invoice_date=date(2025, 6, 1),
                         taxable_value=Decimal("50000"), tax_amount=Decimal("9000"),
                         is_blocked_credit_category=True, blocked_credit_reason="Club membership",
                         itc_claimed=True, **full_conditions())
    result = engine(onto).evaluate(profile_with(inv))
    ev = find(result, "Sec17_5_BlockedCredit_I7")
    assert ev.status == VerdictStatus.VIOLATED
    # And no separate Sec 16(2) evaluation should even run for a blocked invoice
    assert find(result, "Sec16_2_ITCEligibility_I7") is None


def test_blocked_credit_skips_180_day_and_time_bar_checks(onto):
    inv = InvoiceRecord(invoice_number="I8", invoice_date=date(2024, 1, 1),
                         taxable_value=Decimal("50000"), tax_amount=Decimal("9000"),
                         is_blocked_credit_category=True, itc_claimed=True,
                         payment_made_to_supplier=False)
    result = engine(onto).evaluate(profile_with(inv))
    assert find(result, "Sec16_2_Proviso_180Day_I8") is None
    assert find(result, "Sec16_4_TimeBar_I8") is None


# ======================================================================
#  180-day payment rule (Rule 37)
# ======================================================================

def test_paid_within_180_days_satisfied(onto):
    inv = InvoiceRecord(invoice_number="I9", invoice_date=date(2025, 1, 1),
                         taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                         payment_made_to_supplier=True, payment_date=date(2025, 6, 1),  # 151 days
                         **full_conditions())
    result = engine(onto).evaluate(profile_with(inv))
    ev = find(result, "Sec16_2_Proviso_180Day_I9")
    assert ev.status == VerdictStatus.SATISFIED
    assert ev.computed_value == 151


def test_paid_exactly_at_180_days_satisfied(onto):
    """Boundary: exactly 180 days is still within the rule (<=180)."""
    inv = InvoiceRecord(invoice_number="I10", invoice_date=date(2025, 1, 1),
                         taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                         payment_made_to_supplier=True, payment_date=date(2025, 6, 30),  # exactly 180 days
                         **full_conditions())
    result = engine(onto).evaluate(profile_with(inv))
    ev = find(result, "Sec16_2_Proviso_180Day_I10")
    assert ev.computed_value == 180
    assert ev.status == VerdictStatus.SATISFIED


def test_paid_181_days_is_indeterminate_when_unclaimed(onto):
    inv = InvoiceRecord(invoice_number="I11", invoice_date=date(2025, 1, 1),
                         taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                         payment_made_to_supplier=True, payment_date=date(2025, 7, 1),  # 181 days
                         itc_claimed=False, **full_conditions())
    result = engine(onto).evaluate(profile_with(inv))
    ev = find(result, "Sec16_2_Proviso_180Day_I11")
    assert ev.computed_value == 181
    assert ev.status == VerdictStatus.INDETERMINATE


def test_paid_181_days_is_violated_when_claimed(onto):
    inv = InvoiceRecord(invoice_number="I12", invoice_date=date(2025, 1, 1),
                         taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                         payment_made_to_supplier=True, payment_date=date(2025, 7, 1),
                         itc_claimed=True, **full_conditions())
    result = engine(onto).evaluate(profile_with(inv))
    assert find(result, "Sec16_2_Proviso_180Day_I12").status == VerdictStatus.VIOLATED


def test_unpaid_within_window_is_silent(onto):
    """Not yet paid, but still within 180 days as of the evaluation date -
    no finding should be emitted at all (nothing wrong yet)."""
    inv = InvoiceRecord(invoice_number="I13", invoice_date=date(2026, 8, 1),  # 40 days before TODAY
                         taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                         payment_made_to_supplier=False, itc_claimed=True,
                         **full_conditions())
    result = engine(onto).evaluate(profile_with(inv))
    assert find(result, "Sec16_2_Proviso_180Day_I13") is None


def test_unpaid_past_window_and_claimed_is_violated(onto):
    inv = InvoiceRecord(invoice_number="I14", invoice_date=date(2025, 1, 1),  # far more than 180 days before TODAY
                         taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                         payment_made_to_supplier=False, itc_claimed=True,
                         **full_conditions())
    result = engine(onto).evaluate(profile_with(inv))
    assert find(result, "Sec16_2_Proviso_180Day_I14").status == VerdictStatus.VIOLATED


# ======================================================================
#  Sec 16(4) time bar
# ======================================================================

def test_financial_year_derivation():
    assert financial_year_of(date(2025, 6, 15)) == "2025-26"
    assert financial_year_of(date(2026, 3, 31)) == "2025-26"
    assert financial_year_of(date(2026, 4, 1)) == "2026-27"


def test_deadline_defaults_to_november_30():
    assert sec16_4_deadline("2025-26", {}) == date(2026, 11, 30)


def test_deadline_uses_earlier_annual_return_date():
    filed = {"2025-26": date(2026, 10, 15)}
    assert sec16_4_deadline("2025-26", filed) == date(2026, 10, 15)


def test_deadline_ignores_later_annual_return_date():
    """If the annual return was filed AFTER 30 Nov (unusual, but the
    deadline logic must not use a later date to be lenient)."""
    filed = {"2025-26": date(2026, 12, 20)}
    assert sec16_4_deadline("2025-26", filed) == date(2026, 11, 30)


def test_claimed_before_deadline_satisfied(onto):
    inv = InvoiceRecord(invoice_number="I15", invoice_date=date(2025, 6, 1),
                         taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                         itc_claimed=True, itc_claim_date=date(2026, 10, 1),
                         **full_conditions())
    result = engine(onto).evaluate(profile_with(inv))
    assert find(result, "Sec16_4_TimeBar_I15").status == VerdictStatus.SATISFIED


def test_claimed_after_deadline_violated(onto):
    inv = InvoiceRecord(invoice_number="I16", invoice_date=date(2025, 6, 1),
                         taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                         itc_claimed=True, itc_claim_date=date(2026, 12, 15),
                         **full_conditions())
    result = engine(onto).evaluate(profile_with(inv))
    assert find(result, "Sec16_4_TimeBar_I16").status == VerdictStatus.VIOLATED


def test_claimed_with_missing_claim_date_is_indeterminate(onto):
    inv = InvoiceRecord(invoice_number="I17", invoice_date=date(2025, 6, 1),
                         taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                         itc_claimed=True, itc_claim_date=None, **full_conditions())
    result = engine(onto).evaluate(profile_with(inv))
    assert find(result, "Sec16_4_TimeBar_I17").status == VerdictStatus.INDETERMINATE


def test_unclaimed_past_deadline_is_violated_permanently_lost(onto):
    """FY 2024-25 invoice (deadline 30 Nov 2025), never claimed, evaluated
    'today' = 10 Sep 2026 - well past deadline: permanently lost ITC."""
    inv = InvoiceRecord(invoice_number="I18", invoice_date=date(2024, 6, 1),
                         taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                         itc_claimed=False, **full_conditions())
    result = engine(onto).evaluate(profile_with(inv))
    ev = find(result, "Sec16_4_TimeBar_I18")
    assert ev.status == VerdictStatus.VIOLATED
    assert ev.inputs_used["financial_year"] == "2024-25"


def test_unclaimed_still_within_deadline_is_silent(onto):
    inv = InvoiceRecord(invoice_number="I19", invoice_date=date(2026, 6, 1),
                         taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                         itc_claimed=False, **full_conditions())
    result = engine(onto).evaluate(profile_with(inv))
    assert find(result, "Sec16_4_TimeBar_I19") is None
