"""
Phase 7 test suite - Proof Object Assembly + Layer 3 Bridge.

Prompt construction (explanation_prompt.py) is pure and deterministic,
so it's tested exhaustively without any network/credential dependency.
The Layer3Explainer's dry-run path is tested the same way. A real
(non-dry-run) API call is NOT tested here - there is no
ANTHROPIC_API_KEY in this environment - but the test suite documents
exactly what a CI environment WITH credentials would need to add
(see test_real_api_call_is_skipped_without_credentials).

Run: pytest -v test_phase7.py
"""

import os
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from auditsure_pipeline import generate_explanation, run_compliance_check
from business_profile import BusinessProfile, InvoiceRecord, RegistrationStatus
from explanation_prompt import SYSTEM_PROMPT, build_messages, build_user_prompt
from layer3_explainer import Layer3ConfigurationError, Layer3Explainer
from ontology_loader import OntologyLoader
from phase6_pipeline import run_phase6
from proof_object import ComplianceModule, ProofObject, RuleEvaluation, VerdictStatus


@pytest.fixture(scope="module")
def onto():
    return OntologyLoader()


TODAY = date(2026, 9, 10)


def make_evaluation(rule_id="R1", status=VerdictStatus.VIOLATED, citation="Sec 99, CGST Act 2017",
                     computed_value=None, threshold_value=None) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id=rule_id, module=ComplianceModule.REGISTRATION, status=status,
        legal_citation=citation, section_number="99", description="Test description.",
        computed_value=computed_value, threshold_value=threshold_value,
        explanation_hint="This is a test explanation hint.",
    )


def make_proof(*evaluations) -> ProofObject:
    p = ProofObject(business_name="Test Co", financial_year="2025-26")
    p.extend(list(evaluations))
    return p


# ======================================================================
#  Prompt construction - deterministic, no network needed
# ======================================================================

def test_empty_proof_object_says_so_plainly():
    proof = make_proof()
    prompt = build_user_prompt(proof)
    assert "No compliance findings were generated" in prompt


def test_prompt_includes_business_name_and_fy():
    proof = make_proof(make_evaluation())
    prompt = build_user_prompt(proof)
    assert "Test Co" in prompt
    assert "2025-26" in prompt


def test_prompt_groups_by_status_in_priority_order():
    """VIOLATED must appear before INDETERMINATE, which must appear
    before SATISFIED, before NOT_APPLICABLE - so an LLM reading top-down
    naturally prioritizes what matters most."""
    proof = make_proof(
        make_evaluation(rule_id="SAT1", status=VerdictStatus.SATISFIED),
        make_evaluation(rule_id="VIO1", status=VerdictStatus.VIOLATED),
        make_evaluation(rule_id="IND1", status=VerdictStatus.INDETERMINATE),
        make_evaluation(rule_id="NA1", status=VerdictStatus.NOT_APPLICABLE),
    )
    prompt = build_user_prompt(proof)
    assert (prompt.index("=== VIOLATED") < prompt.index("=== INDETERMINATE")
            < prompt.index("=== SATISFIED") < prompt.index("=== NOT_APPLICABLE"))


def test_prompt_omits_status_sections_with_no_findings():
    proof = make_proof(make_evaluation(status=VerdictStatus.VIOLATED))
    prompt = build_user_prompt(proof)
    assert "=== VIOLATED" in prompt
    assert "=== SATISFIED" not in prompt
    assert "=== INDETERMINATE" not in prompt
    assert "=== NOT_APPLICABLE" not in prompt


def test_prompt_preserves_exact_legal_citation():
    proof = make_proof(make_evaluation(citation="Sec 16(2), CGST Act 2017"))
    prompt = build_user_prompt(proof)
    assert "Sec 16(2), CGST Act 2017" in prompt


def test_prompt_includes_computed_and_threshold_values_when_present():
    proof = make_proof(make_evaluation(computed_value=2500000.0, threshold_value=2000000.0))
    prompt = build_user_prompt(proof)
    assert "2500000.0" in prompt
    assert "2000000.0" in prompt


def test_prompt_omits_computed_value_line_when_absent():
    proof = make_proof(make_evaluation(computed_value=None, threshold_value=None))
    prompt = build_user_prompt(proof)
    assert "computed_value" not in prompt
    assert "threshold_value" not in prompt


def test_system_prompt_forbids_introducing_new_legal_content():
    """Guard against someone editing the system prompt and accidentally
    weakening the core anti-hallucination guarantee."""
    assert "ONLY use facts" in SYSTEM_PROMPT
    assert "Never introduce a section number" in SYSTEM_PROMPT


def test_build_messages_shape_matches_anthropic_api():
    proof = make_proof(make_evaluation())
    messages = build_messages(proof)
    assert isinstance(messages, list)
    assert messages[0]["role"] == "user"
    assert isinstance(messages[0]["content"], str)


def test_same_proof_object_produces_identical_prompt_twice():
    """Determinism guarantee: prompt construction must not depend on
    anything except the ProofObject's own content (e.g. no hidden
    randomness or wall-clock dependence beyond what's already in the
    object)."""
    proof = make_proof(make_evaluation())
    assert build_user_prompt(proof) == build_user_prompt(proof)


# ======================================================================
#  Layer3Explainer - dry-run path (no credentials needed)
# ======================================================================

def test_auto_dry_run_when_no_api_key_present(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    explainer = Layer3Explainer()
    assert explainer.dry_run is True


def test_explicit_dry_run_overrides_present_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    explainer = Layer3Explainer(dry_run=True)
    assert explainer.dry_run is True


def test_dry_run_output_contains_system_and_user_prompt_content():
    proof = make_proof(make_evaluation(citation="Sec 42, CGST Act 2017"))
    explainer = Layer3Explainer(dry_run=True)
    output = explainer.explain(proof)
    assert "DRY RUN" in output
    assert "Sec 42, CGST Act 2017" in output
    assert "STRICT RULES" in output   # confirms the system prompt is included


def test_real_call_without_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    explainer = Layer3Explainer(dry_run=False, api_key=None)
    with pytest.raises(Layer3ConfigurationError, match="No API key configured"):
        explainer.explain(make_proof(make_evaluation()))


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="requires a real ANTHROPIC_API_KEY")
def test_real_api_call_produces_markdown_explanation(onto):
    """Documents what a CI environment WITH real credentials would run.
    Skipped here since this sandbox has no API key - this is the one
    test in the whole Layer 2/3 codebase that touches the network."""
    profile = BusinessProfile(name="Real API Test Co", state="Karnataka",
                               aggregate_turnover=Decimal("2500000"), financial_year="2025-26")
    proof = run_compliance_check(profile, onto, as_of_date=TODAY)
    explanation = Layer3Explainer(dry_run=False).explain(proof)
    assert "##" in explanation   # Markdown headers per the system prompt's format spec


# ======================================================================
#  Top-level pipeline facade
# ======================================================================

def test_run_compliance_check_matches_run_phase6(onto):
    """The facade must be a faithful pass-through, not a divergent
    re-implementation - same profile, same as_of_date, same result."""
    profile = BusinessProfile(name="Facade Test Co", state="Karnataka",
                               aggregate_turnover=Decimal("2500000"), financial_year="2025-26")
    via_facade = run_compliance_check(profile, onto, as_of_date=TODAY)
    via_phase6 = run_phase6(profile, onto, as_of_date=TODAY)
    assert via_facade.summary_counts() == via_phase6.summary_counts()
    assert [e.rule_id for e in via_facade.evaluations] == [e.rule_id for e in via_phase6.evaluations]


def test_generate_explanation_returns_proof_and_text(onto):
    profile = BusinessProfile(name="End To End Co", state="Karnataka",
                               aggregate_turnover=Decimal("2500000"), financial_year="2025-26")
    proof, explanation = generate_explanation(profile, onto, as_of_date=TODAY,
                                                explainer=Layer3Explainer(dry_run=True))
    assert isinstance(proof, ProofObject)
    assert isinstance(explanation, str)
    assert "Sec22_RegistrationLiability" in explanation


def test_generate_explanation_surfaces_validation_errors(onto):
    """A profile that fails Phase 1's ontology validation must raise
    BEFORE any (wasted) Layer 3 call is attempted."""
    profile = BusinessProfile(name="Bad Co", state="NotARealState", financial_year="2025-26")
    with pytest.raises(ValueError, match="ontology validation"):
        generate_explanation(profile, onto, as_of_date=TODAY)


def test_full_pipeline_with_a_violation_end_to_end(onto):
    profile = BusinessProfile(
        name="Violation Co", state="Karnataka", aggregate_turnover=Decimal("2500000"),
        financial_year="2025-26", registration_status=RegistrationStatus.NOT_REGISTERED,
    )
    proof, explanation = generate_explanation(profile, onto, as_of_date=TODAY,
                                                explainer=Layer3Explainer(dry_run=True))
    assert proof.violations()
    assert "VIOLATED" in explanation
    assert "Sec 22" in explanation or "Sec22" in explanation
