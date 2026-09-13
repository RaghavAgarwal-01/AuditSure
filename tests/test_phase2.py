"""
Phase 2 test suite - Registration (Sec 22/23/24) + Composition (Sec 10).

Every case below is hand-worked against the actual statutory thresholds
(not against the code) before being encoded as an assertion, per the
plan's requirement for boundary-tested unit tests. Boundary cases use
the threshold value EXACTLY (not threshold +/- 1) since Sec 22/10 use
strict/non-strict comparisons that differ at the boundary itself:
  - Sec 22: liability is turnover > threshold (so turnover == threshold
    is NOT yet liable).
  - Sec 10: eligibility is turnover <= threshold (so turnover == threshold
    IS still eligible).

Run: pytest -v tests/test_phase2.py
"""

from decimal import Decimal

import pytest

from app.models.business_profile import BusinessProfile
from app.ontology.ontology_loader import OntologyLoader
from app.pipelines.phase2_pipeline import run_phase2
from app.models.proof_object import VerdictStatus


@pytest.fixture(scope="module")
def onto():
    return OntologyLoader()


def status_of(proof, rule_id):
    for e in proof.evaluations:
        if e.rule_id == rule_id:
            return e.status
    return None


def evaluation_of(proof, rule_id):
    for e in proof.evaluations:
        if e.rule_id == rule_id:
            return e
    return None


# ======================================================================
#  SECTION 22 - Registration threshold (general states)
# ======================================================================

def test_general_state_above_threshold_is_liable(onto):
    """Rs 25L in Maharashtra (Rs 20L threshold) -> liable."""
    p = BusinessProfile(name="Sharma Textiles", state="Maharashtra",
                         aggregate_turnover=Decimal("2500000"), financial_year="2025-26",
                         business_types=["Trader"])
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec22_RegistrationLiability") == VerdictStatus.VIOLATED


def test_general_state_exactly_at_threshold_is_not_liable(onto):
    """Exactly Rs 20,00,000 in a general state: Sec 22 says '> 20 lakh',
    so exactly-at-threshold must NOT be liable. This is the boundary
    case most hand-written if/else code gets wrong (off-by-one on >
    vs >=)."""
    p = BusinessProfile(name="Boundary Co", state="Karnataka",
                         aggregate_turnover=Decimal("2000000"), financial_year="2025-26",
                         business_types=["Trader"])
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec22_RegistrationLiability") == VerdictStatus.SATISFIED


def test_general_state_one_rupee_above_threshold_is_liable(onto):
    p = BusinessProfile(name="Boundary Co Plus One", state="Karnataka",
                         aggregate_turnover=Decimal("2000001"), financial_year="2025-26",
                         business_types=["Trader"])
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec22_RegistrationLiability") == VerdictStatus.VIOLATED


# ======================================================================
#  SECTION 22 - Special category states (Rs 10L threshold)
# ======================================================================

def test_special_category_state_uses_10L_not_20L(onto):
    """Rs 12L in Manipur (special category, Rs 10L threshold) -> liable,
    even though Rs 12L would be BELOW the Rs 20L general threshold.
    This is the case that proves the engine is actually branching on
    special-category status, not just applying one flat number."""
    p = BusinessProfile(name="Northeast Handicrafts", state="Manipur",
                         aggregate_turnover=Decimal("1200000"), financial_year="2025-26",
                         business_types=["Manufacturer"])
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec22_RegistrationLiability") == VerdictStatus.VIOLATED
    ev = evaluation_of(proof, "Sec22_RegistrationLiability")
    assert ev.threshold_id == "ThresholdRegistrationSpecialCategory10L"
    assert ev.threshold_value == 1_000_000


def test_special_category_state_exactly_at_10L_is_not_liable(onto):
    p = BusinessProfile(name="Tripura Boundary Co", state="Tripura",
                         aggregate_turnover=Decimal("1000000"), financial_year="2025-26",
                         business_types=["Trader"])
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec22_RegistrationLiability") == VerdictStatus.SATISFIED


def test_non_special_category_northeastern_neighbour_uses_20L(onto):
    """Assam was CARVED OUT of special-category treatment for Sec 22 by
    amendment (per the ontology's gst:SpecialCategoryState sourceNote) -
    Rs 12L there must NOT trigger liability, unlike Manipur above. This
    guards against a naive 'all northeastern states are special category'
    assumption creeping into the model."""
    p = BusinessProfile(name="Assam Traders", state="Assam",
                         aggregate_turnover=Decimal("1200000"), financial_year="2025-26",
                         business_types=["Trader"])
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec22_RegistrationLiability") == VerdictStatus.SATISFIED


# ======================================================================
#  SECTION 24 - Compulsory registration overrides turnover AND Sec 23
# ======================================================================

def test_sec24_overrides_low_turnover(onto):
    """Rs 5L turnover (well below any threshold) but makes inter-State
    supply -> Sec 24 makes registration mandatory anyway."""
    p = BusinessProfile(name="Tiny Interstate Seller", state="DelhiNationalCapitalTerritory",
                         aggregate_turnover=Decimal("500000"), financial_year="2025-26",
                         business_types=["Trader"], makes_interstate_outward_supply=True)
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec24_CompulsoryRegistration") == VerdictStatus.VIOLATED
    assert status_of(proof, "Sec22_RegistrationLiability") is None  # Sec 22 evaluation must not also fire


def test_sec24_overrides_sec23_exemption(onto):
    """A casual taxable person who ALSO exclusively deals in exempt goods
    is still compulsorily registerable under Sec 24 - Sec 23 does not
    save them. Tests the exact priority-ordering the Z3 formula encodes."""
    p = BusinessProfile(name="Casual Exempt Trader", state="DelhiNationalCapitalTerritory",
                         aggregate_turnover=Decimal("100000"), financial_year="2025-26",
                         business_types=["Trader"],
                         is_casual_taxable_person=True,
                         supplies_exclusively_exempt_or_nontaxable_goods=True)
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec24_CompulsoryRegistration") == VerdictStatus.VIOLATED
    assert status_of(proof, "Sec23_RegistrationExemption") is None


# ======================================================================
#  SECTION 23 - Exemption from registration
# ======================================================================

def test_agriculturist_exempt_regardless_of_turnover(onto):
    """Sec 23(1)(b): an agriculturist supplying own produce is exempt
    even at a very high turnover, as long as no Sec 24 trigger applies."""
    p = BusinessProfile(name="Big Farm Co", state="Punjab",
                         aggregate_turnover=Decimal("50000000"), financial_year="2025-26",
                         business_types=["Trader"], is_agriculturist=True)
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec23_RegistrationExemption") == VerdictStatus.SATISFIED


def test_exclusively_exempt_supplier_is_exempt(onto):
    p = BusinessProfile(name="Exempt Goods Seller", state="Punjab",
                         aggregate_turnover=Decimal("3000000"), financial_year="2025-26",
                         business_types=["Trader"],
                         supplies_exclusively_exempt_or_nontaxable_goods=True)
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec23_RegistrationExemption") == VerdictStatus.SATISFIED


# ======================================================================
#  SECTION 10(1) - Composition levy (goods)
# ======================================================================

def test_composition_goods_eligible_within_threshold(onto):
    p = BusinessProfile(name="Eligible Manufacturer", state="Gujarat",
                         aggregate_turnover=Decimal("8000000"), financial_year="2025-26",
                         business_types=["Manufacturer"], opts_for_composition=True)
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec10_1_CompositionGoods") == VerdictStatus.SATISFIED


def test_composition_goods_exactly_at_1_5cr_still_eligible(onto):
    """Sec 10(1) proviso ceiling is inclusive (<=), unlike Sec 22's
    exclusive (>) threshold - this test specifically guards against
    copy-pasting the Sec 22 boundary convention into Sec 10 by mistake."""
    p = BusinessProfile(name="Exactly At Ceiling Co", state="Gujarat",
                         aggregate_turnover=Decimal("15000000"), financial_year="2025-26",
                         business_types=["Manufacturer"], opts_for_composition=True)
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec10_1_CompositionGoods") == VerdictStatus.SATISFIED


def test_composition_goods_one_rupee_over_ceiling_ineligible(onto):
    p = BusinessProfile(name="Just Over Ceiling Co", state="Gujarat",
                         aggregate_turnover=Decimal("15000001"), financial_year="2025-26",
                         business_types=["Manufacturer"], opts_for_composition=True)
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec10_CompositionIneligible") == VerdictStatus.VIOLATED


def test_composition_ineligible_due_to_interstate_supply_even_under_threshold(onto):
    """Rs 50L (well under Rs 1.5Cr) but makes inter-State supply ->
    ineligible anyway. Proves the disqualifiers are checked even when
    turnover alone would pass."""
    p = BusinessProfile(name="Interstate Small Trader", state="Gujarat",
                         aggregate_turnover=Decimal("5000000"), financial_year="2025-26",
                         business_types=["Trader"], opts_for_composition=True,
                         makes_interstate_outward_supply=True)
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec10_CompositionIneligible") == VerdictStatus.VIOLATED


def test_composition_goods_special_category_uses_75L_not_1_5cr(onto):
    """A Tripura manufacturer with Rs 80L turnover exceeds the
    special-category Rs 75L composition ceiling even though Rs 80L is
    far under the general Rs 1.5Cr ceiling - proves state-conditional
    threshold selection for composition, mirroring the same pattern
    already tested for registration."""
    p = BusinessProfile(name="Tripura Manufacturer", state="Tripura",
                         aggregate_turnover=Decimal("8000000"), financial_year="2025-26",
                         business_types=["Manufacturer"], opts_for_composition=True)
    proof = run_phase2(p, onto)
    ev = evaluation_of(proof, "Sec10_CompositionIneligible")
    assert ev is not None
    assert ev.threshold_id == "ThresholdCompositionGoodsSpecialCategory75L"


# ======================================================================
#  SECTION 10(2A) - Composition levy (services)
# ======================================================================

def test_composition_services_eligible_within_50L(onto):
    p = BusinessProfile(name="Eligible Consultant", state="Karnataka",
                         aggregate_turnover=Decimal("4000000"), financial_year="2025-26",
                         business_types=["ServiceProvider"], opts_for_composition=True)
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec10_2A_CompositionServices") == VerdictStatus.SATISFIED


def test_composition_services_exactly_at_50L_still_eligible(onto):
    p = BusinessProfile(name="Exactly At Services Ceiling", state="Karnataka",
                         aggregate_turnover=Decimal("5000000"), financial_year="2025-26",
                         business_types=["ServiceProvider"], opts_for_composition=True)
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec10_2A_CompositionServices") == VerdictStatus.SATISFIED


def test_composition_services_over_50L_ineligible(onto):
    p = BusinessProfile(name="Over Services Ceiling", state="Karnataka",
                         aggregate_turnover=Decimal("5100000"), financial_year="2025-26",
                         business_types=["ServiceProvider"], opts_for_composition=True)
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec10_CompositionIneligible") == VerdictStatus.VIOLATED


# ======================================================================
#  Cross-engine consistency
# ======================================================================

def test_casual_taxable_person_ineligible_for_composition_structurally(onto):
    """A casual taxable person is compulsorily registerable under Sec 24
    AND is structurally barred from composition - both engines should
    agree it's not a composition candidate, using the SAME Sec24Trigger
    list (imported, not re-declared) so they can't drift apart."""
    p = BusinessProfile(name="Casual Trader", state="Karnataka",
                         aggregate_turnover=Decimal("2000000"), financial_year="2025-26",
                         business_types=["Trader"], opts_for_composition=True,
                         is_casual_taxable_person=True)
    proof = run_phase2(p, onto)
    assert status_of(proof, "Sec24_CompulsoryRegistration") == VerdictStatus.VIOLATED
    assert status_of(proof, "Sec10_CompositionIneligible") == VerdictStatus.VIOLATED


def test_validation_rejects_unknown_state(onto):
    p = BusinessProfile(name="Bad State Co", state="Narnia",
                         aggregate_turnover=Decimal("1000000"), financial_year="2025-26")
    with pytest.raises(ValueError):
        run_phase2(p, onto)


def test_validation_rejects_unknown_business_type(onto):
    p = BusinessProfile(name="Bad Type Co", state="Kerala",
                         aggregate_turnover=Decimal("1000000"), financial_year="2025-26",
                         business_types=["SpaceMerchant"])
    with pytest.raises(ValueError):
        run_phase2(p, onto)
