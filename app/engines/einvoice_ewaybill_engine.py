"""
AuditSure Layer 2 - Phase 5a: E-Invoicing / E-Way Bill Applicability Engine
=================================================================================
Two threshold-triggered document obligations:

  1. E-invoicing (Rule 48(4), Notification 10/2023-CT): once a taxpayer's
     aggregate turnover has exceeded Rs 5 Cr in ANY financial year since
     the e-invoicing regime began, e-invoicing becomes mandatory for all
     its B2B tax invoices GOING FORWARD - it does NOT switch off again if
     turnover later drops below the threshold. This is exactly why
     BusinessProfile.turnover_by_year (a full year-by-year history, not
     just current-year turnover) was scaffolded in Phase 1: a
     current-year-only check would silently produce the wrong answer for
     a business that crossed the threshold two years ago and has since
     shrunk.

  2. E-way bill (Rule 138(1)): required per consignment where the value
     exceeds Rs 50,000. Checked per OutwardSupplyRecord.consignment_value -
     a None value is treated as "not a goods movement" (e.g. a pure
     service supply), for which Rule 138 does not apply at all.

LIMITATION (documented, not silently assumed): sector-specific exemptions
from e-invoicing (SEZ units, insurers, banks/FIs, GTAs, passenger
transport, cinema exhibitors, and government departments/local
authorities) and from e-way bills (specified exempted goods, non-motorised
conveyance, etc.) are NOT modelled - the source manual's tracker gives the
threshold notifications but not an exhaustive, itemised exemption list.
See Layer2_README.md.
"""

from __future__ import annotations

from app.models.business_profile import BusinessProfile, OutwardSupplyRecord
from app.ontology.ontology_loader import OntologyLoader
from app.models.proof_object import ComplianceModule, RuleEvaluation, VerdictStatus


class EInvoicingEWayBillEngine:

    def __init__(self, onto: OntologyLoader):
        self.onto = onto

    def evaluate(self, profile: BusinessProfile) -> list[RuleEvaluation]:
        evaluations = [self._einvoicing_applicability(profile)]
        for record in profile.outward_supplies:
            eway_eval = self._eway_bill_applicability(record)
            if eway_eval:
                evaluations.append(eway_eval)
        return evaluations

    # -- E-invoicing: ever-crossed-threshold check, not current-year-only ----

    def _einvoicing_applicability(self, profile: BusinessProfile) -> RuleEvaluation:
        if profile.opts_for_composition:
            return RuleEvaluation(
                rule_id="Rule48_4_EInvoicingApplicability",
                module=ComplianceModule.COMPLIANCE_OBLIGATIONS,
                status=VerdictStatus.NOT_APPLICABLE,
                legal_citation="Rule 48(4), CGST Rules 2017; Sec 31(3)(c), CGST Act 2017",
                section_number=None,
                description="E-invoicing applicability check.",
                inputs_used={"opts_for_composition": True},
                explanation_hint=(
                    f"{profile.name} has opted for the composition levy, so e-invoicing is not applicable "
                    f"regardless of turnover - composition taxpayers issue a Bill of Supply under Sec 31(3)(c), "
                    f"not a tax invoice, and Rule 48(4)'s e-invoicing mandate applies only to tax invoices."
                ),
            )

        threshold = self.onto.get_threshold("ThresholdEInvoicing5Cr")

        turnover_history = dict(profile.turnover_by_year)
        turnover_history[profile.financial_year] = profile.aggregate_turnover
        max_fy, max_turnover = max(turnover_history.items(), key=lambda kv: float(kv[1]))
        max_turnover_f = float(max_turnover)

        applicable = max_turnover_f > threshold.amount

        return RuleEvaluation(
            rule_id="Rule48_4_EInvoicingApplicability",
            module=ComplianceModule.COMPLIANCE_OBLIGATIONS,
            status=VerdictStatus.SATISFIED if applicable else VerdictStatus.NOT_APPLICABLE,
            legal_citation=threshold.citation or "Rule 48(4), CGST Rules 2017",
            section_number=None,
            description="E-invoicing applicability check (turnover ever exceeding the notified threshold, any FY).",
            inputs_used={"turnover_by_year": {k: float(v) for k, v in turnover_history.items()},
                         "highest_turnover_fy": max_fy, "highest_turnover": max_turnover_f},
            computed_value=max_turnover_f,
            threshold_value=threshold.amount,
            threshold_id=threshold.id,
            explanation_hint=(
                (
                    f"{profile.name}'s aggregate turnover exceeded Rs {threshold.amount:,.0f} in FY {max_fy} "
                    f"(Rs {max_turnover_f:,.0f}), so e-invoicing is mandatory for all B2B tax invoices from the "
                    f"notified date onward under {threshold.citation} - and remains mandatory even in years "
                    f"where turnover is lower, since the obligation does not switch off once triggered."
                ) if applicable else (
                    f"{profile.name}'s aggregate turnover has not exceeded the Rs {threshold.amount:,.0f} "
                    f"e-invoicing threshold in any recorded financial year (highest on record: Rs "
                    f"{max_turnover_f:,.0f} in FY {max_fy}), so e-invoicing is not yet mandatory under "
                    f"{threshold.citation}."
                )
            ),
        )

    # -- E-way bill: per-consignment check ------------------------------------

    def _eway_bill_applicability(self, record: OutwardSupplyRecord) -> RuleEvaluation | None:
        if record.consignment_value is None:
            return None   # not a goods movement (e.g. a pure service supply) - Rule 138 is moot

        threshold = self.onto.get_threshold("ThresholdEWayBill50K")
        value = float(record.consignment_value)
        required = value > threshold.amount

        return RuleEvaluation(
            rule_id=f"Rule138_EWayBillApplicability_{record.invoice_number}",
            module=ComplianceModule.COMPLIANCE_OBLIGATIONS,
            status=VerdictStatus.SATISFIED if required else VerdictStatus.NOT_APPLICABLE,
            legal_citation=threshold.citation or "Rule 138(1), CGST Rules 2017",
            section_number=None,
            description="E-way bill applicability check (consignment value vs Rule 138 threshold).",
            inputs_used={"invoice_number": record.invoice_number, "consignment_value": value},
            computed_value=value,
            threshold_value=threshold.amount,
            threshold_id=threshold.id,
            explanation_hint=(
                f"Invoice {record.invoice_number}'s consignment value of Rs {value:,.0f} "
                f"{'exceeds' if required else 'does not exceed'} the Rs {threshold.amount:,.0f} threshold under "
                f"{threshold.citation}, so an e-way bill is "
                f"{'required' if required else 'not required'} for this movement of goods."
            ),
        )
