"""
POST /api/compliance/check
================================
The route itself does no GST reasoning. It:

  1. relies on Pydantic (schemas.ComplianceCheckRequest) to validate shape,
  2. dumps the validated request to a plain JSON-safe dict,
  3. hands that dict to the EXISTING app.io.profile_loader canonical
     converter to build a real BusinessProfile,
  4. calls the EXISTING app.auditsure_pipeline.generate_explanation,
  5. serializes the real ProofObject (via its own .to_dict()) plus a
     derived phase summary, and separates a Layer 3 failure from a
     Layer 2 (compliance) failure per item 25/82.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter

from api.exceptions import ComplianceAnalysisError, ProfileValidationError
from api.schemas import ComplianceCheckRequest
from api.serialization import build_phase_summary
from app.auditsure_pipeline import run_compliance_check
from app.io.profile_loader import ProfileLoadError, load_profile_from_dict
from app.llm.layer3_explainer import Layer3ConfigurationError, Layer3Explainer
from app.ontology.ontology_loader import get_default_loader

router = APIRouter(prefix="/compliance", tags=["compliance"])


@router.post("/check")
def check_compliance(request: ComplianceCheckRequest) -> dict:
    profile_dict = request.profile.model_dump(mode="json", exclude_unset=True)

    try:
        profile = load_profile_from_dict(profile_dict)
    except ProfileLoadError as exc:
        raise ProfileValidationError(str(exc)) from exc

    as_of = request.as_of or date.today()
    onto = get_default_loader()

    try:
        proof = run_compliance_check(profile, onto, as_of_date=as_of)
    except ValueError as exc:
        # app.pipelines.phase2_pipeline.run_phase2 raises ValueError when
        # validate_against_ontology finds bad field values (unknown
        # state, business type, supply type, or registration status).
        raise ProfileValidationError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive; engines are deterministic
        raise ComplianceAnalysisError(f"Compliance analysis failed: {exc}") from exc

    explanation = None
    explanation_error = None
    try:
        explanation = Layer3Explainer().explain(proof)
    except Layer3ConfigurationError as exc:
        # A Groq/Layer-3 failure must never discard a valid deterministic
        # proof (item 25/82) - the compliance verdict below is still returned.
        explanation_error = {
            "code": "EXPLANATION_UNAVAILABLE",
            "message": str(exc),
        }

    proof_dict = proof.to_dict()

    return {
        "proof": proof_dict,
        "summary": proof_dict["summary"],
        "phases": build_phase_summary(proof),
        "explanation": explanation,
        "explanation_error": explanation_error,
        "metadata": {
            "ontology_version": proof.ontology_version,
            "generated_at": proof_dict["generated_at"],
            "financial_year": proof.financial_year,
            "business_name": proof.business_name,
            "as_of": as_of.isoformat(),
        },
    }
