"""
AuditSure Layer 2 - Phase 3b: Levy Mechanism Engine (Forward vs Reverse Charge)
====================================================================================
Determines, per outward-supply record, whether the supplier collects
tax (forward charge, the default under Sec 9(1)) or whether liability
shifts to the recipient (reverse charge under Sec 9(3) or Sec 9(4)).

Encoded as one Z3 formula per record because the two reverse-charge
gateways have DIFFERENT preconditions that are easy to conflate:
  - Sec 9(3): reverse charge on Government-notified categories of
    supply, REGARDLESS of either party's registration status.
  - Sec 9(4): reverse charge only where an UNREGISTERED supplier makes
    a notified supply to a REGISTERED recipient - registration status
    of both sides is a precondition, unlike Sec 9(3).

reverse_charge_applies = sec9_3_notified OR (sec9_4_notified AND
                                              NOT supplier_registered AND
                                              recipient_registered)

This reuses registration_engine's own "is this business currently
registered" definition (imported, not restated) so the levy-mechanism
verdict and the registration verdict can never quietly disagree about
what "registered" means for the same BusinessProfile.
"""

from __future__ import annotations

from z3 import And, Bool, Or, Solver, sat

from business_profile import BusinessProfile, OutwardSupplyRecord
from proof_object import ComplianceModule, RuleEvaluation, VerdictStatus
from registration_engine import _is_currently_unregistered


class LevyMechanismEngine:

    def evaluate(self, profile: BusinessProfile) -> list[RuleEvaluation]:
        return [
            self._forward_or_reverse_charge(profile, record)
            for record in profile.outward_supplies
            if record.supply_type in ("TaxableSupply", "CompositeSupply", "MixedSupply")
        ]

    def _forward_or_reverse_charge(self, profile: BusinessProfile, record: OutwardSupplyRecord) -> RuleEvaluation:
        sec9_3 = Bool("sec9_3_notified")
        sec9_4 = Bool("sec9_4_notified")
        supplier_unregistered = Bool("supplier_unregistered")
        recipient_registered = Bool("recipient_registered")
        reverse_charge = Bool("reverse_charge")

        s = Solver()
        s.add(reverse_charge == Or(sec9_3, And(sec9_4, supplier_unregistered, recipient_registered)))
        s.add(sec9_3 == bool(record.is_notified_under_sec9_3))
        s.add(sec9_4 == bool(record.is_notified_under_sec9_4))
        s.add(supplier_unregistered == _is_currently_unregistered(profile))
        # Unknown recipient registration status is treated as NOT registered
        # (the conservative assumption for a Sec 9(4) trigger - it should
        # not fire on a guess), and separately flagged INDETERMINATE below.
        s.add(recipient_registered == bool(record.recipient_is_registered))
        assert s.check() == sat
        model = s.model()

        is_reverse_charge = bool(model.eval(reverse_charge))
        sec9_3_fired = bool(model.eval(sec9_3))
        sec9_4_fired = is_reverse_charge and not sec9_3_fired

        unknown_recipient_status = record.recipient_is_registered is None and record.is_notified_under_sec9_4

        if unknown_recipient_status and not sec9_3_fired:
            return RuleEvaluation(
                rule_id=f"Sec9_LevyMechanism_{record.invoice_number}",
                module=ComplianceModule.SUPPLY_CLASSIFICATION,
                status=VerdictStatus.INDETERMINATE,
                legal_citation="Sec 9(4), CGST Act 2017",
                section_number="9",
                description="Forward vs reverse charge determination.",
                inputs_used={"invoice_number": record.invoice_number, "recipient_is_registered": None},
                explanation_hint=(
                    f"Invoice {record.invoice_number} is in a Sec 9(4)-notified category and "
                    f"{profile.name} is currently unregistered, but the recipient's registration status is "
                    f"unknown - Sec 9(4) reverse charge applies only if the recipient IS registered. "
                    f"Confirm recipient registration status to resolve this."
                ),
            )

        if is_reverse_charge:
            citation = "Sec 9(3), CGST Act 2017" if sec9_3_fired else "Sec 9(4), CGST Act 2017"
            reason = (
                "a Government-notified reverse-charge category of supply (applies regardless of either party's registration)"
                if sec9_3_fired else
                "a Sec 9(4)-notified supply made by an unregistered supplier to a registered recipient"
            )
            explanation = (
                f"Invoice {record.invoice_number} is taxed under the REVERSE CHARGE mechanism ({citation}): "
                f"it is {reason}, so the RECIPIENT (not {profile.name}) is liable to pay the tax."
            )
        else:
            citation = "Sec 9(1), CGST Act 2017"
            explanation = (
                f"Invoice {record.invoice_number} is taxed under the standard FORWARD CHARGE mechanism "
                f"({citation}): {profile.name}, as supplier, collects and pays the tax."
            )

        return RuleEvaluation(
            rule_id=f"Sec9_LevyMechanism_{record.invoice_number}",
            module=ComplianceModule.SUPPLY_CLASSIFICATION,
            status=VerdictStatus.SATISFIED,
            legal_citation=citation,
            section_number="9",
            description="Forward vs reverse charge determination.",
            inputs_used={
                "invoice_number": record.invoice_number,
                "is_notified_under_sec9_3": record.is_notified_under_sec9_3,
                "is_notified_under_sec9_4": record.is_notified_under_sec9_4,
                "supplier_unregistered": _is_currently_unregistered(profile),
                "recipient_is_registered": record.recipient_is_registered,
            },
            explanation_hint=explanation,
        )
