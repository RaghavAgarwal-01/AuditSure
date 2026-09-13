"""
AuditSure Layer 2 - Phase 4: Input Tax Credit Engine
=========================================================
Evaluates BusinessProfile.inward_invoices against:

  1. Sec 16(2)(a)/(aa)/(b)/(c)/(d) - all FIVE conditions must hold for
     ITC to be validly available on an invoice. Modelled as a single Z3
     conjunction (not a chain of Python `if`s) so "ALL of the following"
     is enforced structurally rather than by an easily-miscounted list
     of nested conditionals.
  2. Sec 17(5) blocked credit - an independent, absolute bar that
     applies BEFORE Sec 16(2) is even considered (a blocked category is
     never eligible no matter how perfectly the five conditions are met).
  3. Sec 16(2) second proviso / Rule 37 - the 180-day payment rule:
     ITC must be reversed (with interest) if the recipient hasn't paid
     the supplier within 180 days of the invoice.
  4. Sec 16(4) time bar - ITC cannot be validly claimed after 30
     November following the end of the relevant financial year, or the
     date of furnishing the Sec 44 annual return for that year, if
     earlier.

STATUS SEMANTICS (kept consistent with Phases 2/3): VIOLATED means an
ACTIONABLE compliance problem exists right now (ITC claimed but not
actually entitled, or entitlement window already lost) - not merely
"not yet eligible". An invoice that simply isn't eligible YET (e.g.
supplier hasn't filed their return, payment still within the 180-day
window) is INDETERMINATE: nothing wrong has happened, but the position
isn't resolved either.

LIMITATION (documented rather than silently assumed): the 180-day rule
does not apply to reverse-charge supplies, to Schedule I supplies made
without consideration, or to amounts added under Sec 15(2)(b) - the
source manual's extracted text establishes the general rule but not
these carve-out mechanics, so they are not modelled. See
Layer2_README.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from z3 import And, Bool, Not, Or, Solver, sat

from business_profile import BusinessProfile, InvoiceRecord
from ontology_loader import OntologyLoader
from proof_object import ComplianceModule, RuleEvaluation, VerdictStatus

DAYS_180 = 180


@dataclass(frozen=True)
class Sec16_2_Condition:
    field_name: str
    ontology_individual: str
    paragraph: str


SEC16_2_CONDITIONS: tuple[Sec16_2_Condition, ...] = (
    Sec16_2_Condition("has_tax_invoice_or_debit_note", "PossessionOfTaxInvoice", "Sec 16(2)(a)"),
    Sec16_2_Condition("invoice_details_communicated_37_38", "InvoiceDetailsCommunicated", "Sec 16(2)(aa)"),
    Sec16_2_Condition("goods_or_services_received", "ReceiptOfGoodsOrServices", "Sec 16(2)(b)"),
    Sec16_2_Condition("tax_paid_by_supplier_to_government", "TaxActuallyPaidToGovernment", "Sec 16(2)(c)"),
    Sec16_2_Condition("supplier_has_filed_return", "ReturnFurnished", "Sec 16(2)(d)"),
)


def financial_year_of(d: date) -> str:
    """Indian FY runs 1 April - 31 March. 15 June 2025 -> '2025-26'."""
    if d.month >= 4:
        start = d.year
    else:
        start = d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def sec16_4_deadline(fy: str, annual_return_filed_dates: dict[str, date]) -> date:
    """30 November following the end of FY, or the Sec 44 annual return
    filing date for that FY if earlier."""
    fy_end_year = int(fy.split("-")[0]) + 1
    november_30 = date(fy_end_year, 11, 30)
    filed = annual_return_filed_dates.get(fy)
    if filed is not None and filed < november_30:
        return filed
    return november_30


class ITCEligibilityEngine:
    """Z3-backed evaluator for Sec 16(2)/16(4)/17(5) on inward invoices."""

    def __init__(self, onto: OntologyLoader, as_of_date: date | None = None):
        self.onto = onto
        self.as_of_date = as_of_date or date.today()
        self._condition_labels = {
            c.field_name: onto.get_class_info(c.ontology_individual).label or c.ontology_individual
            for c in SEC16_2_CONDITIONS
        }

    def evaluate(self, profile: BusinessProfile) -> list[RuleEvaluation]:
        evaluations: list[RuleEvaluation] = []
        for invoice in profile.inward_invoices:
            if profile.opts_for_composition:
                evaluations.append(self._composition_itc_bar(profile, invoice))
                continue   # Sec 10(4) is an absolute bar - Sec 16(2)/17(5)/180-day/16(4) are all moot
            evaluations.append(self._eligibility_or_block(invoice))
            payment_eval = self._180_day_rule(invoice)
            if payment_eval:
                evaluations.append(payment_eval)
            time_bar_eval = self._sec16_4_time_bar(profile, invoice)
            if time_bar_eval:
                evaluations.append(time_bar_eval)
        return evaluations

    # -- Sec 10(4): composition taxpayers cannot claim ANY ITC ----------------

    def _composition_itc_bar(self, profile: BusinessProfile, invoice: InvoiceRecord) -> RuleEvaluation:
        return RuleEvaluation(
            rule_id=f"Sec10_4_CompositionITCBar_{invoice.invoice_number}",
            module=ComplianceModule.INPUT_TAX_CREDIT,
            status=VerdictStatus.VIOLATED if invoice.itc_claimed else VerdictStatus.NOT_APPLICABLE,
            legal_citation="Sec 10(4), CGST Act 2017",
            section_number="10",
            description="Sec 10(4) absolute bar on ITC for composition taxpayers (independent of Sec 16(2)/17(5)).",
            inputs_used={"invoice_number": invoice.invoice_number, "itc_claimed": invoice.itc_claimed},
            explanation_hint=(
                f"{profile.name} has opted for the composition levy, so under Sec 10(4) it is not entitled to "
                f"ANY input tax credit at all - this is an absolute bar independent of whether invoice "
                f"{invoice.invoice_number} would otherwise satisfy Sec 16(2)'s conditions."
                + (
                    f" ITC has been claimed on this invoice anyway and must be reversed."
                    if invoice.itc_claimed else
                    " No ITC has been claimed here, which is correct."
                )
            ),
        )

    # -- 1 & 2: Sec 17(5) block (absolute bar) then Sec 16(2) (all-of) -------

    def _eligibility_or_block(self, invoice: InvoiceRecord) -> RuleEvaluation:
        if invoice.is_blocked_credit_category:
            return RuleEvaluation(
                rule_id=f"Sec17_5_BlockedCredit_{invoice.invoice_number}",
                module=ComplianceModule.INPUT_TAX_CREDIT,
                status=VerdictStatus.VIOLATED if invoice.itc_claimed else VerdictStatus.NOT_APPLICABLE,
                legal_citation="Sec 17(5), CGST Act 2017",
                section_number="17",
                description="Sec 17(5) blocked credit check (absolute bar, independent of Sec 16(2)).",
                inputs_used={
                    "invoice_number": invoice.invoice_number,
                    "blocked_credit_reason": invoice.blocked_credit_reason,
                    "itc_claimed": invoice.itc_claimed,
                },
                explanation_hint=(
                    f"Invoice {invoice.invoice_number} falls under a Sec 17(5) blocked-credit category"
                    + (f" ({invoice.blocked_credit_reason})" if invoice.blocked_credit_reason else "")
                    + (
                        ", and ITC has been claimed on it - this must be reversed; ITC on blocked categories "
                        "is never available, regardless of invoice/payment/return status."
                        if invoice.itc_claimed else
                        ", so ITC is not available on it regardless of invoice/payment/return status. "
                        "No ITC has been claimed here, so no corrective action is needed."
                    )
                ),
            )

        # -- Sec 16(2): Z3 conjunction of all five conditions -----------------
        cond_vars = {c.field_name: Bool(c.field_name) for c in SEC16_2_CONDITIONS}
        eligible = Bool("eligible")
        s = Solver()
        s.add(eligible == And(*cond_vars.values()))
        for c in SEC16_2_CONDITIONS:
            s.add(cond_vars[c.field_name] == bool(getattr(invoice, c.field_name)))
        assert s.check() == sat
        is_eligible = bool(s.model().eval(eligible))

        failed = [c for c in SEC16_2_CONDITIONS if not getattr(invoice, c.field_name)]

        if is_eligible:
            status = VerdictStatus.SATISFIED
            explanation = (
                f"Invoice {invoice.invoice_number}: all five Sec 16(2) conditions are satisfied "
                f"({', '.join(c.paragraph for c in SEC16_2_CONDITIONS)}), so ITC of Rs "
                f"{float(invoice.tax_amount):,.2f} is validly available."
            )
        elif invoice.itc_claimed:
            status = VerdictStatus.VIOLATED
            failed_desc = "; ".join(f"{c.paragraph} ({self._condition_labels[c.field_name]})" for c in failed)
            explanation = (
                f"Invoice {invoice.invoice_number}: ITC of Rs {float(invoice.tax_amount):,.2f} has been "
                f"claimed, but the following Sec 16(2) condition(s) are NOT met: {failed_desc}. "
                f"This ITC has been wrongly availed and should be reversed."
            )
        else:
            status = VerdictStatus.INDETERMINATE
            failed_desc = "; ".join(f"{c.paragraph} ({self._condition_labels[c.field_name]})" for c in failed)
            explanation = (
                f"Invoice {invoice.invoice_number} is not yet eligible for ITC: {failed_desc} not yet "
                f"satisfied. No ITC has been claimed, so there is no compliance breach - claim only once "
                f"all Sec 16(2) conditions are met."
            )

        return RuleEvaluation(
            rule_id=f"Sec16_2_ITCEligibility_{invoice.invoice_number}",
            module=ComplianceModule.INPUT_TAX_CREDIT,
            status=status,
            legal_citation="Sec 16(2), CGST Act 2017",
            section_number="16",
            description="Sec 16(2)(a)/(aa)/(b)/(c)/(d) ITC eligibility check (all conditions required).",
            inputs_used={
                "invoice_number": invoice.invoice_number,
                "tax_amount": float(invoice.tax_amount),
                "itc_claimed": invoice.itc_claimed,
                "failed_conditions": [c.field_name for c in failed],
            },
            computed_value=float(invoice.tax_amount) if is_eligible else 0.0,
            explanation_hint=explanation,
        )

    # -- 3: 180-day payment rule (Sec 16(2) second proviso; Rule 37) --------

    def _180_day_rule(self, invoice: InvoiceRecord) -> RuleEvaluation | None:
        if invoice.is_blocked_credit_category:
            return None   # already blocked outright - the 180-day rule is moot

        if invoice.payment_made_to_supplier and invoice.payment_date:
            days_taken = (invoice.payment_date - invoice.invoice_date).days
            paid_within = Bool("paid_within_180")
            s = Solver()
            s.add(paid_within == (days_taken <= DAYS_180))
            assert s.check() == sat
            within = bool(s.model().eval(paid_within))
            if within:
                return RuleEvaluation(
                    rule_id=f"Sec16_2_Proviso_180Day_{invoice.invoice_number}",
                    module=ComplianceModule.INPUT_TAX_CREDIT,
                    status=VerdictStatus.SATISFIED,
                    legal_citation="Second proviso to Sec 16(2), CGST Act 2017; Rule 37",
                    section_number="16",
                    description="180-day payment-to-supplier rule.",
                    inputs_used={"invoice_number": invoice.invoice_number, "days_taken": days_taken},
                    computed_value=days_taken,
                    threshold_value=DAYS_180,
                    explanation_hint=(
                        f"Invoice {invoice.invoice_number} was paid within {days_taken} days (<=180), so no "
                        f"ITC reversal is triggered under the second proviso to Sec 16(2)."
                    ),
                )
            return RuleEvaluation(
                rule_id=f"Sec16_2_Proviso_180Day_{invoice.invoice_number}",
                module=ComplianceModule.INPUT_TAX_CREDIT,
                status=VerdictStatus.VIOLATED if invoice.itc_claimed else VerdictStatus.INDETERMINATE,
                legal_citation="Second proviso to Sec 16(2), CGST Act 2017; Rule 37",
                section_number="16",
                description="180-day payment-to-supplier rule.",
                inputs_used={"invoice_number": invoice.invoice_number, "days_taken": days_taken},
                computed_value=days_taken,
                threshold_value=DAYS_180,
                explanation_hint=(
                    f"Invoice {invoice.invoice_number} took {days_taken} days to pay (>180), triggering "
                    f"reversal of the corresponding ITC with interest under Rule 37"
                    + (", and that ITC has already been claimed - reverse it now." if invoice.itc_claimed else ".")
                ),
            )

        # Not yet paid: only actionable once the 180-day window has actually
        # elapsed AND ITC was claimed (otherwise there's nothing to reverse
        # yet, and nothing wrong has happened - stay silent, matching the
        # "no news is good news" convention used in Phase 3).
        days_elapsed = (self.as_of_date - invoice.invoice_date).days
        if days_elapsed > DAYS_180 and invoice.itc_claimed:
            return RuleEvaluation(
                rule_id=f"Sec16_2_Proviso_180Day_{invoice.invoice_number}",
                module=ComplianceModule.INPUT_TAX_CREDIT,
                status=VerdictStatus.VIOLATED,
                legal_citation="Second proviso to Sec 16(2), CGST Act 2017; Rule 37",
                section_number="16",
                description="180-day payment-to-supplier rule.",
                inputs_used={"invoice_number": invoice.invoice_number, "days_elapsed": days_elapsed},
                computed_value=days_elapsed,
                threshold_value=DAYS_180,
                explanation_hint=(
                    f"Invoice {invoice.invoice_number} remains unpaid {days_elapsed} days after the invoice "
                    f"date (>180) and ITC has been claimed on it - reverse this ITC with interest under Rule 37 "
                    f"until payment is made."
                ),
            )
        return None

    # -- 4: Sec 16(4) time bar ------------------------------------------------

    def _sec16_4_time_bar(self, profile: BusinessProfile, invoice: InvoiceRecord) -> RuleEvaluation | None:
        if invoice.is_blocked_credit_category:
            return None   # already void under Sec 17(5) - a time-bar finding would be redundant noise

        fy = invoice.financial_year or financial_year_of(invoice.invoice_date)
        deadline = sec16_4_deadline(fy, profile.annual_return_filed_dates)

        if invoice.itc_claimed:
            if invoice.itc_claim_date is None:
                status = VerdictStatus.INDETERMINATE
                explanation = (
                    f"Invoice {invoice.invoice_number}: ITC is marked as claimed but no claim date is on "
                    f"record, so the Sec 16(4) time-bar ({deadline.isoformat()} deadline for FY {fy}) cannot be verified."
                )
            else:
                claimed_var = Bool("claimed_in_time")
                s = Solver()
                s.add(claimed_var == (invoice.itc_claim_date <= deadline))
                assert s.check() == sat
                in_time = bool(s.model().eval(claimed_var))
                status = VerdictStatus.SATISFIED if in_time else VerdictStatus.VIOLATED
                explanation = (
                    f"Invoice {invoice.invoice_number} (FY {fy}): ITC claimed on {invoice.itc_claim_date.isoformat()}, "
                    + (
                        f"within the Sec 16(4) deadline of {deadline.isoformat()}."
                        if in_time else
                        f"AFTER the Sec 16(4) deadline of {deadline.isoformat()} - this claim is time-barred "
                        f"and the ITC is not legally available; it should be reversed."
                    )
                )
        else:
            if self.as_of_date > deadline:
                status = VerdictStatus.VIOLATED
                explanation = (
                    f"Invoice {invoice.invoice_number} (FY {fy}): ITC of Rs {float(invoice.tax_amount):,.2f} was "
                    f"never claimed, and the Sec 16(4) deadline of {deadline.isoformat()} has now passed - this "
                    f"ITC is permanently lost."
                )
            else:
                return None   # still within the claim window - no finding yet

        return RuleEvaluation(
            rule_id=f"Sec16_4_TimeBar_{invoice.invoice_number}",
            module=ComplianceModule.INPUT_TAX_CREDIT,
            status=status,
            legal_citation="Sec 16(4), CGST Act 2017",
            section_number="16",
            description="Sec 16(4) time-bar on claiming ITC (30 November following FY end, or annual return date if earlier).",
            inputs_used={
                "invoice_number": invoice.invoice_number,
                "financial_year": fy,
                "deadline": deadline.isoformat(),
                "itc_claimed": invoice.itc_claimed,
                "itc_claim_date": invoice.itc_claim_date.isoformat() if invoice.itc_claim_date else None,
            },
            explanation_hint=explanation,
        )
