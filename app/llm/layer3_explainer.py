"""
AuditSure Layer 3 Bridge - Groq LLM Explainer
================================================
Thin wrapper that sends a Layer 2 ProofObject's deterministic prompt
to Groq and returns a plain-English explanation.

IMPORTANT ARCHITECTURAL RULE:
Layer 3 explains the verified ProofObject.
It does NOT perform GST compliance reasoning.

All legal reasoning has already happened in Layer 2.

This is intentionally the ONLY module in the codebase that touches
the external LLM API or API credentials. All Layer 2 modules remain
pure, offline, and deterministic.
"""

from __future__ import annotations

import os

from app.llm.explanation_prompt import SYSTEM_PROMPT, build_messages
from app.models.proof_object import ProofObject

DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_MAX_TOKENS = 2000


class Layer3ConfigurationError(RuntimeError):
    """Raised when a real Layer 3 call cannot be configured."""


class Layer3Explainer:

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        dry_run: bool | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        # Explicit model argument > GROQ_MODEL environment variable
        # > default model.
        self.model = model or os.environ.get(
            "GROQ_MODEL",
            DEFAULT_MODEL,
        )

        self.max_tokens = max_tokens

        # Explicit API key > GROQ_API_KEY environment variable.
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")

        # Automatically use dry-run mode when no API key is configured.
        self.dry_run = (
            dry_run
            if dry_run is not None
            else (self.api_key is None)
        )

    def explain(self, proof: ProofObject) -> str:
        messages = build_messages(proof)

        # ------------------------------------------------------------
        # Offline / deterministic mode
        # ------------------------------------------------------------
        if self.dry_run:
            return (
                "[DRY RUN - no GROQ_API_KEY configured; showing the exact "
                "prompt that would be sent instead of a real explanation]\n\n"
                f"--- SYSTEM PROMPT ---\n{SYSTEM_PROMPT}\n\n"
                f"--- USER MESSAGE ---\n{messages[0]['content']}"
            )

        # ------------------------------------------------------------
        # Configuration validation
        # ------------------------------------------------------------
        if not self.api_key:
            raise Layer3ConfigurationError(
                "No GROQ API key configured. Set the GROQ_API_KEY "
                "environment variable, pass api_key= explicitly, "
                "or use dry_run=True for offline testing."
            )

        # ------------------------------------------------------------
        # Import Groq SDK
        # ------------------------------------------------------------
        try:
            from groq import Groq
        except ImportError as exc:
            raise Layer3ConfigurationError(
                "The 'groq' package is not installed. "
                "Run `pip install groq`."
            ) from exc

        # ------------------------------------------------------------
        # Real Groq API call
        # ------------------------------------------------------------
        try:
            client = Groq(api_key=self.api_key)

            response = client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT,
                    },
                    *messages,
                ],
            )

        except Exception as exc:
            raise Layer3ConfigurationError(
                f"Groq API request failed: {exc}"
            ) from exc

        # ------------------------------------------------------------
        # Extract generated explanation
        # ------------------------------------------------------------
        content = response.choices[0].message.content

        if not content:
            raise Layer3ConfigurationError(
                "Groq returned an empty explanation."
            )

        return content