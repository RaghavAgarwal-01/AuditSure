"""
Phase 3 test suite - Supply Classification (Sec 7/8/16 IGST, Sec 8 CGST)
and Levy Mechanism (Sec 9(3)/9(4) CGST).

Run: pytest -v tests/test_phase3.py
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models.business_profile import BusinessProfile, OutwardSupplyRecord, RegistrationStatus
from app.ontology.ontology_loader import OntologyLoader
from app.pipelines.phase3_pipeline import run_phase3
from app.models.proof_object import VerdictStatus


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
        name="Test Co", state="Karnataka", aggregate_turnover=Decimal("5000000"),
        financial_year="2025-26", business_types=["Trader"],
        registration_status=RegistrationStatus.ACTIVE,
    )
    defaults.update(overrides)
    return BusinessProfile(**defaults)


# ======================================================================
#  Zero-rated validity (Sec 16, IGST Act)
# ======================================================================

def test_zero_rated_export_is_valid(onto):
    p = base_profile(outward_supplies=[
        OutwardSupplyRecord(invoice_number="INV-1", invoice_date=date(2025, 6, 1),
                             value=Decimal("100000"), supply_type="ZeroRatedSupply",
                             is_export_or_sez_supply=True)
    ])
    proof = run_phase3(p, onto)
    assert find(proof, "Sec16IGST_ZeroRatedValidity_INV-1").status == VerdictStatus.SATISFIED


def test_zero_rated_without_export_or_sez_is_violated(onto):
    """The classic misclassification: marking a domestic sale zero-rated
    without it actually being an export/SEZ supply."""
    p = base_profile(outward_supplies=[
        OutwardSupplyRecord(invoice_number="INV-2", invoice_date=date(2025, 6, 1),
                             value=Decimal("100000"), supply_type="ZeroRatedSupply",
                             is_export_or_sez_supply=False)
    ])
    proof = run_phase3(p, onto)
    assert find(proof, "Sec16IGST_ZeroRatedValidity_INV-2").status == VerdictStatus.VIOLATED


def test_taxable_supply_zero_rated_check_not_applicable(onto):
    p = base_profile(outward_supplies=[
        OutwardSupplyRecord(invoice_number="INV-3", invoice_date=date(2025, 6, 1),
                             value=Decimal("100000"), supply_type="TaxableSupply")
    ])
    proof = run_phase3(p, onto)
    assert find(proof, "Sec16IGST_ZeroRatedValidity_INV-3").status == VerdictStatus.NOT_APPLICABLE


# ======================================================================
#  Place of supply consistency (Sec 7/8, IGST Act)
# ======================================================================

def test_correctly_declared_interstate_supply(onto):
    p = base_profile(outward_supplies=[
        OutwardSupplyRecord(invoice_number="INV-4", invoice_date=date(2025, 6, 1),
                             value=Decimal("100000"), supply_type="TaxableSupply",
                             is_interstate=True, recipient_state="Maharashtra")
    ])
    proof = run_phase3(p, onto)
    ev = find(proof, "Sec7_8IGST_PlaceOfSupply_INV-4")
    assert ev.status == VerdictStatus.SATISFIED
    assert ev.legal_citation == "Sec 7, IGST Act 2017"


def test_correctly_declared_intrastate_supply(onto):
    p = base_profile(outward_supplies=[
        OutwardSupplyRecord(invoice_number="INV-5", invoice_date=date(2025, 6, 1),
                             value=Decimal("100000"), supply_type="TaxableSupply",
                             is_interstate=False, recipient_state="Karnataka")
    ])
    proof = run_phase3(p, onto)
    ev = find(proof, "Sec7_8IGST_PlaceOfSupply_INV-5")
    assert ev.status == VerdictStatus.SATISFIED
    assert ev.legal_citation == "Sec 8, IGST Act 2017"


def test_mismatched_interstate_flag_is_caught(onto):
    """Declared intra-State but recipient is actually in a different
    State - a real data-entry bug this engine exists to catch."""
    p = base_profile(outward_supplies=[
        OutwardSupplyRecord(invoice_number="INV-6", invoice_date=date(2025, 6, 1),
                             value=Decimal("100000"), supply_type="TaxableSupply",
                             is_interstate=False, recipient_state="Maharashtra")
    ])
    proof = run_phase3(p, onto)
    ev = find(proof, "Sec7_8IGST_PlaceOfSupply_INV-6")
    assert ev.status == VerdictStatus.VIOLATED


def test_missing_recipient_state_is_indeterminate(onto):
    p = base_profile(outward_supplies=[
        OutwardSupplyRecord(invoice_number="INV-7", invoice_date=date(2025, 6, 1),
                             value=Decimal("100000"), supply_type="TaxableSupply")
    ])
    proof = run_phase3(p, onto)
    assert find(proof, "Sec7_8IGST_PlaceOfSupply_INV-7").status == VerdictStatus.INDETERMINATE


def test_summary_flag_disagrees_with_invoices_is_flagged(onto):
    """profile.makes_interstate_outward_supply=False, but an actual
    invoice shows an inter-State recipient - this must surface because
    Phase 2's Sec 24 check depends on that summary flag being right."""
    p = base_profile(
        makes_interstate_outward_supply=False,
        outward_supplies=[
            OutwardSupplyRecord(invoice_number="INV-8", invoice_date=date(2025, 6, 1),
                                 value=Decimal("100000"), supply_type="TaxableSupply",
                                 is_interstate=True, recipient_state="Maharashtra")
        ],
    )
    proof = run_phase3(p, onto)
    ev = find(proof, "ProfileFlag_InterstateSupplyConsistency")
    assert ev is not None
    assert ev.status == VerdictStatus.VIOLATED


def test_summary_flag_agrees_with_invoices_is_silent(onto):
    """When the flag and the invoices agree, no consistency warning
    should be emitted at all (keeps the proof object from being
    cluttered with non-findings)."""
    p = base_profile(
        makes_interstate_outward_supply=True,
        outward_supplies=[
            OutwardSupplyRecord(invoice_number="INV-9", invoice_date=date(2025, 6, 1),
                                 value=Decimal("100000"), supply_type="TaxableSupply",
                                 is_interstate=True, recipient_state="Maharashtra")
        ],
    )
    proof = run_phase3(p, onto)
    assert find(proof, "ProfileFlag_InterstateSupplyConsistency") is None


# ======================================================================
#  Composite / Mixed supply (Sec 8(a)/(b))
# ======================================================================

def test_composite_supply_with_principal_identified(onto):
    p = base_profile(outward_supplies=[
        OutwardSupplyRecord(invoice_number="INV-10", invoice_date=date(2025, 6, 1),
                             value=Decimal("100000"), supply_type="CompositeSupply",
                             is_composite_supply_principal="AC installation service")
    ])
    proof = run_phase3(p, onto)
    ev = find(proof, "Sec8a_CompositeSupplyRate_INV-10")
    assert ev.status == VerdictStatus.SATISFIED
    assert "AC installation service" in ev.explanation_hint


def test_composite_supply_without_principal_is_indeterminate(onto):
    p = base_profile(outward_supplies=[
        OutwardSupplyRecord(invoice_number="INV-11", invoice_date=date(2025, 6, 1),
                             value=Decimal("100000"), supply_type="CompositeSupply")
    ])
    proof = run_phase3(p, onto)
    assert find(proof, "Sec8a_CompositeSupplyRate_INV-11").status == VerdictStatus.INDETERMINATE


def test_mixed_supply_is_always_indeterminate_on_rate(onto):
    """Mixed-supply rate always needs the actual numeric GST rate of
    each bundled item to resolve 'highest rate' - which is outside this
    system's modelled scope (no HSN rate slabs in the source manual),
    so this should always be INDETERMINATE, never SATISFIED/VIOLATED."""
    p = base_profile(outward_supplies=[
        OutwardSupplyRecord(invoice_number="INV-12", invoice_date=date(2025, 6, 1),
                             value=Decimal("100000"), supply_type="MixedSupply",
                             bundled_supply_descriptions=["Chocolates", "Aerated drink", "Fruit juice"])
    ])
    proof = run_phase3(p, onto)
    assert find(proof, "Sec8b_MixedSupplyRate_INV-12").status == VerdictStatus.INDETERMINATE


# ======================================================================
#  Levy mechanism - forward vs reverse charge (Sec 9(3)/9(4))
# ======================================================================

def test_default_forward_charge(onto):
    p = base_profile(outward_supplies=[
        OutwardSupplyRecord(invoice_number="INV-13", invoice_date=date(2025, 6, 1),
                             value=Decimal("100000"), supply_type="TaxableSupply")
    ])
    proof = run_phase3(p, onto)
    ev = find(proof, "Sec9_LevyMechanism_INV-13")
    assert ev.status == VerdictStatus.SATISFIED
    assert ev.legal_citation == "Sec 9(1), CGST Act 2017"


def test_sec9_3_reverse_charge_regardless_of_registration(onto):
    """Sec 9(3) fires purely on the notified-category flag - registration
    status of either party is irrelevant, unlike Sec 9(4) below."""
    p = base_profile(registration_status=RegistrationStatus.ACTIVE, outward_supplies=[
        OutwardSupplyRecord(invoice_number="INV-14", invoice_date=date(2025, 6, 1),
                             value=Decimal("100000"), supply_type="TaxableSupply",
                             is_notified_under_sec9_3=True)
    ])
    proof = run_phase3(p, onto)
    ev = find(proof, "Sec9_LevyMechanism_INV-14")
    assert ev.status == VerdictStatus.SATISFIED
    assert ev.legal_citation == "Sec 9(3), CGST Act 2017"


def test_sec9_4_fires_only_when_supplier_unregistered_and_recipient_registered(onto):
    p = base_profile(registration_status=RegistrationStatus.NOT_REGISTERED, outward_supplies=[
        OutwardSupplyRecord(invoice_number="INV-15", invoice_date=date(2025, 6, 1),
                             value=Decimal("100000"), supply_type="TaxableSupply",
                             is_notified_under_sec9_4=True, recipient_is_registered=True)
    ])
    proof = run_phase3(p, onto)
    ev = find(proof, "Sec9_LevyMechanism_INV-15")
    assert ev.status == VerdictStatus.SATISFIED
    assert ev.legal_citation == "Sec 9(4), CGST Act 2017"


def test_sec9_4_does_not_fire_when_supplier_is_registered(onto):
    """Same notified category, same recipient status, but the supplier
    IS registered this time - Sec 9(4)'s precondition fails, so this
    should fall back to ordinary forward charge."""
    p = base_profile(registration_status=RegistrationStatus.ACTIVE, outward_supplies=[
        OutwardSupplyRecord(invoice_number="INV-16", invoice_date=date(2025, 6, 1),
                             value=Decimal("100000"), supply_type="TaxableSupply",
                             is_notified_under_sec9_4=True, recipient_is_registered=True)
    ])
    proof = run_phase3(p, onto)
    ev = find(proof, "Sec9_LevyMechanism_INV-16")
    assert ev.status == VerdictStatus.SATISFIED
    assert ev.legal_citation == "Sec 9(1), CGST Act 2017"


def test_sec9_4_unknown_recipient_status_is_indeterminate(onto):
    p = base_profile(registration_status=RegistrationStatus.NOT_REGISTERED, outward_supplies=[
        OutwardSupplyRecord(invoice_number="INV-17", invoice_date=date(2025, 6, 1),
                             value=Decimal("100000"), supply_type="TaxableSupply",
                             is_notified_under_sec9_4=True, recipient_is_registered=None)
    ])
    proof = run_phase3(p, onto)
    ev = find(proof, "Sec9_LevyMechanism_INV-17")
    assert ev.status == VerdictStatus.INDETERMINATE


def test_exempt_supply_has_no_levy_mechanism_evaluation(onto):
    """Reverse/forward charge only makes sense for taxable-type supplies;
    an ExemptSupply record should not get a Sec 9 evaluation at all."""
    p = base_profile(outward_supplies=[
        OutwardSupplyRecord(invoice_number="INV-18", invoice_date=date(2025, 6, 1),
                             value=Decimal("100000"), supply_type="ExemptSupply")
    ])
    proof = run_phase3(p, onto)
    assert find(proof, "Sec9_LevyMechanism_INV-18") is None
