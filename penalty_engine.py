"""
AuditSure Layer 2 - Phase 6b: Penalty Engine (Sec 122)
============================================================
Deliberately narrow scope: only the two Sec 122(1) offence categories
that are BOTH already-modelled in the ontology (WrongfulITCOffence,
FailureToRegisterOffence) AND fully derivable from facts this system
already computes (Phase 4's ITC violations, Phase 2's registration
violations). Sec 122(1) lists 21 offences in total; the other 19
(invoice violations, obstruction of officers, tampering with evidence,
etc.) require facts BusinessProfile has no way of capturing (e.g. "did
you obstruct a proper officer") and are therefore NOT modelled here -
asserting a penalty for an offence category we cannot actually verify
would be exactly the kind of unfounded legal claim this project's
"never invent" rule exists to prevent.

Like the interest engine, this reads Phase 2 and Phase 4's already-
computed ProofObject findings rather than re-deriving eligibility -
the penalty is attached to a violation that another engine already
established, not re-discovered from raw facts here.
"""

from __future__ import annotations

from business_profile import BusinessProfile
from ontology_loader import OntologyLoader
from proof_object import ComplianceModule, ProofObject, RuleEvaluation, VerdictStatus

FLAT_PENALTY_FLOOR = 10_000.0   # Rs 10,000 - the Sec 122(1) floor penalty


class PenaltyEngine:

    def __init__(self, onto: OntologyLoader):
        self.onto = onto

    def evaluate(self, profile: BusinessProfile, prior_proof: ProofObject) -> list[RuleEvaluation]:
        return [
            *self._wrongful_itc_penalties(profile, prior_proof),
            *self._failure_to_register_penalty(prior_proof),
        ]

    # -- Sec 122(1)(vii)-(x): wrongful ITC availment --------------------------

    def _wrongful_itc_penalties(self, profile: BusinessProfile, prior_proof: ProofObject) -> list[RuleEvaluation]:
        offence = self.onto.get_class_info("WrongfulITCOffence")
        invoices_by_number = {inv.invoice_number: inv for inv in profile.inward_invoices}
        evaluations = []
        for e in prior_proof.by_status(VerdictStatus.VIOLATED):
            if e.module != ComplianceModule.INPUT_TAX_CREDIT:
                continue
            if not (e.rule_id.startswith("Sec16_2_ITCEligibility_") or e.rule_id.startswith("Sec17_5_BlockedCredit_")):
                continue
            invoice_number = e.inputs_used.get("invoice_number")
            invoice = invoices_by_number.get(invoice_number)
            if invoice is None:
                continue
            tax_amount = float(invoice.tax_amount)
            penalty = max(FLAT_PENALTY_FLOOR, tax_amount)

            evaluations.append(RuleEvaluation(
                rule_id=f"Sec122_WrongfulITCPenalty_{invoice_number}",
                module=ComplianceModule.FINANCIAL_CONSEQUENCES,
                status=VerdictStatus.VIOLATED,
                legal_citation=offence.citation or "Sec 122(1), CGST Act 2017",
                section_number="122",
                description="Sec 122(1) penalty for wrongful ITC availment (higher of Rs 10,000 or tax wrongly availed).",
                inputs_used={"invoice_number": invoice_number, "tax_amount": tax_amount, "source_finding": e.rule_id},
                computed_value=penalty,
                threshold_value=FLAT_PENALTY_FLOOR,
                explanation_hint=(
                    f"Invoice {invoice_number}'s wrongly availed ITC of Rs {tax_amount:,.2f} attracts a "
                    f"Sec 122(1) penalty of Rs {penalty:,.2f} (the higher of Rs 10,000 or the ITC wrongly "
                    f"availed), under {offence.citation}."
                ),
            ))
        return evaluations

    # -- Sec 122(1)(xi): failure to register -----------------------------------

    def _failure_to_register_penalty(self, prior_proof: ProofObject) -> list[RuleEvaluation]:
        offence = self.onto.get_class_info("FailureToRegisterOffence")
        triggers = [
            e for e in prior_proof.by_status(VerdictStatus.VIOLATED)
            if e.module == ComplianceModule.REGISTRATION
            and e.rule_id in ("Sec22_RegistrationLiability", "Sec24_CompulsoryRegistration")
        ]
        if not triggers:
            return []

        return [RuleEvaluation(
            rule_id="Sec122_FailureToRegisterPenalty",
            module=ComplianceModule.FINANCIAL_CONSEQUENCES,
            status=VerdictStatus.VIOLATED,
            legal_citation=offence.citation or "Sec 122(1)(xi), CGST Act 2017",
            section_number="122",
            description="Sec 122(1)(xi) penalty for failure to register when liable.",
            inputs_used={"source_finding": triggers[0].rule_id},
            computed_value=FLAT_PENALTY_FLOOR,
            threshold_value=FLAT_PENALTY_FLOOR,
            explanation_hint=(
                f"A minimum Sec 122(1)(xi) penalty of Rs {FLAT_PENALTY_FLOOR:,.0f} applies for failure to "
                f"register when liable, under {offence.citation}. The actual penalty may be higher (the higher "
                f"of Rs 10,000 or the tax evaded) - the tax-evaded component is not quantified here since it "
                f"depends on the applicable GST rate, which is outside this system's modelled scope."
            ),
        )]
