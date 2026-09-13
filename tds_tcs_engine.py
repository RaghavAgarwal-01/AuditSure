"""
AuditSure Layer 2 - Phase 5c: TDS / TCS Applicability Engine
==================================================================
Sec 51 (TDS): a specified deductor must deduct tax at the notified rate
from a payment to a supplier where the total contract value exceeds
Rs 2,50,000. Checked per InvoiceRecord.taxable_value, modelling each
invoice's value as its own "contract value" (a documented simplification -
see LIMITATION below).

Sec 52 (TCS): every e-commerce operator (other than an agent) must
collect tax on the net value of taxable supplies made through it by
other suppliers. Modelled at the OPERATOR-obligation level (does this
business need to register and collect TCS at all), not per third-party
transaction, since representing another seller's sales through a
marketplace is outside BusinessProfile's single-business scope.

LIMITATION (documented, not silently assumed): Sec 51's threshold is
technically applied to the aggregate value of a CONTRACT, which may
span multiple invoices - this engine checks each invoice independently
and will not catch a contract artificially split into several
sub-threshold invoices. A real deployment would need contract-level
aggregation, which requires a "contract" concept BusinessProfile does
not yet have.
"""

from __future__ import annotations

from business_profile import BusinessProfile, InvoiceRecord
from ontology_loader import OntologyLoader
from proof_object import ComplianceModule, RuleEvaluation, VerdictStatus


class TDSApplicabilityEngine:

    def __init__(self, onto: OntologyLoader):
        self.onto = onto

    def evaluate(self, profile: BusinessProfile) -> list[RuleEvaluation]:
        if not profile.is_deductor_under_section51:
            return []   # Sec 51 only binds specified deductors - not an ordinary taxpayer
        return [
            self._per_invoice_check(profile, invoice)
            for invoice in profile.inward_invoices
        ]

    def _per_invoice_check(self, profile: BusinessProfile, invoice: InvoiceRecord) -> RuleEvaluation:
        threshold = self.onto.get_threshold("ThresholdTDSContractValue250K")
        value = float(invoice.taxable_value)
        tds_required = value > threshold.amount

        if tds_required and not invoice.tds_deducted:
            status = VerdictStatus.VIOLATED
            explanation = (
                f"Invoice {invoice.invoice_number}'s value of Rs {value:,.0f} exceeds the Rs "
                f"{threshold.amount:,.0f} Sec 51 threshold, and {profile.name} is a specified deductor, "
                f"but TDS was NOT deducted on this payment - this is a compliance breach requiring correction."
            )
        elif tds_required and invoice.tds_deducted:
            status = VerdictStatus.SATISFIED
            explanation = (
                f"Invoice {invoice.invoice_number}'s value of Rs {value:,.0f} exceeds the Rs "
                f"{threshold.amount:,.0f} Sec 51 threshold, and TDS was correctly deducted."
            )
        else:
            status = VerdictStatus.NOT_APPLICABLE
            explanation = (
                f"Invoice {invoice.invoice_number}'s value of Rs {value:,.0f} does not exceed the Rs "
                f"{threshold.amount:,.0f} Sec 51 threshold, so TDS deduction is not required on this payment."
            )

        return RuleEvaluation(
            rule_id=f"Sec51_TDSApplicability_{invoice.invoice_number}",
            module=ComplianceModule.COMPLIANCE_OBLIGATIONS,
            status=status,
            legal_citation=threshold.citation or "Sec 51(1), CGST Act 2017",
            section_number="51",
            description="TDS applicability and compliance check (contract/invoice value vs Sec 51 threshold).",
            inputs_used={"invoice_number": invoice.invoice_number, "tds_deducted": invoice.tds_deducted},
            computed_value=value,
            threshold_value=threshold.amount,
            threshold_id=threshold.id,
            explanation_hint=explanation,
        )


class TCSApplicabilityEngine:

    def __init__(self, onto: OntologyLoader):
        self.onto = onto

    def evaluate(self, profile: BusinessProfile) -> list[RuleEvaluation]:
        if not profile.is_ecommerce_operator:
            return []

        rate = self.onto.get_threshold("ThresholdTCSRate1Pct")
        return [RuleEvaluation(
            rule_id="Sec52_TCSObligation",
            module=ComplianceModule.COMPLIANCE_OBLIGATIONS,
            status=VerdictStatus.SATISFIED if profile.is_required_to_collect_tcs_under_section52 else VerdictStatus.VIOLATED,
            legal_citation=rate.citation or "Sec 52(1), CGST Act 2017",
            section_number="52",
            description="Sec 52 TCS collection obligation check for e-commerce operators.",
            inputs_used={
                "is_ecommerce_operator": profile.is_ecommerce_operator,
                "is_required_to_collect_tcs_under_section52": profile.is_required_to_collect_tcs_under_section52,
            },
            threshold_value=rate.amount,
            threshold_id=rate.id,
            explanation_hint=(
                f"{profile.name} is an electronic commerce operator and is correctly registered/collecting "
                f"TCS at {rate.amount:.1f}% under {rate.citation} on taxable supplies made through its platform "
                f"by other suppliers."
                if profile.is_required_to_collect_tcs_under_section52 else
                f"{profile.name} is an electronic commerce operator but is not currently flagged as collecting "
                f"TCS under Sec 52 - every e-commerce operator (other than an agent) must collect tax on net "
                f"taxable supplies made through it by other suppliers; confirm registration and set up TCS "
                f"collection at {rate.amount:.1f}%."
            ),
        )]
