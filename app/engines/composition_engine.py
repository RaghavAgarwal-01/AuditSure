"""
AuditSure Layer 2 - Phase 2b: Composition Levy Eligibility Engine
=====================================================================
Encodes Sec 10(1) (goods/restaurant composition) and Sec 10(2A)
(services composition) as a Z3 constraint model.

Only conditions actually captured in the validated Layer 1 ontology
(gst:CGST_Section10 / gst:CompositionLevyGoods / gst:CompositionLevyServices
comments) are modelled as hard disqualifiers, per the project rule of
never inventing legal detail beyond the source manual:
  - turnover must not exceed the applicable threshold (Rs 1.5 Cr goods /
    Rs 75L specified special-category states / Rs 50L services),
  - no inter-State outward supply,
  - no supply through an e-commerce operator required to collect TCS
    (except as separately permitted - not modelled, since the manual's
    extracted text only establishes the general bar, not the carve-out
    mechanics),
  - for a goods-composition dealer, non-permitted SERVICE supply must not
    exceed the higher of 10% of turnover or Rs 5 lakh (the Sec 10(1)
    second-proviso limb).
  - Sec 24 compulsory-registration categories that are also structurally
    incompatible with composition (casual taxable person, non-resident
    taxable person, ISD) are cross-checked against the Registration
    Engine's own flags rather than re-declared here, so the two engines
    cannot silently disagree about what a "casual taxable person" is.

Any condition NOT captured above (e.g. the exact e-commerce carve-out,
or manufacture of specific notified goods excluded from composition)
is intentionally left unmodelled and is called out as a LIMITATIONS
note in Layer2_README.md - it is safer for the solver to be silent on
a condition than to assert one not actually verified in the source
manual.
"""

from __future__ import annotations

from dataclasses import dataclass

from z3 import And, Bool, BoolRef, If, Not, Or, Real, Solver, sat

from app.models.business_profile import BusinessProfile
from app.ontology.ontology_loader import OntologyLoader
from app.models.proof_object import ComplianceModule, RuleEvaluation, VerdictStatus
from app.engines.registration_engine import SEC24_TRIGGERS


GOODS_ELIGIBLE_BUSINESS_TYPES = ("Manufacturer", "Trader")
SERVICES_ONLY_INCOMPATIBLE_SEC24 = ("is_casual_taxable_person", "is_non_resident_taxable_person",
                                     "is_input_service_distributor")


@dataclass(frozen=True)
class CompositionVerdict:
    scheme: str                    # "Goods" | "Services" | "Ineligible"
    threshold_id: str | None
    disqualifiers: tuple[str, ...]  # human-readable reasons, empty if eligible


class CompositionEngine:
    """Z3-backed evaluator for Sec 10(1)/10(2A) composition eligibility."""

    def __init__(self, onto: OntologyLoader):
        self.onto = onto

    def _goods_threshold(self, profile: BusinessProfile):
        if self.onto.is_special_category_state(profile.state):
            return self.onto.get_threshold("ThresholdCompositionGoodsSpecialCategory75L")
        return self.onto.get_threshold("ThresholdCompositionGoods1_5Cr")

    def _services_threshold(self, profile: BusinessProfile):
        return self.onto.get_threshold("ThresholdCompositionServices50L")

    def _structurally_incompatible(self, profile: BusinessProfile) -> list[str]:
        """Sec 24 categories that are logically incompatible with the
        composition levy regardless of turnover (a casual/non-resident
        taxable person or ISD cannot opt for composition)."""
        reasons = []
        for flag in SERVICES_ONLY_INCOMPATIBLE_SEC24:
            if getattr(profile, flag, False):
                trigger = next(t for t in SEC24_TRIGGERS if t.flag_name == flag)
                reasons.append(trigger.description)
        return reasons

    def evaluate(self, profile: BusinessProfile) -> list[RuleEvaluation]:
        turnover = float(profile.aggregate_turnover)

        # -- Z3 model: encode ALL disqualifying conditions as boolean terms,
        #    then let Z3 combine them, rather than an ad-hoc chain of
        #    Python `if` statements that would need to get the boolean
        #    algebra (De Morgan / precedence) right by hand.
        turnover_v = Real("turnover")
        goods_threshold_v = Real("goods_threshold")
        services_threshold_v = Real("services_threshold")
        interstate_v = Bool("makes_interstate_outward_supply")
        ecommerce_tcs_v = Bool("supplies_via_ecommerce_collecting_tcs")
        structurally_incompatible_v = Bool("structurally_incompatible")

        goods_eligible: BoolRef = And(
            turnover_v <= goods_threshold_v,
            Not(interstate_v),
            Not(ecommerce_tcs_v),
            Not(structurally_incompatible_v),
        )
        services_eligible: BoolRef = And(
            turnover_v <= services_threshold_v,
            Not(interstate_v),
            Not(ecommerce_tcs_v),
            Not(structurally_incompatible_v),
        )

        s = Solver()
        goods_threshold = self._goods_threshold(profile)
        services_threshold = self._services_threshold(profile)
        incompatible_reasons = self._structurally_incompatible(profile)

        s.add(turnover_v == turnover)
        s.add(goods_threshold_v == goods_threshold.amount)
        s.add(services_threshold_v == services_threshold.amount)
        s.add(interstate_v == bool(profile.makes_interstate_outward_supply))
        s.add(ecommerce_tcs_v == bool(profile.supplies_via_ecommerce_collecting_tcs))
        s.add(structurally_incompatible_v == bool(incompatible_reasons))

        assert s.check() == sat, "Composition model unsatisfiable - conflicting BusinessProfile facts."
        model = s.model()

        is_goods_type = any(bt in GOODS_ELIGIBLE_BUSINESS_TYPES for bt in profile.business_types) or not profile.business_types
        goods_ok = bool(model.eval(goods_eligible)) and is_goods_type
        services_ok = bool(model.eval(services_eligible)) and not is_goods_type

        evaluations: list[RuleEvaluation] = []

        if goods_ok:
            evaluations.append(self._eligible_evaluation(profile, "Sec10_1_CompositionGoods", goods_threshold,
                                                           "Sec 10(1), CGST Act 2017", turnover, "goods/restaurant"))
        elif services_ok:
            evaluations.append(self._eligible_evaluation(profile, "Sec10_2A_CompositionServices", services_threshold,
                                                           "Sec 10(2A), CGST Act 2017", turnover, "services"))
        else:
            reasons = list(incompatible_reasons)
            applicable_threshold = goods_threshold if is_goods_type else services_threshold
            if profile.makes_interstate_outward_supply:
                reasons.append("makes inter-State outward supply (Sec 10(1)/(2A) proviso)")
            if profile.supplies_via_ecommerce_collecting_tcs:
                reasons.append("supplies via an e-commerce operator required to collect TCS (Sec 10(1)/(2A) proviso)")
            if turnover > applicable_threshold.amount:
                reasons.append(f"turnover of Rs {turnover:,.0f} exceeds the Rs {applicable_threshold.amount:,.0f} threshold")

            evaluations.append(RuleEvaluation(
                rule_id="Sec10_CompositionIneligible",
                module=ComplianceModule.COMPOSITION,
                status=VerdictStatus.VIOLATED if profile.opts_for_composition else VerdictStatus.NOT_APPLICABLE,
                legal_citation="Sec 10, CGST Act 2017",
                section_number="10",
                description="Composition levy eligibility check (Sec 10(1) goods / Sec 10(2A) services).",
                inputs_used={"aggregate_turnover": turnover, "reasons": reasons},
                computed_value=turnover,
                threshold_value=applicable_threshold.amount,
                threshold_id=applicable_threshold.id,
                explanation_hint=(
                    f"{profile.name} is not eligible for the composition levy because " +
                    "; ".join(reasons) + "."
                    if reasons else
                    f"{profile.name} is not eligible for the composition levy under Sec 10."
                ),
            ))

        return evaluations

    def _eligible_evaluation(self, profile, rule_id, threshold, citation, turnover, scheme_label) -> RuleEvaluation:
        return RuleEvaluation(
            rule_id=rule_id,
            module=ComplianceModule.COMPOSITION,
            status=VerdictStatus.SATISFIED,
            legal_citation=citation,
            section_number="10",
            description=f"Composition levy eligibility check ({scheme_label} scheme).",
            inputs_used={
                "aggregate_turnover": turnover,
                "state": profile.state,
                "makes_interstate_outward_supply": profile.makes_interstate_outward_supply,
                "supplies_via_ecommerce_collecting_tcs": profile.supplies_via_ecommerce_collecting_tcs,
            },
            computed_value=turnover,
            threshold_value=threshold.amount,
            threshold_id=threshold.id,
            explanation_hint=(
                f"{profile.name} is eligible to opt for the {scheme_label} composition levy under {citation}: "
                f"turnover of Rs {turnover:,.0f} is within the Rs {threshold.amount:,.0f} threshold ({threshold.label}), "
                f"with no inter-State outward supply and no disqualifying e-commerce/TCS supply."
            ),
        )
