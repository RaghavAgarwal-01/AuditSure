"""
AuditSure Layer 2 - Business Profile Schema
==============================================
The input contract. Every Z3 constraint module in Phases 2-6 takes a
BusinessProfile and returns RuleEvaluations (proof_object.py).

Field names deliberately mirror the ontology's object/data properties
(hasBusinessType -> business_types, belongsToState -> state,
turnoverAmount -> aggregate_turnover, hasSupplyType -> supply_types)
so a future auto-mapper between OWL individuals and Python instances
is a rename-free exercise.

This schema is intentionally broader than Phase 2 needs alone - it
anticipates Phases 3-6 (supply/ITC/compliance/financial) so later
phases don't require re-opening this contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------
#  Enums - values validated against the ontology at construction time
#  (see validate_against_ontology below), not hardcoded as the source
#  of truth. Kept as plain str-Enums for IDE/type-checker friendliness;
#  OntologyLoader.get_business_type_names() etc. remain authoritative.
# ---------------------------------------------------------------------

class RegistrationStatus(str, Enum):
    ACTIVE = "ActiveStatus"
    CANCELLED = "CancelledStatus"
    SUSPENDED = "SuspendedStatus"
    PENDING_CANCELLATION = "PendingForCancellationStatus"
    NOT_REGISTERED = "NotRegistered"          # not an ontology individual -
                                                # sentinel for "never registered"


@dataclass(frozen=True)
class InvoiceRecord:
    """One inward-supply invoice, for Phase 4 (ITC eligibility) constraints.

    Field names map onto the ontology's five gst:ITCEligibilityCondition
    individuals (Sec 16(2)(a)/(aa)/(b)/(c)/(d)) one-to-one - see
    itc_engine.py's SEC16_2_CONDITIONS for the explicit mapping. All
    condition flags default to False (not True) deliberately: a
    compliance tool should never silently assume a condition is met -
    the caller must assert it explicitly for ITC to come out eligible.
    """
    invoice_number: str
    invoice_date: date
    taxable_value: Decimal
    tax_amount: Decimal
    supplier_gstin: Optional[str] = None

    # -- Sec 16(2) conditions (a)/(aa)/(b)/(c)/(d) --------------------------
    has_tax_invoice_or_debit_note: bool = False        # (a) PossessionOfTaxInvoice
    invoice_details_communicated_37_38: bool = False   # (aa) InvoiceDetailsCommunicated
    goods_or_services_received: bool = False           # (b) ReceiptOfGoodsOrServices
    tax_paid_by_supplier_to_government: bool = False   # (c) TaxActuallyPaidToGovernment
    supplier_has_filed_return: bool = False            # (d) ReturnFurnished

    # -- Sec 16(2) second proviso: 180-day payment rule (Rule 37) -----------
    payment_made_to_supplier: bool = False
    payment_date: Optional[date] = None

    # -- Sec 17(5) blocked credit -------------------------------------------
    is_blocked_credit_category: bool = False   # e.g. motor vehicle, food & beverage
    blocked_credit_reason: Optional[str] = None

    # -- Sec 16(4) time bar ---------------------------------------------------
    itc_claimed: bool = False
    itc_utilized: bool = False        # Sec 50(3) interest requires BOTH availed AND utilised
    itc_claim_date: Optional[date] = None
    financial_year: Optional[str] = None       # derived from invoice_date if not given

    # -- Sec 51 TDS compliance (Phase 5) - relevant only when the profile
    #    itself is a specified deductor paying THIS supplier -------------------
    tds_deducted: bool = False


@dataclass(frozen=True)
class OutwardSupplyRecord:
    """One outward supply/invoice line, for Phase 3 (supply classification)
    and Phase 5 (e-invoicing/e-way-bill) constraints."""
    invoice_number: str
    invoice_date: date
    value: Decimal
    supply_type: str                # e.g. "TaxableSupply", "ZeroRatedSupply"
    is_interstate: bool = False
    recipient_state: Optional[str] = None
    is_via_ecommerce_operator: bool = False
    consignment_value: Optional[Decimal] = None   # for e-way bill check

    # -- Phase 3 additions (Sec 16 IGST Act zero-rated validity; Sec 9(3)/
    #    9(4) CGST Act reverse charge determination) -----------------------
    is_export_or_sez_supply: bool = False        # required for a ZeroRatedSupply claim to be valid
    is_notified_under_sec9_3: bool = False        # Sec 9(3): RCM regardless of either party's registration
    is_notified_under_sec9_4: bool = False        # Sec 9(4): RCM only if supplier unregistered + recipient registered
    recipient_is_registered: Optional[bool] = None
    is_composite_supply_principal: Optional[str] = None   # for CompositeSupply: the principal supply's description
    bundled_supply_descriptions: list[str] = field(default_factory=list)  # for MixedSupply: the bundled items


@dataclass(frozen=True)
class TaxPaymentRecord:
    """One tax-period's payment, for Phase 6 Sec 50(1) delayed-payment
    interest. amount_paid_via_cash_ledger is what Sec 50(1) interest (post
    the 2021 amendment) is actually computed on - NOT the full liability,
    since the ITC-offset portion never attracted interest even historically
    once paid via cash for the balance."""
    return_period: str                       # e.g. "2025-06" (June 2025)
    due_date: date
    tax_liability: Decimal
    amount_paid_via_cash_ledger: Decimal
    payment_date: Optional[date] = None


@dataclass(frozen=True)
class RefundClaim:
    """One Sec 54 refund claim."""
    claim_id: str
    claim_type: str            # "ZeroRatedITC" | "InvertedDuty" | "ExcessPayment"
    claim_amount: Decimal
    relevant_date: date         # the date the 2-year limitation period runs from
    filing_date: Optional[date] = None


@dataclass(frozen=True)
class AppealRecord:
    """One Sec 107 appeal against a demand/adjudication order."""
    appeal_id: str
    order_communication_date: date
    admitted_amount: Decimal            # tax/interest/fine/fee/penalty NOT in dispute - must be paid in full
    disputed_tax_amount: Decimal         # the portion actually contested - subject to 10% pre-deposit
    appeal_filed_date: Optional[date] = None


@dataclass
class BusinessProfile:
    # -- Identity -----------------------------------------------------
    name: str
    pan: Optional[str] = None
    gstin: Optional[str] = None

    # -- Jurisdiction & Registration -----------------------------------
    state: str = ""                              # must match a gst:State individual id
    registration_status: RegistrationStatus = RegistrationStatus.NOT_REGISTERED
    registration_date: Optional[date] = None
    voluntarily_registered: bool = False

    # -- Turnover -------------------------------------------------------
    aggregate_turnover: Decimal = Decimal("0")     # current FY, per Sec 2(6) definition
    financial_year: str = ""                       # e.g. "2025-26"
    turnover_by_year: dict[str, Decimal] = field(default_factory=dict)   # for trend/threshold-crossing checks
    annual_return_filed_dates: dict[str, date] = field(default_factory=dict)  # FY string -> Sec 44 filing date

    # -- Business classification (maps to BusinessType subclasses) --------
    business_types: list[str] = field(default_factory=list)     # e.g. ["Manufacturer"]
    is_agriculturist: bool = False
    is_casual_taxable_person: bool = False
    is_non_resident_taxable_person: bool = False
    is_input_service_distributor: bool = False
    is_ecommerce_operator: bool = False
    opts_for_composition: bool = False

    # -- Supply profile (Phase 3/5 inputs) --------------------------------
    makes_interstate_outward_supply: bool = False
    supplies_via_ecommerce_collecting_tcs: bool = False
    is_liable_under_reverse_charge: bool = False
    supplies_notified_reverse_charge_goods_or_services: bool = False
    outward_supplies: list[OutwardSupplyRecord] = field(default_factory=list)

    # -- ITC profile (Phase 4 inputs) -------------------------------------
    inward_invoices: list[InvoiceRecord] = field(default_factory=list)

    # -- Financial consequences profile (Phase 6 inputs) ---------------------
    tax_payment_records: list[TaxPaymentRecord] = field(default_factory=list)
    refund_claims: list[RefundClaim] = field(default_factory=list)
    appeal_records: list[AppealRecord] = field(default_factory=list)

    # -- Misc flags used by multiple phases --------------------------------
    supplies_exclusively_exempt_or_nontaxable_goods: bool = False
    is_deductor_under_section51: bool = False
    is_required_to_collect_tcs_under_section52: bool = False

    # -- Free-form extension point (avoid re-opening the schema for
    #    one-off / experimental fields during development) -----------------
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        self.aggregate_turnover = Decimal(str(self.aggregate_turnover))
        self.turnover_by_year = {k: Decimal(str(v)) for k, v in self.turnover_by_year.items()}

    # -- Convenience -------------------------------------------------------
    def has_business_type(self, type_name: str) -> bool:
        return type_name in self.business_types

    def to_dict(self) -> dict:
        import dataclasses
        def conv(v):
            if isinstance(v, Decimal):
                return float(v)
            if isinstance(v, date):
                return v.isoformat()
            if isinstance(v, Enum):
                return v.value
            if dataclasses.is_dataclass(v):
                return {k: conv(val) for k, val in dataclasses.asdict(v).items()}
            if isinstance(v, (list, tuple)):
                return [conv(x) for x in v]
            if isinstance(v, dict):
                return {k: conv(val) for k, val in v.items()}
            return v
        return {f.name: conv(getattr(self, f.name)) for f in dataclasses.fields(self)}


def validate_against_ontology(profile: BusinessProfile, onto) -> list[str]:
    """Cross-checks profile field VALUES against live ontology individuals.
    Returns a list of human-readable warnings (empty list = fully valid).
    `onto` is an OntologyLoader instance (Phase 1's other module) - kept as
    a plain argument rather than an import to avoid a circular dependency
    and to let callers validate against a specific ontology version.
    """
    warnings: list[str] = []

    valid_states = set(onto.get_state_names())
    if profile.state and profile.state not in valid_states:
        warnings.append(f"state '{profile.state}' is not a known gst:State individual.")

    valid_business_types = set(onto.get_business_type_names())
    for bt in profile.business_types:
        if bt not in valid_business_types:
            warnings.append(f"business_type '{bt}' is not a known gst:BusinessType subclass.")

    valid_supply_types = set(onto.get_supply_type_names())
    for s in profile.outward_supplies:
        if s.supply_type not in valid_supply_types:
            warnings.append(f"outward supply '{s.invoice_number}' has unknown supply_type '{s.supply_type}'.")

    if profile.registration_status != RegistrationStatus.NOT_REGISTERED:
        valid_statuses = set(onto.get_registration_status_names())
        if profile.registration_status.value not in valid_statuses:
            warnings.append(f"registration_status '{profile.registration_status}' not a known gst:RegistrationStatus individual.")

    return warnings
