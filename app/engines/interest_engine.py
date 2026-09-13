"""
AuditSure Layer 2 - Phase 6a: Interest Engine (Sec 50)
============================================================
Two distinct interest triggers, at two different rates:

  1. Sec 50(1) - 18% p.a. on tax paid after the due date, computed (post
     the 2021 amendment) ONLY on the portion actually paid by debiting
     the electronic CASH ledger, not the full liability. Uses
     BusinessProfile.tax_payment_records.

  2. Sec 50(3) - 24% p.a. where ITC has been wrongly availed AND
     UTILISED (both conditions - availed alone is not enough). This is
     the first Phase 6 engine to consume a PRIOR PHASE'S ProofObject
     directly, rather than only raw BusinessProfile data: it scans
     Phase 4's already-computed VIOLATED input-tax-credit evaluations
     (Sec 16(2) ineligibility, Sec 17(5) blocked credit, 180-day
     reversal, Sec 16(4) time-bar) and, for each one where the
     underlying invoice was also actually UTILISED, computes 24%
     interest from the claim date to the evaluation date. This is
     deliberate: Phase 4 already did the legal work of determining
     WHICH ITC is wrongly availed - Phase 6 would be duplicating (and
     risking drifting from) that logic if it re-derived eligibility
     from scratch instead of reading Phase 4's verdicts.

Interest is computed on a simple daily-rate basis (rate% x principal x
days/365), which is how Sec 50 interest is computed in practice.
"""

from __future__ import annotations

from datetime import date

from app.models.business_profile import BusinessProfile, InvoiceRecord
from app.ontology.ontology_loader import OntologyLoader
from app.models.proof_object import ComplianceModule, ProofObject, RuleEvaluation, VerdictStatus

ITC_VIOLATION_RULE_PREFIXES = (
    "Sec16_2_ITCEligibility_",
    "Sec17_5_BlockedCredit_",
    "Sec16_2_Proviso_180Day_",
    "Sec16_4_TimeBar_",
)


def _simple_interest(principal: float, annual_rate_pct: float, days: int) -> float:
    return principal * (annual_rate_pct / 100.0) * (days / 365.0)


class InterestEngine:

    def __init__(self, onto: OntologyLoader, as_of_date: date | None = None):
        self.onto = onto
        self.as_of_date = as_of_date or date.today()

    def evaluate(self, profile: BusinessProfile, prior_proof: ProofObject) -> list[RuleEvaluation]:
        evaluations: list[RuleEvaluation] = []
        for record in profile.tax_payment_records:
            ev = self._delayed_payment_interest(record)
            if ev:
                evaluations.append(ev)
        evaluations.extend(self._wrongly_availed_itc_interest(profile, prior_proof))
        return evaluations

    # -- Sec 50(1): 18% on delayed cash-ledger payment ------------------------

    def _delayed_payment_interest(self, record) -> RuleEvaluation | None:
        if record.payment_date is None or record.payment_date <= record.due_date:
            return None   # not yet paid (nothing to compute) or paid on/before due date (no interest)

        rate = self.onto.get_threshold("ThresholdInterestDelayedPayment18Pct")
        days_late = (record.payment_date - record.due_date).days
        principal = float(record.amount_paid_via_cash_ledger)
        interest = _simple_interest(principal, rate.amount, days_late)

        return RuleEvaluation(
            rule_id=f"Sec50_1_DelayedPaymentInterest_{record.return_period}",
            module=ComplianceModule.FINANCIAL_CONSEQUENCES,
            status=VerdictStatus.VIOLATED,
            legal_citation=rate.citation or "Sec 50(1), CGST Act 2017",
            section_number="50",
            description="Sec 50(1) interest on tax paid after the due date (cash-ledger portion only).",
            inputs_used={
                "return_period": record.return_period,
                "days_late": days_late,
                "amount_paid_via_cash_ledger": principal,
            },
            computed_value=principal,
            threshold_value=rate.amount,
            threshold_id=rate.id,
            explanation_hint=(
                f"Return period {record.return_period}: Rs {principal:,.2f} was paid via the cash ledger "
                f"{days_late} days after the due date ({record.due_date.isoformat()}), attracting interest "
                f"at {rate.amount:.0f}% p.a. under {rate.citation}: approximately Rs {interest:,.2f}."
            ),
        )

    # -- Sec 50(3): 24% on wrongly availed AND utilised ITC -------------------

    def _wrongly_availed_itc_interest(self, profile: BusinessProfile, prior_proof: ProofObject) -> list[RuleEvaluation]:
        invoices_by_number = {inv.invoice_number: inv for inv in profile.inward_invoices}
        rate = self.onto.get_threshold("ThresholdInterestWrongITC24Pct")

        flagged_invoice_numbers: set[str] = set()
        for e in prior_proof.by_status(VerdictStatus.VIOLATED):
            if e.module != ComplianceModule.INPUT_TAX_CREDIT:
                continue
            if not any(e.rule_id.startswith(p) for p in ITC_VIOLATION_RULE_PREFIXES):
                continue
            invoice_number = e.inputs_used.get("invoice_number")
            if invoice_number:
                flagged_invoice_numbers.add(invoice_number)

        evaluations = []
        for invoice_number in sorted(flagged_invoice_numbers):
            invoice = invoices_by_number.get(invoice_number)
            if invoice is None or not invoice.itc_utilized:
                continue   # Sec 50(3) requires UTILISATION, not just availment - "availed only" attracts no interest
            if invoice.itc_claim_date is None:
                continue   # can't compute a day-count without a starting date

            days = (self.as_of_date - invoice.itc_claim_date).days
            if days <= 0:
                continue
            principal = float(invoice.tax_amount)
            interest = _simple_interest(principal, rate.amount, days)

            evaluations.append(RuleEvaluation(
                rule_id=f"Sec50_3_WronglyAvailedITCInterest_{invoice_number}",
                module=ComplianceModule.FINANCIAL_CONSEQUENCES,
                status=VerdictStatus.VIOLATED,
                legal_citation=rate.citation or "Sec 50(3), CGST Act 2017",
                section_number="50",
                description="Sec 50(3) interest on ITC wrongly availed AND utilised (per Phase 4's eligibility findings).",
                inputs_used={"invoice_number": invoice_number, "tax_amount": principal, "days": days},
                computed_value=principal,
                threshold_value=rate.amount,
                threshold_id=rate.id,
                explanation_hint=(
                    f"Invoice {invoice_number}: ITC of Rs {principal:,.2f} was found wrongly availed (see the "
                    f"corresponding Input Tax Credit module finding) and has been utilised, attracting interest "
                    f"at {rate.amount:.0f}% p.a. under {rate.citation} for {days} days: approximately "
                    f"Rs {interest:,.2f}."
                ),
            ))
        return evaluations
