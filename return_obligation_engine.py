"""
AuditSure Layer 2 - Phase 5b: Return Obligation Engine
============================================================
Determines which GSTR return(s) a BusinessProfile must file, based on
its business classification - not on turnover-based frequency options
(QRMP eligibility etc.), which this engine deliberately does NOT assert
a specific numeric threshold for (see LIMITATION below).

Priority order mirrors the ontology's own Return subclasses and their
Sec 39 citations:
  - ISD                        -> ISDReturn (GSTR-6), Sec 39(4)
  - Non-resident taxable person -> NonResidentReturn (GSTR-5), Sec 39(5)
  - TDS deductor                -> TDSReturn (GSTR-7), Sec 39(3)/Sec 51
  - TCS collector (e-commerce)  -> TCSStatement (GSTR-8), Sec 52(4)
  - Composition taxpayer        -> CompositionReturn (GSTR-4), Sec 39(2)
  - Otherwise (normal RP)       -> OutwardSupplyReturn (GSTR-1, Sec 37)
                                    + SummaryReturn (GSTR-3B, Sec 39(1))
A business can be liable for MORE than one of these simultaneously (e.g.
a normal taxpayer who is also a TDS deductor), so this engine returns
one evaluation PER applicable obligation rather than picking just one.

Sec 44 Annual Return (GSTR-9) is evaluated separately, since its
exclusion list (ISD, casual/non-resident taxable person, TDS/TCS-only
registrants) is already precisely documented on the ontology's
gst:AnnualReturn individual and deserves its own citation-backed
verdict rather than being folded into the "normal taxpayer" branch.

LIMITATION (documented, not silently assumed): return FREQUENCY choice
for normal taxpayers (monthly vs the QRMP quarterly scheme) depends on
a turnover threshold that was not deeply extracted from the source
manual this session (only the QRMP notification NAME - 84/2020-CT - was
captured, not its numeric eligibility ceiling). This engine therefore
states the return TYPE with full confidence but leaves FREQUENCY choice
as an informational note rather than asserting an unverified number.
"""

from __future__ import annotations

from business_profile import BusinessProfile, RegistrationStatus
from ontology_loader import OntologyLoader
from proof_object import ComplianceModule, RuleEvaluation, VerdictStatus


class ReturnObligationEngine:

    def __init__(self, onto: OntologyLoader):
        self.onto = onto

    def evaluate(self, profile: BusinessProfile) -> list[RuleEvaluation]:
        if profile.registration_status not in (RegistrationStatus.ACTIVE, RegistrationStatus.SUSPENDED):
            return []   # no return obligation for a never-registered/cancelled business

        evaluations: list[RuleEvaluation] = []

        if profile.is_input_service_distributor:
            evaluations.append(self._obligation(profile, "ISDReturn", "Sec 39(4), CGST Act 2017",
                                                  "Input Service Distributor Return (GSTR-6)"))
        if profile.is_non_resident_taxable_person:
            evaluations.append(self._obligation(profile, "NonResidentReturn", "Sec 39(5), CGST Act 2017",
                                                  "Non-Resident Taxable Person Return (GSTR-5)"))
        if profile.is_deductor_under_section51:
            evaluations.append(self._obligation(profile, "TDSReturn", "Sec 39(3)/Sec 51, CGST Act 2017",
                                                  "TDS Return (GSTR-7)"))
        if profile.is_required_to_collect_tcs_under_section52:
            evaluations.append(self._obligation(profile, "TCSStatement", "Sec 52(4), CGST Act 2017",
                                                  "TCS Statement (GSTR-8)"))

        if profile.opts_for_composition:
            evaluations.append(self._obligation(profile, "CompositionReturn", "Sec 39(2), CGST Act 2017",
                                                  "Composition Taxpayer Return (GSTR-4)", frequency_note=(
                    "GSTR-4 is filed ANNUALLY (due 30 April following the FY), with tax paid quarterly via "
                    "a CMP-08 statement."
                )))
        else:
            evaluations.append(self._obligation(profile, "OutwardSupplyReturn", "Sec 37, CGST Act 2017",
                                                  "Outward Supply Return (GSTR-1)", frequency_note=(
                    "Filed monthly by default, or quarterly under the QRMP scheme (Notification 84/2020-CT) "
                    "if eligible - confirm current QRMP turnover eligibility separately, as that specific "
                    "ceiling is not modelled here."
                )))
            evaluations.append(self._obligation(profile, "SummaryReturn", "Sec 39(1), CGST Act 2017",
                                                  "Summary Self-Assessed Return (GSTR-3B)", frequency_note=(
                    "Filed monthly by default, or quarterly (with monthly tax payment) under the QRMP scheme "
                    "if eligible - see note above."
                )))

        evaluations.append(self._annual_return(profile))
        return evaluations

    def _obligation(self, profile: BusinessProfile, ontology_class: str, citation: str, label: str,
                     frequency_note: str = "") -> RuleEvaluation:
        return RuleEvaluation(
            rule_id=f"ReturnObligation_{ontology_class}",
            module=ComplianceModule.COMPLIANCE_OBLIGATIONS,
            status=VerdictStatus.SATISFIED,
            legal_citation=citation,
            section_number=citation.split("Sec ")[1].split(",")[0].split("(")[0].strip() if "Sec " in citation else None,
            description=f"Return filing obligation: {label}.",
            inputs_used={"business_classification_basis": ontology_class},
            explanation_hint=(
                f"{profile.name} must file {label} under {citation}."
                + (f" {frequency_note}" if frequency_note else "")
            ),
        )

    def _annual_return(self, profile: BusinessProfile) -> RuleEvaluation:
        excluded = (
            profile.is_input_service_distributor
            or profile.is_casual_taxable_person
            or profile.is_non_resident_taxable_person
            or profile.is_deductor_under_section51
            or profile.is_required_to_collect_tcs_under_section52
        )
        sec44 = self.onto.get_class_info("AnnualReturn")
        return RuleEvaluation(
            rule_id="ReturnObligation_AnnualReturn",
            module=ComplianceModule.COMPLIANCE_OBLIGATIONS,
            status=VerdictStatus.NOT_APPLICABLE if excluded else VerdictStatus.SATISFIED,
            legal_citation=sec44.citation or "Sec 44, CGST Act 2017",
            section_number="44",
            description="Sec 44 Annual Return (GSTR-9) obligation check.",
            inputs_used={
                "is_input_service_distributor": profile.is_input_service_distributor,
                "is_casual_taxable_person": profile.is_casual_taxable_person,
                "is_non_resident_taxable_person": profile.is_non_resident_taxable_person,
                "is_deductor_under_section51": profile.is_deductor_under_section51,
                "is_required_to_collect_tcs_under_section52": profile.is_required_to_collect_tcs_under_section52,
            },
            explanation_hint=(
                f"{profile.name} is exempt from filing the Sec 44 annual return (GSTR-9), being an ISD, "
                f"casual/non-resident taxable person, or a TDS/TCS-only registrant."
                if excluded else
                f"{profile.name} must file the Sec 44 annual return (GSTR-9) for {profile.financial_year}."
            ),
        )
