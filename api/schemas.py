"""
AuditSure API - Pydantic Schemas
=====================================
Pydantic is the HTTP transport boundary ONLY. It validates and parses
incoming JSON, then request bodies are dumped back to a plain dict
(`model_dump(mode="json", exclude_unset=True)`) and handed to the
EXISTING canonical converter, `app.io.profile_loader.load_profile_from_dict`,
which builds the real `BusinessProfile` dataclass tree. There is
deliberately no second, divergent JSON -> BusinessProfile implementation
here (see profile_loader.py's own docstring).

Field names and structure mirror app.models.business_profile exactly -
nothing here is invented. Enum fields reuse the actual domain Enum
(RegistrationStatus) so an invalid value is rejected before it ever
reaches the domain layer. `state`, `business_types`, and `supply_type`
remain plain strings (validated live against the ontology downstream,
in validate_against_ontology) rather than a hardcoded Pydantic enum,
because their valid values live in the ontology and can change without
a code deploy.

Decimal and date fields use the real Python types; Pydantic v2 already
parses "2500000" or 2500000 into Decimal, and "2026-09-10" into date,
and (critically) `model_dump(mode="json")` serializes Decimal back to a
JSON-safe *string* (never a lossy float) and date to an ISO string -
exactly what profile_loader.py's `_convert_value` expects to parse.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.business_profile import RegistrationStatus

# Generous but finite bounds on submitted list sizes (item 80: resource
# protection). High enough that no legitimate demo/test profile is
# affected; low enough that a client can't submit an unbounded payload.
_MAX_RECORDS = 2000


class ApiModel(BaseModel):
    """Shared config: reject unknown fields so a typo produces a clean
    422 at the HTTP boundary rather than falling through to a less
    specific ProfileLoadError deeper in the stack."""

    model_config = ConfigDict(extra="forbid")


class InvoiceRecordSchema(ApiModel):
    """One inward-supply invoice - Phase 4 ITC eligibility input.
    Mirrors app.models.business_profile.InvoiceRecord exactly."""

    invoice_number: str
    invoice_date: date
    taxable_value: Decimal = Field(..., description="Taxable value of the supply, in INR.")
    tax_amount: Decimal = Field(..., description="GST charged on the invoice, in INR.")
    supplier_gstin: Optional[str] = None

    has_tax_invoice_or_debit_note: bool = False
    invoice_details_communicated_37_38: bool = False
    goods_or_services_received: bool = False
    tax_paid_by_supplier_to_government: bool = False
    supplier_has_filed_return: bool = False

    payment_made_to_supplier: bool = False
    payment_date: Optional[date] = None

    is_blocked_credit_category: bool = False
    blocked_credit_reason: Optional[str] = None

    itc_claimed: bool = False
    itc_utilized: bool = False
    itc_claim_date: Optional[date] = None
    financial_year: Optional[str] = None

    tds_deducted: bool = False


class OutwardSupplyRecordSchema(ApiModel):
    """One outward supply/invoice line - Phase 3 supply classification
    and Phase 5 e-invoicing/e-way-bill input. Mirrors
    app.models.business_profile.OutwardSupplyRecord exactly."""

    invoice_number: str
    invoice_date: date
    value: Decimal = Field(..., description="Value of the outward supply, in INR.")
    supply_type: str = Field(
        ...,
        description="An ontology gst:Supply subclass id, e.g. 'TaxableSupply', 'ZeroRatedSupply'.",
    )
    is_interstate: bool = False
    recipient_state: Optional[str] = None
    is_via_ecommerce_operator: bool = False
    consignment_value: Optional[Decimal] = None

    is_export_or_sez_supply: bool = False
    is_notified_under_sec9_3: bool = False
    is_notified_under_sec9_4: bool = False
    recipient_is_registered: Optional[bool] = None
    is_composite_supply_principal: Optional[str] = None
    bundled_supply_descriptions: list[str] = Field(default_factory=list, max_length=_MAX_RECORDS)


class TaxPaymentRecordSchema(ApiModel):
    """One tax-period's payment - Phase 6 Sec 50(1) interest input.
    Mirrors app.models.business_profile.TaxPaymentRecord exactly."""

    return_period: str = Field(..., description="e.g. '2025-06' for June 2025.")
    due_date: date
    tax_liability: Decimal
    amount_paid_via_cash_ledger: Decimal
    payment_date: Optional[date] = None


class RefundClaimSchema(ApiModel):
    """One Sec 54 refund claim. Mirrors
    app.models.business_profile.RefundClaim exactly."""

    claim_id: str
    claim_type: str = Field(..., description="'ZeroRatedITC' | 'InvertedDuty' | 'ExcessPayment'")
    claim_amount: Decimal
    relevant_date: date
    filing_date: Optional[date] = None


class AppealRecordSchema(ApiModel):
    """One Sec 107 appeal. Mirrors
    app.models.business_profile.AppealRecord exactly."""

    appeal_id: str
    order_communication_date: date
    admitted_amount: Decimal
    disputed_tax_amount: Decimal
    appeal_filed_date: Optional[date] = None


class BusinessProfileSchema(ApiModel):
    """HTTP transport mirror of app.models.business_profile.BusinessProfile.
    Every field name and default matches the domain dataclass one-to-one -
    see that module's docstring for the legal rationale behind each field."""

    name: str = Field(..., description="Business name, used as the ProofObject label.")
    pan: Optional[str] = None
    gstin: Optional[str] = None

    state: str = Field("", description="An ontology gst:State individual id, e.g. 'Karnataka'.")
    registration_status: RegistrationStatus = RegistrationStatus.NOT_REGISTERED
    registration_date: Optional[date] = None
    voluntarily_registered: bool = False

    aggregate_turnover: Decimal = Field(
        Decimal("0"), description="Current FY aggregate turnover, per Sec 2(6), in INR."
    )
    financial_year: str = Field("", description="e.g. '2025-26'.")
    turnover_by_year: dict[str, Decimal] = Field(default_factory=dict)
    annual_return_filed_dates: dict[str, date] = Field(default_factory=dict)

    business_types: list[str] = Field(
        default_factory=list,
        max_length=_MAX_RECORDS,
        description="Ontology gst:BusinessType subclass ids, e.g. ['Manufacturer'].",
    )
    is_agriculturist: bool = False
    is_casual_taxable_person: bool = False
    is_non_resident_taxable_person: bool = False
    is_input_service_distributor: bool = False
    is_ecommerce_operator: bool = False
    opts_for_composition: bool = False

    makes_interstate_outward_supply: bool = False
    supplies_via_ecommerce_collecting_tcs: bool = False
    is_liable_under_reverse_charge: bool = False
    supplies_notified_reverse_charge_goods_or_services: bool = False
    outward_supplies: list[OutwardSupplyRecordSchema] = Field(
        default_factory=list, max_length=_MAX_RECORDS
    )

    inward_invoices: list[InvoiceRecordSchema] = Field(default_factory=list, max_length=_MAX_RECORDS)

    tax_payment_records: list[TaxPaymentRecordSchema] = Field(
        default_factory=list, max_length=_MAX_RECORDS
    )
    refund_claims: list[RefundClaimSchema] = Field(default_factory=list, max_length=_MAX_RECORDS)
    appeal_records: list[AppealRecordSchema] = Field(default_factory=list, max_length=_MAX_RECORDS)

    supplies_exclusively_exempt_or_nontaxable_goods: bool = False
    is_deductor_under_section51: bool = False
    is_required_to_collect_tcs_under_section52: bool = False

    extra: dict = Field(default_factory=dict)


class ComplianceCheckRequest(ApiModel):
    """POST /api/compliance/check request body."""

    profile: BusinessProfileSchema
    as_of: Optional[date] = Field(
        None,
        description="ISO date to evaluate as of. Defaults to today if omitted.",
        examples=["2026-09-10"],
    )

    model_config = ConfigDict(
        extra="forbid",
        # Sourced verbatim from examples/small_composition_trader.json -
        # a real, already-validated demo persona - per item 53
        # ("prefer a sanitized real example").
        json_schema_extra={
            "examples": [
                {
                    "profile": {
                        "name": "Meenakshi General Store",
                        "state": "TamilNadu",
                        "aggregate_turnover": "1800000",
                        "financial_year": "2025-26",
                        "business_types": ["Trader"],
                        "opts_for_composition": True,
                        "registration_status": "ActiveStatus",
                    },
                    "as_of": "2026-09-10",
                }
            ]
        },
    )


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    ontology_version: Optional[str] = None
    detail: Optional[str] = None


class DemoSummary(BaseModel):
    id: str
    name: Optional[str] = None
    state: Optional[str] = None
    financial_year: Optional[str] = None
    business_types: list[str] = Field(default_factory=list)
    aggregate_turnover: Optional[str] = None
    registration_status: Optional[str] = None
