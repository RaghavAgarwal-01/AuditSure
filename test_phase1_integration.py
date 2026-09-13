"""
Phase 1 integration test.

This does NOT contain real Z3 constraint logic yet (that's Phase 2).
It proves the three Phase 1 contracts - OntologyLoader, BusinessProfile,
ProofObject - fit together correctly:

  1. A BusinessProfile can be built and validated against live ontology data.
  2. A hand-written "mini rule" (standing in for what Phase 2's Z3 module
     will compute) can pull a real Threshold out of the ontology and
     produce a properly-shaped RuleEvaluation.
  3. The resulting ProofObject serializes to clean JSON.

Run: python3 test_phase1_integration.py
"""

from decimal import Decimal

from business_profile import BusinessProfile, RegistrationStatus, validate_against_ontology
from ontology_loader import OntologyLoader
from proof_object import ComplianceModule, ProofObject, RuleEvaluation, VerdictStatus


def build_sample_profiles() -> list[BusinessProfile]:
    return [
        BusinessProfile(
            name="Sharma Textiles",
            pan="ABCDE1234F",
            state="Maharashtra",
            aggregate_turnover=Decimal("2500000"),   # Rs 25 lakh
            financial_year="2025-26",
            business_types=["Trader"],
            registration_status=RegistrationStatus.NOT_REGISTERED,
        ),
        BusinessProfile(
            name="Northeast Handicrafts",
            pan="XYZAB5678K",
            state="Manipur",                          # special-category state
            aggregate_turnover=Decimal("1200000"),    # Rs 12 lakh
            financial_year="2025-26",
            business_types=["Manufacturer"],
            registration_status=RegistrationStatus.NOT_REGISTERED,
        ),
        BusinessProfile(
            name="Bogus BusinessType Co",
            state="Nowhereland",                      # deliberately invalid, to test validation
            aggregate_turnover=Decimal("500000"),
            financial_year="2025-26",
            business_types=["SpaceMerchant"],          # deliberately invalid
        ),
    ]


def evaluate_registration_liability_stub(profile: BusinessProfile, onto: OntologyLoader) -> RuleEvaluation:
    """STAND-IN for Phase 2's real Sec 22 Z3 constraint. Demonstrates the
    exact shape Phase 2 must produce: pull the threshold from the
    ontology (never hardcode it), compare, and emit a RuleEvaluation."""
    sec22 = onto.get_section("22")

    if onto.is_special_category_state(profile.state):
        threshold = onto.get_threshold("ThresholdRegistrationSpecialCategory10L")
    else:
        threshold = onto.get_threshold("ThresholdRegistrationGeneral20L")

    turnover = float(profile.aggregate_turnover)
    exceeds = turnover > threshold.amount

    return RuleEvaluation(
        rule_id="Sec22_RegistrationLiability",
        module=ComplianceModule.REGISTRATION,
        status=VerdictStatus.VIOLATED if (exceeds and profile.registration_status == RegistrationStatus.NOT_REGISTERED) else VerdictStatus.SATISFIED,
        legal_citation=threshold.citation or sec22.title,
        section_number=sec22.number,
        description=f"Registration liability check under Sec {sec22.number} against {threshold.label}.",
        inputs_used={"aggregate_turnover": turnover, "state": profile.state, "registration_status": profile.registration_status.value},
        computed_value=turnover,
        threshold_value=threshold.amount,
        threshold_id=threshold.id,
        explanation_hint=(
            f"{profile.name}'s aggregate turnover of Rs {turnover:,.0f} "
            f"{'exceeds' if exceeds else 'does not exceed'} the Rs {threshold.amount:,.0f} "
            f"threshold under {threshold.citation}, so registration is "
            f"{'mandatory' if exceeds else 'not yet mandatory (voluntary registration remains available)'}."
        ),
    )


def main():
    onto = OntologyLoader()
    print(f"Ontology loaded: {len(onto.get_all_thresholds())} thresholds, "
          f"{len(onto.get_all_sections())} sections, {len(onto.get_all_states())} states.\n")

    for profile in build_sample_profiles():
        print(f"--- {profile.name} ---")

        warnings = validate_against_ontology(profile, onto)
        if warnings:
            print("  Validation warnings:")
            for w in warnings:
                print("   -", w)
            print("  (skipping rule evaluation for an invalid profile)\n")
            continue

        proof = ProofObject(business_name=profile.name, financial_year=profile.financial_year)
        proof.add(evaluate_registration_liability_stub(profile, onto))

        print("  Summary:", proof.summary_counts())
        for e in proof.evaluations:
            print(f"  [{e.status.value}] {e.explanation_hint}")

        out_path = f"proof_{profile.name.replace(' ', '_')}.json"
        proof.save(out_path)
        print(f"  Saved -> {out_path}\n")


if __name__ == "__main__":
    main()
