"""
AuditSure Layer 2 - Phase 2 Pipeline
========================================
Wires RegistrationEngine + CompositionEngine together against one
BusinessProfile and returns a fully-populated ProofObject. This is the
function Phase 3+ engines will slot into (each just appends its own
evaluations onto the same ProofObject), and the one a future API/CLI
layer would call directly.
"""

from __future__ import annotations

from business_profile import BusinessProfile, validate_against_ontology
from composition_engine import CompositionEngine
from ontology_loader import OntologyLoader, get_default_loader
from proof_object import ProofObject


def run_phase2(profile: BusinessProfile, onto: OntologyLoader | None = None) -> ProofObject:
    from registration_engine import RegistrationEngine   # local import: avoids a module-load cycle
                                                            # with composition_engine importing SEC24_TRIGGERS

    onto = onto or get_default_loader()

    warnings = validate_against_ontology(profile, onto)
    if warnings:
        raise ValueError(
            f"BusinessProfile '{profile.name}' failed ontology validation: {warnings}"
        )

    proof = ProofObject(business_name=profile.name, financial_year=profile.financial_year,
                         ontology_version=onto.get_version())

    registration_engine = RegistrationEngine(onto)
    proof.extend(registration_engine.evaluate(profile))

    composition_engine = CompositionEngine(onto)
    proof.extend(composition_engine.evaluate(profile))

    return proof


if __name__ == "__main__":
    from decimal import Decimal

    sample = BusinessProfile(
        name="Demo Trader",
        state="Karnataka",
        aggregate_turnover=Decimal("8000000"),
        financial_year="2025-26",
        business_types=["Trader"],
        opts_for_composition=True,
    )
    proof = run_phase2(sample)
    print(proof.to_json())
