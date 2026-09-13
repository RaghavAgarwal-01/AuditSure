"""
AuditSure Layer 2 - Phase 6d: Appeal Engine (Sec 107)
===========================================================
For each BusinessProfile.appeal_records entry:
  1. Limitation period: 3 months from order communication (+1 month
     condonable on sufficient cause - reported separately as a note
     when the 3-month window is missed but the condonable window isn't).
  2. Pre-deposit calculator: full admitted amount + 10% of the disputed
     tax amount, capped at Rs 20 crore - a genuine small computation
     (min() against the cap) rather than a pure lookup.
"""

from __future__ import annotations

import calendar

from business_profile import AppealRecord, BusinessProfile
from ontology_loader import OntologyLoader
from proof_object import ComplianceModule, RuleEvaluation, VerdictStatus


class AppealEngine:

    def __init__(self, onto: OntologyLoader):
        self.onto = onto

    def evaluate(self, profile: BusinessProfile) -> list[RuleEvaluation]:
        evaluations: list[RuleEvaluation] = []
        for appeal in profile.appeal_records:
            evaluations.append(self._limitation_check(appeal))
            evaluations.append(self._pre_deposit_calculation(appeal))
        return evaluations

    # -- 3-month limitation (+1 month condonable) -----------------------------

    def _limitation_check(self, appeal: AppealRecord) -> RuleEvaluation:
        limitation = self.onto.get_threshold("ThresholdAppealLimitation3Months")
        months = int(limitation.amount)
        deadline = _add_months(appeal.order_communication_date, months)
        condonable_deadline = _add_months(appeal.order_communication_date, months + 1)

        if appeal.appeal_filed_date is None:
            status = VerdictStatus.INDETERMINATE
            explanation = (
                f"Appeal {appeal.appeal_id}: no filing date on record, so the Sec 107(1) 3-month limitation "
                f"check (deadline {deadline.isoformat()}) cannot be verified."
            )
        elif appeal.appeal_filed_date <= deadline:
            status = VerdictStatus.SATISFIED
            explanation = (
                f"Appeal {appeal.appeal_id} was filed on {appeal.appeal_filed_date.isoformat()}, within the "
                f"Sec 107(1) 3-month limitation deadline of {deadline.isoformat()}."
            )
        elif appeal.appeal_filed_date <= condonable_deadline:
            status = VerdictStatus.INDETERMINATE
            explanation = (
                f"Appeal {appeal.appeal_id} was filed on {appeal.appeal_filed_date.isoformat()}, after the "
                f"3-month deadline of {deadline.isoformat()} but within the further 1-month condonable window "
                f"({condonable_deadline.isoformat()}) - it may still be admitted if the Appellate Authority is "
                f"satisfied there was sufficient cause for the delay."
            )
        else:
            status = VerdictStatus.VIOLATED
            explanation = (
                f"Appeal {appeal.appeal_id} was filed on {appeal.appeal_filed_date.isoformat()}, after even "
                f"the condonable deadline of {condonable_deadline.isoformat()} - it is time-barred under "
                f"Sec 107(1) and cannot be admitted."
            )

        return RuleEvaluation(
            rule_id=f"Sec107_1_AppealLimitation_{appeal.appeal_id}",
            module=ComplianceModule.FINANCIAL_CONSEQUENCES,
            status=status,
            legal_citation=limitation.citation or "Sec 107(1), CGST Act 2017",
            section_number="107",
            description="Sec 107(1) appeal limitation period check (3 months, +1 month condonable).",
            inputs_used={
                "appeal_id": appeal.appeal_id,
                "order_communication_date": appeal.order_communication_date.isoformat(),
                "deadline": deadline.isoformat(),
                "condonable_deadline": condonable_deadline.isoformat(),
                "appeal_filed_date": appeal.appeal_filed_date.isoformat() if appeal.appeal_filed_date else None,
            },
            explanation_hint=explanation,
        )

    # -- Pre-deposit: admitted amount + 10% of disputed tax, capped ------------

    def _pre_deposit_calculation(self, appeal: AppealRecord) -> RuleEvaluation:
        rate = self.onto.get_threshold("ThresholdAppealPreDeposit10Pct")
        cap = self.onto.get_threshold("ThresholdAppealPreDepositCap20Cr")

        admitted = float(appeal.admitted_amount)
        disputed = float(appeal.disputed_tax_amount)
        ten_pct_of_disputed = disputed * (rate.amount / 100.0)
        capped_pre_deposit_component = min(ten_pct_of_disputed, cap.amount)
        total_pre_deposit = admitted + capped_pre_deposit_component
        cap_applied = ten_pct_of_disputed > cap.amount

        return RuleEvaluation(
            rule_id=f"Sec107_6_PreDepositCalculation_{appeal.appeal_id}",
            module=ComplianceModule.FINANCIAL_CONSEQUENCES,
            status=VerdictStatus.SATISFIED,
            legal_citation=rate.citation or "Sec 107(6), CGST Act 2017",
            section_number="107",
            description="Sec 107(6) pre-deposit calculation (admitted amount + 10% of disputed tax, capped at Rs 20 crore).",
            inputs_used={
                "appeal_id": appeal.appeal_id, "admitted_amount": admitted, "disputed_tax_amount": disputed,
                "cap_applied": cap_applied,
            },
            computed_value=total_pre_deposit,
            threshold_value=cap.amount,
            threshold_id=cap.id,
            explanation_hint=(
                f"Appeal {appeal.appeal_id}: pre-deposit required is Rs {admitted:,.2f} (admitted amount, paid "
                f"in full) + Rs {capped_pre_deposit_component:,.2f} "
                f"({'capped at Rs 20 crore - ' if cap_applied else ''}10% of the Rs {disputed:,.2f} disputed tax "
                f"amount) = Rs {total_pre_deposit:,.2f} total, under {rate.citation}."
            ),
        )


def _add_months(d, months: int):
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)
