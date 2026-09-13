"""
AuditSure Layer 2 - Phase 6c: Refund Engine (Sec 54)
==========================================================
For each BusinessProfile.refund_claims entry, checks:
  1. The 2-year limitation period from the claim's relevant date.
  2. Whether documentary evidence of no unjust enrichment is required
     (waived - self-declaration suffices - for claims not exceeding
     Rs 2 lakh).
  3. For zero-rated-supply claims specifically, notes the 90%
     provisional-refund entitlement within 60 days.
"""

from __future__ import annotations

from app.models.business_profile import BusinessProfile, RefundClaim
from app.ontology.ontology_loader import OntologyLoader
from app.models.proof_object import ComplianceModule, RuleEvaluation, VerdictStatus


def _add_years(d, years: int):
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # 29 Feb + N years landing on a non-leap year - fall back to 28 Feb
        return d.replace(month=2, day=28, year=d.year + years)


class RefundEngine:

    def __init__(self, onto: OntologyLoader):
        self.onto = onto

    def evaluate(self, profile: BusinessProfile) -> list[RuleEvaluation]:
        evaluations: list[RuleEvaluation] = []
        for claim in profile.refund_claims:
            evaluations.append(self._limitation_check(claim))
            evaluations.append(self._documentary_evidence_check(claim))
            provisional = self._provisional_refund_note(claim)
            if provisional:
                evaluations.append(provisional)
        return evaluations

    # -- 2-year limitation period ---------------------------------------------

    def _limitation_check(self, claim: RefundClaim) -> RuleEvaluation:
        limitation = self.onto.get_threshold("ThresholdRefundLimitationPeriod2Yr")
        years = int(limitation.amount)
        deadline = _add_years(claim.relevant_date, years)

        if claim.filing_date is None:
            status = VerdictStatus.INDETERMINATE
            explanation = (
                f"Refund claim {claim.claim_id}: no filing date on record, so the Sec 54(1) 2-year limitation "
                f"check (deadline {deadline.isoformat()}, from relevant date {claim.relevant_date.isoformat()}) "
                f"cannot be verified."
            )
        else:
            within_time = claim.filing_date <= deadline
            status = VerdictStatus.SATISFIED if within_time else VerdictStatus.VIOLATED
            explanation = (
                f"Refund claim {claim.claim_id} of Rs {float(claim.claim_amount):,.2f} was filed on "
                f"{claim.filing_date.isoformat()}, "
                + (
                    f"within the Sec 54(1) 2-year limitation deadline of {deadline.isoformat()}."
                    if within_time else
                    f"AFTER the Sec 54(1) 2-year limitation deadline of {deadline.isoformat()} - this claim is "
                    f"time-barred."
                )
            )

        return RuleEvaluation(
            rule_id=f"Sec54_1_LimitationPeriod_{claim.claim_id}",
            module=ComplianceModule.FINANCIAL_CONSEQUENCES,
            status=status,
            legal_citation=limitation.citation or "Sec 54(1), CGST Act 2017",
            section_number="54",
            description="Sec 54(1) 2-year refund claim limitation period check.",
            inputs_used={
                "claim_id": claim.claim_id, "claim_type": claim.claim_type,
                "relevant_date": claim.relevant_date.isoformat(), "deadline": deadline.isoformat(),
                "filing_date": claim.filing_date.isoformat() if claim.filing_date else None,
            },
            computed_value=float(claim.claim_amount),
            explanation_hint=explanation,
        )

    # -- Rs 2 lakh documentary evidence waiver --------------------------------

    def _documentary_evidence_check(self, claim: RefundClaim) -> RuleEvaluation:
        waiver_threshold = self.onto.get_threshold("ThresholdRefundDocEvidenceWaiver2L")
        amount = float(claim.claim_amount)
        waived = amount <= waiver_threshold.amount

        return RuleEvaluation(
            rule_id=f"Sec54_4_DocEvidenceWaiver_{claim.claim_id}",
            module=ComplianceModule.FINANCIAL_CONSEQUENCES,
            status=VerdictStatus.SATISFIED if waived else VerdictStatus.INDETERMINATE,
            legal_citation=waiver_threshold.citation or "Sec 54(4) proviso, CGST Act 2017",
            section_number="54",
            description="Sec 54(4) proviso documentary-evidence-of-no-unjust-enrichment waiver check.",
            inputs_used={"claim_id": claim.claim_id, "claim_amount": amount},
            computed_value=amount,
            threshold_value=waiver_threshold.amount,
            threshold_id=waiver_threshold.id,
            explanation_hint=(
                f"Refund claim {claim.claim_id} of Rs {amount:,.2f} "
                + (
                    f"does not exceed the Rs {waiver_threshold.amount:,.0f} threshold, so a self-declaration "
                    f"of no unjust enrichment suffices under {waiver_threshold.citation} - no further "
                    f"documentary evidence is required."
                    if waived else
                    f"exceeds the Rs {waiver_threshold.amount:,.0f} threshold, so documentary evidence "
                    f"establishing no unjust enrichment must be furnished under {waiver_threshold.citation} "
                    f"- confirm this evidence is available before filing."
                )
            ),
        )

    # -- 90% provisional refund note (zero-rated claims only) -----------------

    def _provisional_refund_note(self, claim: RefundClaim) -> RuleEvaluation | None:
        if claim.claim_type != "ZeroRatedITC":
            return None
        provisional = self.onto.get_threshold("ThresholdRefundProvisional90Pct")
        amount = float(claim.claim_amount)
        provisional_amount = amount * (provisional.amount / 100.0)

        return RuleEvaluation(
            rule_id=f"Sec54_6_ProvisionalRefund_{claim.claim_id}",
            module=ComplianceModule.FINANCIAL_CONSEQUENCES,
            status=VerdictStatus.SATISFIED,
            legal_citation=provisional.citation or "Sec 54(6), CGST Act 2017",
            section_number="54",
            description="Sec 54(6) provisional refund entitlement for zero-rated-supply ITC claims.",
            inputs_used={"claim_id": claim.claim_id, "claim_amount": amount},
            computed_value=provisional_amount,
            threshold_value=provisional.amount,
            threshold_id=provisional.id,
            explanation_hint=(
                f"Refund claim {claim.claim_id} is a zero-rated-supply ITC claim, so up to "
                f"{provisional.amount:.0f}% (approximately Rs {provisional_amount:,.2f}) may be granted "
                f"provisionally within 60 days of acknowledgment under {provisional.citation}, with the "
                f"balance sanctioned after verification."
            ),
        )
