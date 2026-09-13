"""
AuditSure Layer 2 - Phase 3a: Supply Classification Engine
================================================================
Operates on BusinessProfile.outward_supplies (per-invoice records) and
checks three things per Sec 7/8 CGST Act and Sec 16 IGST Act:

  1. Zero-rated validity (Sec 16, IGST Act): a supply classified as
     ZeroRatedSupply is only legally zero-rated if it is actually an
     export or a supply to a SEZ developer/unit. A record marked
     ZeroRatedSupply without that backing fact is a misclassification -
     this is exactly the kind of data-entry error a symbolic layer
     should catch before it reaches a tax return.

  2. Place-of-supply consistency (Sec 7/8, IGST Act): whether a supply
     is inter-State or intra-State is a FACT (supplier's State vs
     recipient's State), not a free-text flag a preparer can set
     independently. This engine derives the correct classification from
     profile.state + record.recipient_state and cross-checks it against
     the record's declared is_interstate flag AND against the
     profile-level `makes_interstate_outward_supply` summary flag that
     Phase 2's Sec 24 check depends on - catching the case where the
     summary flag and the underlying invoice data disagree, which would
     silently produce a wrong Sec 24 registration verdict upstream.

  3. Composite/Mixed supply tax-rate rule (Sec 8(a)/(b)): states which
     rule applies (principal-supply rate for composite; highest-rate
     item for mixed) WITHOUT asserting a specific numeric GST rate,
     since HSN-wise rate slabs are not part of the source manual (see
     Layer 1 ontology's documented placeholder policy for gst:TaxRate).
"""

from __future__ import annotations

from z3 import Bool, Implies, Solver, sat

from business_profile import BusinessProfile, OutwardSupplyRecord
from proof_object import ComplianceModule, RuleEvaluation, VerdictStatus


class SupplyClassificationEngine:

    def evaluate(self, profile: BusinessProfile) -> list[RuleEvaluation]:
        evaluations: list[RuleEvaluation] = []
        for record in profile.outward_supplies:
            evaluations.append(self._zero_rated_validity(profile, record))
            pos_eval = self._place_of_supply_consistency(profile, record)
            if pos_eval:
                evaluations.append(pos_eval)
            bundle_eval = self._composite_or_mixed_rule(profile, record)
            if bundle_eval:
                evaluations.append(bundle_eval)

        summary_eval = self._interstate_summary_flag_consistency(profile)
        if summary_eval:
            evaluations.append(summary_eval)

        return evaluations

    # -- 1. Zero-rated validity (Sec 16, IGST Act) --------------------------

    def _zero_rated_validity(self, profile: BusinessProfile, record: OutwardSupplyRecord) -> RuleEvaluation:
        declared_zero_rated = Bool("declared_zero_rated")
        is_export_or_sez = Bool("is_export_or_sez")
        valid = Bool("valid")

        s = Solver()
        s.add(valid == Implies(declared_zero_rated, is_export_or_sez))
        s.add(declared_zero_rated == (record.supply_type == "ZeroRatedSupply"))
        s.add(is_export_or_sez == bool(record.is_export_or_sez_supply))
        assert s.check() == sat
        model = s.model()
        is_valid = bool(model.eval(valid))
        is_zero_rated_claim = record.supply_type == "ZeroRatedSupply"

        if not is_zero_rated_claim:
            status = VerdictStatus.NOT_APPLICABLE
            explanation = f"Invoice {record.invoice_number} is not classified as a zero-rated supply; Sec 16 IGST Act does not apply."
        elif is_valid:
            status = VerdictStatus.SATISFIED
            explanation = (
                f"Invoice {record.invoice_number} is correctly classified as a zero-rated supply under "
                f"Sec 16, IGST Act 2017, being an export/SEZ supply."
            )
        else:
            status = VerdictStatus.VIOLATED
            explanation = (
                f"Invoice {record.invoice_number} is classified as ZeroRatedSupply but is not marked as an "
                f"export or SEZ supply - Sec 16, IGST Act 2017 only zero-rates exports and supplies to a SEZ "
                f"developer/unit. This looks like a misclassification: reclassify as TaxableSupply (or confirm "
                f"and record the export/SEZ fact) before filing."
            )

        return RuleEvaluation(
            rule_id=f"Sec16IGST_ZeroRatedValidity_{record.invoice_number}",
            module=ComplianceModule.SUPPLY_CLASSIFICATION,
            status=status,
            legal_citation="Sec 16, IGST Act 2017",
            section_number="16",
            description="Zero-rated supply classification validity check.",
            inputs_used={
                "invoice_number": record.invoice_number,
                "supply_type": record.supply_type,
                "is_export_or_sez_supply": record.is_export_or_sez_supply,
            },
            explanation_hint=explanation,
        )

    # -- 2. Place of supply consistency (Sec 7/8, IGST Act) ------------------

    def _place_of_supply_consistency(self, profile: BusinessProfile, record: OutwardSupplyRecord) -> RuleEvaluation | None:
        if not record.recipient_state:
            return RuleEvaluation(
                rule_id=f"Sec7_8IGST_PlaceOfSupply_{record.invoice_number}",
                module=ComplianceModule.SUPPLY_CLASSIFICATION,
                status=VerdictStatus.INDETERMINATE,
                legal_citation="Sec 7/8, IGST Act 2017",
                section_number="7",
                description="Inter-State/Intra-State classification check.",
                inputs_used={"invoice_number": record.invoice_number, "recipient_state": None},
                explanation_hint=(
                    f"Invoice {record.invoice_number} has no recipient State on record, so its Sec 7/8 "
                    f"inter-State/intra-State classification cannot be verified."
                ),
            )

        derived_interstate = record.recipient_state != profile.state
        declared = Bool("declared_interstate")
        derived = Bool("derived_interstate")
        consistent = Bool("consistent")

        s = Solver()
        s.add(consistent == (declared == derived))
        s.add(declared == bool(record.is_interstate))
        s.add(derived == bool(derived_interstate))
        assert s.check() == sat
        is_consistent = bool(s.model().eval(consistent))

        classification = "InterStateSupply" if derived_interstate else "IntraStateSupply"
        citation = "Sec 7, IGST Act 2017" if derived_interstate else "Sec 8, IGST Act 2017"

        if is_consistent:
            return RuleEvaluation(
                rule_id=f"Sec7_8IGST_PlaceOfSupply_{record.invoice_number}",
                module=ComplianceModule.SUPPLY_CLASSIFICATION,
                status=VerdictStatus.SATISFIED,
                legal_citation=citation,
                section_number="7" if derived_interstate else "8",
                description="Inter-State/Intra-State classification check.",
                inputs_used={
                    "invoice_number": record.invoice_number,
                    "supplier_state": profile.state,
                    "recipient_state": record.recipient_state,
                    "declared_is_interstate": record.is_interstate,
                },
                explanation_hint=(
                    f"Invoice {record.invoice_number} ({profile.state} -> {record.recipient_state}) is correctly "
                    f"classified as a {classification} under {citation}."
                ),
            )
        return RuleEvaluation(
            rule_id=f"Sec7_8IGST_PlaceOfSupply_{record.invoice_number}",
            module=ComplianceModule.SUPPLY_CLASSIFICATION,
            status=VerdictStatus.VIOLATED,
            legal_citation=citation,
            section_number="7" if derived_interstate else "8",
            description="Inter-State/Intra-State classification check.",
            inputs_used={
                "invoice_number": record.invoice_number,
                "supplier_state": profile.state,
                "recipient_state": record.recipient_state,
                "declared_is_interstate": record.is_interstate,
            },
            explanation_hint=(
                f"Invoice {record.invoice_number} is declared as "
                f"{'inter-State' if record.is_interstate else 'intra-State'}, but the supplier State "
                f"({profile.state}) vs recipient State ({record.recipient_state}) actually makes this a "
                f"{classification} under {citation} - this determines whether IGST or CGST+SGST applies, "
                f"so the mismatch should be corrected before filing."
            ),
        )

    # -- 3. Composite/Mixed supply rate rule (Sec 8(a)/(b)) -------------------

    def _composite_or_mixed_rule(self, profile: BusinessProfile, record: OutwardSupplyRecord) -> RuleEvaluation | None:
        if record.supply_type == "CompositeSupply":
            principal = record.is_composite_supply_principal
            return RuleEvaluation(
                rule_id=f"Sec8a_CompositeSupplyRate_{record.invoice_number}",
                module=ComplianceModule.SUPPLY_CLASSIFICATION,
                status=VerdictStatus.INDETERMINATE if not principal else VerdictStatus.SATISFIED,
                legal_citation="Sec 8(a), CGST Act 2017",
                section_number="8",
                description="Composite supply tax-rate rule (taxed at the principal supply's rate).",
                inputs_used={"invoice_number": record.invoice_number, "principal_supply": principal},
                explanation_hint=(
                    f"Invoice {record.invoice_number} is a composite supply, so under Sec 8(a) it is taxed "
                    f"entirely at the rate applicable to its principal supply"
                    + (f" ({principal})." if principal else
                       ", but no principal supply has been identified on this record - specify one to "
                       "determine the applicable rate. (Numeric GST rate slabs are outside this system's "
                       "modelled scope; see Layer 1 ontology notes.)")
                ),
            )
        if record.supply_type == "MixedSupply":
            items = record.bundled_supply_descriptions
            return RuleEvaluation(
                rule_id=f"Sec8b_MixedSupplyRate_{record.invoice_number}",
                module=ComplianceModule.SUPPLY_CLASSIFICATION,
                status=VerdictStatus.INDETERMINATE,
                legal_citation="Sec 8(b), CGST Act 2017",
                section_number="8",
                description="Mixed supply tax-rate rule (taxed at the highest rate among bundled items).",
                inputs_used={"invoice_number": record.invoice_number, "bundled_items": items},
                explanation_hint=(
                    f"Invoice {record.invoice_number} is a mixed supply, so under Sec 8(b) it is taxed at "
                    f"whichever of its bundled items ({', '.join(items) if items else 'not itemised'}) attracts "
                    f"the highest rate. (Numeric GST rate slabs are outside this system's modelled scope.)"
                ),
            )
        return None

    # -- Cross-check: does the per-invoice data agree with the summary flag? --

    def _interstate_summary_flag_consistency(self, profile: BusinessProfile) -> RuleEvaluation | None:
        if not profile.outward_supplies:
            return None
        actual_has_interstate = any(
            (r.recipient_state and r.recipient_state != profile.state) or r.is_interstate
            for r in profile.outward_supplies
        )
        declared = Bool("declared_flag")
        actual = Bool("actual_from_records")
        consistent = Bool("consistent")
        s = Solver()
        s.add(consistent == (declared == actual))
        s.add(declared == bool(profile.makes_interstate_outward_supply))
        s.add(actual == bool(actual_has_interstate))
        assert s.check() == sat
        if bool(s.model().eval(consistent)):
            return None   # no news is good news - don't clutter the proof object

        return RuleEvaluation(
            rule_id="ProfileFlag_InterstateSupplyConsistency",
            module=ComplianceModule.SUPPLY_CLASSIFICATION,
            status=VerdictStatus.VIOLATED,
            legal_citation="Sec 24(i), CGST Act 2017",
            section_number="24",
            description="Cross-check: profile-level makes_interstate_outward_supply flag vs actual invoice records.",
            inputs_used={
                "declared_flag": profile.makes_interstate_outward_supply,
                "derived_from_invoices": actual_has_interstate,
            },
            explanation_hint=(
                f"{profile.name}'s profile declares makes_interstate_outward_supply="
                f"{profile.makes_interstate_outward_supply}, but the outward-supply invoice records "
                f"{'DO' if actual_has_interstate else 'do NOT'} show an inter-State supply. This flag feeds "
                f"directly into the Sec 24 compulsory-registration check (Phase 2) - correct it before "
                f"relying on that verdict."
            ),
        )
