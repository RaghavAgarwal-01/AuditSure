"""
AuditSure - Top-Level Pipeline (Layer 2 Facade + Layer 3 Bridge)
======================================================================
This is THE stable entry point for the rest of the system (a future
API, CLI, or UI) to call. It deliberately hides the phaseN_pipeline
chain (run_phase2 -> run_phase3 -> ... -> run_phase6) behind one
function, so callers never need to know how many phases exist or in
what order they run - that internal structure is free to change as
more phases are added without breaking any caller.

Two functions:
  - run_compliance_check(profile)  -> ProofObject   (Layer 2 only)
  - generate_explanation(profile)  -> str            (Layer 2 + Layer 3)
"""

from __future__ import annotations

from datetime import date

from business_profile import BusinessProfile
from layer3_explainer import Layer3Explainer
from ontology_loader import OntologyLoader, get_default_loader
from phase6_pipeline import run_phase6
from proof_object import ProofObject


def run_compliance_check(profile: BusinessProfile, onto: OntologyLoader | None = None,
                          as_of_date: date | None = None) -> ProofObject:
    """Runs every Layer 2 compliance module (registration, composition,
    supply classification, levy mechanism, ITC, compliance obligations,
    interest, penalty, refund, appeal) against one BusinessProfile and
    returns the single aggregated ProofObject. This is the complete
    Layer 2 output - the "verified proof object" the AuditSure
    architecture hands to Layer 3."""
    onto = onto or get_default_loader()
    return run_phase6(profile, onto, as_of_date=as_of_date)


def generate_explanation(profile: BusinessProfile, onto: OntologyLoader | None = None,
                          as_of_date: date | None = None,
                          explainer: Layer3Explainer | None = None) -> tuple[ProofObject, str]:
    """Runs the full Layer 2 check, then passes the resulting ProofObject
    to Layer 3 for a plain-English explanation. Returns BOTH the proof
    object (for a UI to render structured data / audit trail) and the
    explanation text (for display to the business owner)."""
    proof = run_compliance_check(profile, onto, as_of_date=as_of_date)
    explainer = explainer or Layer3Explainer()
    explanation = explainer.explain(proof)
    return proof, explanation


if __name__ == "__main__":
    from decimal import Decimal

    onto = get_default_loader()
    profile = BusinessProfile(
        name="Priya Fashions", state="TamilNadu",
        aggregate_turnover=Decimal("1800000"), financial_year="2025-26",
        business_types=["Trader"], opts_for_composition=True,
    )
    proof, explanation = generate_explanation(profile, onto, as_of_date=date(2026, 9, 10))

    print(f"=== Layer 2 Proof Object: {proof.summary_counts()} ===\n")
    print(f"=== Layer 3 Explanation ===\n{explanation}")
