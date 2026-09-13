"""
AuditSure Layer 2 - Phase 2a: Registration Liability Engine
================================================================
Encodes Sec 22 (threshold-based liability), Sec 23 (exemptions), and
Sec 24 (compulsory registration irrespective of turnover) as a single
Z3 constraint model, and evaluates a BusinessProfile against it.

Why Z3 here and not plain if/else:
  - The three sections interact with a specific legal PRIORITY that is
    easy to get backwards in hand-written conditionals: Sec 24 overrides
    everything (compulsory regardless of turnover/exemption), Sec 23
    exemption only wins if no Sec 24 category applies, and Sec 22's
    threshold is the fallback. That priority is encoded ONCE, as a
    formula; both the final verdict AND the "which provision decided
    this" explanation are read back out of the same solved Z3 model,
    so there is no second, hand-written copy of the priority logic
    that could silently drift out of sync with the formula.
  - solve_minimum_turnover_for_exemption() below is a genuine
    satisfiability query: "what is the highest turnover at which this
    business would NOT be liable?" - falls out of the model for free.

Legal basis modelled (see ontology gst:CGST_Section22/23/24 for the
authoritative citations):
  - Sec 22(1): liable if aggregate turnover > Rs 20L (Rs 10L special
    category states), subject to a notified Rs 40L goods-only
    enhancement (surfaced separately - see the enhancement note logic -
    since it is an OPTIONAL, State-adopted notification, not a
    uniform rule).
  - Sec 23(1): NOT liable if exclusively supplying wholly-exempt/
    non-taxable goods/services, or an agriculturist (produce of own land).
  - Sec 24: compulsorily liable irrespective of turnover if ANY of the
    listed categories apply (modelled here as the subset expressible
    from BusinessProfile flags: inter-state supply, casual taxable
    person, reverse-charge liability, non-resident taxable person,
    TDS deductor liability, ISD, e-commerce operator required to
    collect TCS).
"""

from __future__ import annotations

from dataclasses import dataclass

from z3 import Bool, BoolRef, If, Or, Real, Solver, sat

from business_profile import BusinessProfile, RegistrationStatus
from ontology_loader import OntologyLoader
from proof_object import ComplianceModule, RuleEvaluation, VerdictStatus


@dataclass(frozen=True)
class Sec24Trigger:
    """One of the Sec 24 compulsory-registration categories, with the
    BusinessProfile flag that evidences it and its ontology tie-in."""
    flag_name: str
    description: str


SEC24_TRIGGERS: tuple[Sec24Trigger, ...] = (
    Sec24Trigger("makes_interstate_outward_supply", "Inter-State supplier - Sec 24(i)"),
    Sec24Trigger("is_casual_taxable_person", "Casual taxable person - Sec 24(ii)"),
    Sec24Trigger("is_liable_under_reverse_charge", "Liable to pay tax under reverse charge - Sec 24(iii)"),
    Sec24Trigger("is_non_resident_taxable_person", "Non-resident taxable person - Sec 24(v)"),
    Sec24Trigger("is_deductor_under_section51", "Required to deduct TDS - Sec 24(vi)"),
    Sec24Trigger("is_input_service_distributor", "Input Service Distributor - Sec 24(viii)"),
    Sec24Trigger("is_required_to_collect_tcs_under_section52", "E-commerce operator required to collect TCS - Sec 24(x)"),
    Sec24Trigger("is_ecommerce_operator", "Electronic commerce operator - Sec 24(x)"),
)


def _is_currently_unregistered(profile: BusinessProfile) -> bool:
    return profile.registration_status in (RegistrationStatus.NOT_REGISTERED, RegistrationStatus.CANCELLED)


class RegistrationEngine:
    """Z3-backed evaluator for Sec 22/23/24 registration liability."""

    def __init__(self, onto: OntologyLoader):
        self.onto = onto

    def _applicable_threshold(self, profile: BusinessProfile):
        """Special-category Rs 10L, or general Rs 20L. (The Rs 40L
        goods-only enhancement is State-optional and handled separately
        as an informational note in evaluate().)"""
        if self.onto.is_special_category_state(profile.state):
            return self.onto.get_threshold("ThresholdRegistrationSpecialCategory10L")
        return self.onto.get_threshold("ThresholdRegistrationGeneral20L")

    def evaluate(self, profile: BusinessProfile) -> list[RuleEvaluation]:
        threshold = self._applicable_threshold(profile)
        turnover = float(profile.aggregate_turnover)
        exempt_facts = bool(profile.supplies_exclusively_exempt_or_nontaxable_goods or profile.is_agriculturist)
        active_triggers = [t for t in SEC24_TRIGGERS if getattr(profile, t.flag_name, False)]

        # --- Single Z3 formula encoding the Sec 22/23/24 priority -----------
        turnover_v = Real("turnover")
        threshold_v = Real("threshold_amount")
        sec24_flag_vars = {t.flag_name: Bool(f"sec24_{t.flag_name}") for t in SEC24_TRIGGERS}
        sec23_exempt_v = Bool("sec23_exempt")

        sec22_liable: BoolRef = turnover_v > threshold_v
        sec24_liable: BoolRef = Or(*sec24_flag_vars.values())
        registration_required: BoolRef = If(sec24_liable, True, If(sec23_exempt_v, False, sec22_liable))

        s = Solver()
        s.add(turnover_v == turnover)
        s.add(threshold_v == threshold.amount)
        s.add(sec23_exempt_v == exempt_facts)
        for t in SEC24_TRIGGERS:
            s.add(sec24_flag_vars[t.flag_name] == bool(getattr(profile, t.flag_name, False)))

        check = s.check()
        assert check == sat, "Registration model unsatisfiable - conflicting BusinessProfile facts."
        model = s.model()

        # Read the "why" directly off the solved model - not re-derived.
        is_liable = bool(model.eval(registration_required))
        sec24_fired = bool(model.eval(sec24_liable))
        sec23_fired = bool(model.eval(sec23_exempt_v)) and not sec24_fired
        sec22_fired = not sec24_fired and not sec23_fired

        evaluations: list[RuleEvaluation] = []
        currently_unregistered = _is_currently_unregistered(profile)

        if sec24_fired:
            trigger_desc = "; ".join(t.description for t in active_triggers)
            evaluations.append(RuleEvaluation(
                rule_id="Sec24_CompulsoryRegistration",
                module=ComplianceModule.REGISTRATION,
                status=VerdictStatus.VIOLATED if currently_unregistered else VerdictStatus.SATISFIED,
                legal_citation="Sec 24, CGST Act 2017",
                section_number="24",
                description="Compulsory registration check (overrides turnover threshold and Sec 23 exemption).",
                inputs_used={"active_triggers": [t.flag_name for t in active_triggers]},
                explanation_hint=(
                    f"{profile.name} falls under Sec 24 compulsory registration ({trigger_desc}), "
                    f"so registration is mandatory irrespective of turnover, and irrespective of "
                    f"any Sec 23 exemption that might otherwise apply."
                ),
            ))
        elif sec23_fired:
            evaluations.append(RuleEvaluation(
                rule_id="Sec23_RegistrationExemption",
                module=ComplianceModule.REGISTRATION,
                status=VerdictStatus.SATISFIED,
                legal_citation="Sec 23(1), CGST Act 2017",
                section_number="23",
                description="Sec 23 exemption from registration check.",
                inputs_used={
                    "supplies_exclusively_exempt_or_nontaxable_goods": profile.supplies_exclusively_exempt_or_nontaxable_goods,
                    "is_agriculturist": profile.is_agriculturist,
                },
                explanation_hint=(
                    f"{profile.name} is not liable to register under Sec 23(1), being "
                    f"{'an agriculturist supplying own produce' if profile.is_agriculturist else 'exclusively engaged in exempt/non-taxable supplies'}, "
                    f"and no Sec 24 compulsory-registration category applies."
                ),
            ))
        else:
            evaluations.append(RuleEvaluation(
                rule_id="Sec22_RegistrationLiability",
                module=ComplianceModule.REGISTRATION,
                status=VerdictStatus.VIOLATED if (is_liable and currently_unregistered) else VerdictStatus.SATISFIED,
                legal_citation=threshold.citation or "Sec 22(1), CGST Act 2017",
                section_number="22",
                description=f"Turnover-threshold registration check against {threshold.label}.",
                inputs_used={"aggregate_turnover": turnover, "state": profile.state},
                computed_value=turnover,
                threshold_value=threshold.amount,
                threshold_id=threshold.id,
                explanation_hint=(
                    f"{profile.name}'s aggregate turnover of Rs {turnover:,.0f} "
                    f"{'exceeds' if is_liable else 'does not exceed'} the Rs {threshold.amount:,.0f} threshold "
                    f"under {threshold.citation}, so registration is "
                    f"{'mandatory' if is_liable else 'not mandatory (voluntary registration remains an option under Sec 25(3))'}."
                ),
            ))

        evaluations.extend(self._goods_only_enhancement_note(profile, threshold, sec24_fired, sec23_fired, turnover))
        return evaluations

    def _goods_only_enhancement_note(self, profile, threshold, sec24_fired, sec23_fired, turnover) -> list[RuleEvaluation]:
        """Informational note for the Rs 20L-40L band: whether the
        State-optional Rs 40L goods-only enhancement (Notification
        10/2019-CT) could change the Sec 22 answer. Flagged INDETERMINATE
        because BusinessProfile does not (yet) capture State-adoption
        status of that specific notification."""
        if sec24_fired or sec23_fired or threshold.id != "ThresholdRegistrationGeneral20L":
            return []
        enhancement = self.onto.get_threshold("ThresholdRegistrationGoodsOnly40L")
        deals_exclusively_in_goods = bool(profile.business_types) and all(
            bt in ("Manufacturer", "Trader") for bt in profile.business_types
        )
        if not (deals_exclusively_in_goods and threshold.amount < turnover <= enhancement.amount):
            return []
        return [RuleEvaluation(
            rule_id="Sec22_GoodsOnlyEnhancementNote",
            module=ComplianceModule.REGISTRATION,
            status=VerdictStatus.INDETERMINATE,
            legal_citation=enhancement.citation or "Sec 22(1) proviso, CGST Act 2017",
            section_number="22",
            description="Possible Rs 40 lakh goods-only threshold enhancement (State-optional notification).",
            inputs_used={"aggregate_turnover": turnover, "state": profile.state},
            computed_value=turnover,
            threshold_value=enhancement.amount,
            threshold_id=enhancement.id,
            explanation_hint=(
                f"{profile.name}'s turnover of Rs {turnover:,.0f} falls between the Rs 20 lakh general "
                f"threshold and the Rs 40 lakh goods-only enhancement under Notification 10/2019-CT. "
                f"That enhancement is optional per State - confirm whether {profile.state} has adopted it "
                f"before treating this business as exempt from registration on turnover grounds alone."
            ),
        )]


def solve_minimum_turnover_for_exemption(engine: RegistrationEngine, profile: BusinessProfile) -> float | None:
    """Genuine Z3 satisfiability query: what is the highest turnover at
    which this exact profile (same state, same Sec 24/23 facts) would
    NOT be liable to register? Returns None if Sec 24 makes the business
    liable regardless of turnover, or Sec 23 already exempts it outright."""
    if any(getattr(profile, t.flag_name, False) for t in SEC24_TRIGGERS):
        return None
    if profile.supplies_exclusively_exempt_or_nontaxable_goods or profile.is_agriculturist:
        return None

    threshold = engine._applicable_threshold(profile)
    t = Real("t")
    s = Solver()
    s.add(t >= 0)
    s.add(t <= threshold.amount)          # search within the "not liable" region
    s.add(t == threshold.amount)          # the boundary itself is still "not liable" (strict >)
    if s.check() == sat:
        return threshold.amount
    return None
