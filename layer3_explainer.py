"""
AuditSure Layer 3 Bridge - LLM Explainer
==============================================
Thin wrapper that sends a Layer 2 ProofObject's prompt (built
deterministically by explanation_prompt.py) to an LLM and returns the
resulting explanation. This is intentionally the ONLY module in the
codebase that touches the network / API credentials - every other
Layer 2 module is pure, offline, testable Python.

DRY-RUN MODE: this development sandbox has no ANTHROPIC_API_KEY, so
Layer3Explainer supports dry_run=True, which returns the exact prompt
that WOULD be sent, instead of calling the API. This keeps the
integration code real and complete (not a stub commented out "for
later") while still being fully testable without credentials or
network access. Flip dry_run=False (or leave the API key set) to get
real explanations in a deployment that has one.
"""

from __future__ import annotations

import os

from explanation_prompt import SYSTEM_PROMPT, build_messages
from proof_object import ProofObject

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 2000


class Layer3ConfigurationError(RuntimeError):
    """Raised when a real (non-dry-run) call is attempted without the
    anthropic package installed or without an API key configured."""


class Layer3Explainer:

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None,
                 dry_run: bool | None = None, max_tokens: int = DEFAULT_MAX_TOKENS):
        self.model = model
        self.max_tokens = max_tokens
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        # Auto-detect: if no key is configured, default to dry-run rather
        # than failing - this is what makes `python3 layer3_explainer.py`
        # runnable out of the box in any environment.
        self.dry_run = dry_run if dry_run is not None else (self.api_key is None)

    def explain(self, proof: ProofObject) -> str:
        messages = build_messages(proof)

        if self.dry_run:
            return (
                "[DRY RUN - no ANTHROPIC_API_KEY configured; showing the exact prompt "
                "that would be sent instead of a real explanation]\n\n"
                f"--- SYSTEM PROMPT ---\n{SYSTEM_PROMPT}\n\n"
                f"--- USER MESSAGE ---\n{messages[0]['content']}"
            )

        try:
            import anthropic
        except ImportError as exc:
            raise Layer3ConfigurationError(
                "The 'anthropic' package is not installed. Run `pip install anthropic` "
                "to make real (non-dry-run) Layer 3 calls."
            ) from exc

        if not self.api_key:
            raise Layer3ConfigurationError(
                "No API key configured. Set the ANTHROPIC_API_KEY environment variable, "
                "or pass api_key= explicitly, or use dry_run=True for offline testing."
            )

        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        return "".join(block.text for block in response.content if block.type == "text")


if __name__ == "__main__":
    from datetime import date
    from decimal import Decimal

    from business_profile import BusinessProfile, InvoiceRecord
    from ontology_loader import OntologyLoader
    from phase6_pipeline import run_phase6

    onto = OntologyLoader()
    profile = BusinessProfile(
        name="Ramesh Auto Parts", state="Maharashtra",
        aggregate_turnover=Decimal("2500000"), financial_year="2025-26",
        business_types=["Trader"],
        inward_invoices=[
            InvoiceRecord(
                invoice_number="INV-9", invoice_date=date(2025, 6, 1),
                taxable_value=Decimal("100000"), tax_amount=Decimal("18000"),
                has_tax_invoice_or_debit_note=True, invoice_details_communicated_37_38=True,
                goods_or_services_received=True, tax_paid_by_supplier_to_government=True,
                supplier_has_filed_return=False, itc_claimed=True, itc_utilized=True,
                itc_claim_date=date(2025, 7, 1),
            ),
        ],
    )
    proof = run_phase6(profile, onto, as_of_date=date(2026, 9, 10))
    explanation = Layer3Explainer().explain(proof)   # auto-dry-run: no key in this environment
    print(explanation)
