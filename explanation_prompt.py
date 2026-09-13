"""
AuditSure Layer 3 Bridge - Prompt Construction
====================================================
Turns a Layer 2 ProofObject into the exact prompt Layer 3's LLM call
uses. Deliberately kept in its own module, separate from the actual API
call (layer3_explainer.py), so prompt construction is 100% deterministic
and unit-testable without network access or credentials - the same
ProofObject must always produce the same prompt.

DESIGN PRINCIPLE - Layer 3 explains, it does not decide:
Per the AuditSure architecture ("Layer 3 only converts verified proof
objects into human-readable explanations"), the system prompt is
explicit that the LLM must not introduce any legal claim, citation,
threshold, or figure that isn't already present in the proof object
text handed to it. All legal reasoning happened symbolically in Layer 2
(Phases 2-6); Layer 3's only job is presentation - rephrasing and
organizing already-verified findings for a non-technical reader. This
is the actual point of the neuro-symbolic split: it bounds what the LLM
is allowed to hallucinate about to zero legal content.
"""

from __future__ import annotations

from proof_object import ProofObject, RuleEvaluation, VerdictStatus

SYSTEM_PROMPT = """You are the explanation layer of AuditSure, a neuro-symbolic GST \
compliance system for Indian MSMEs. All legal determinations have ALREADY been made \
by a symbolic (Z3) reasoning engine against a validated GST law ontology - you are not \
determining compliance, you are explaining a decision that has already been made.

STRICT RULES:
1. You may ONLY use facts, figures, legal citations, and conclusions that appear in the \
proof object provided to you. Never introduce a section number, threshold amount, rate, \
or legal claim that is not already present in the input.
2. Never soften, omit, or contradict a VIOLATED finding. Never present an INDETERMINATE \
finding as if it were resolved.
3. Write for a non-technical MSME business owner: plain language, short sentences, no \
legal jargon left unexplained.
4. Preserve every legal citation exactly as given (e.g. "Sec 22(1), CGST Act 2017") so the \
reader can look it up or show it to their accountant.
5. Do not give new advice beyond what the explanation_hint fields already state - your job \
is to organize and clarify, not to extend the legal analysis.
6. If the proof object contains no findings at all, say so plainly rather than inventing \
a compliance status.

OUTPUT FORMAT (Markdown):
## Summary
One short paragraph: overall compliance posture in plain language.

## Action Required
Each VIOLATED finding as a bullet: what's wrong, the citation, and the concrete number(s) \
involved. Omit this section if there are none.

## Needs More Information
Each INDETERMINATE finding as a bullet: what's unresolved and what fact would resolve it. \
Omit this section if there are none.

## Compliant Areas
A brief bullet list of SATISFIED findings, grouped by topic rather than listed one by one \
if there are many. Omit this section if there are none.

Do not include a section for NOT_APPLICABLE findings unless one is directly relevant to \
explaining a nearby violation."""


def _format_evaluation(e: RuleEvaluation) -> str:
    parts = [
        f"- rule_id: {e.rule_id}",
        f"  module: {e.module.value}",
        f"  status: {e.status.value}",
        f"  legal_citation: {e.legal_citation}",
        f"  description: {e.description}",
    ]
    if e.computed_value is not None:
        parts.append(f"  computed_value: {e.computed_value}")
    if e.threshold_value is not None:
        parts.append(f"  threshold_value: {e.threshold_value}")
    parts.append(f"  explanation_hint: {e.explanation_hint}")
    return "\n".join(parts)


def build_user_prompt(proof: ProofObject) -> str:
    """Deterministic: the same ProofObject always yields the same string."""
    header = (
        f"Business: {proof.business_name}\n"
        f"Financial Year: {proof.financial_year}\n"
        f"Generated at: {proof.generated_at.isoformat()}\n"
        f"Ontology version: {proof.ontology_version}\n"
        f"Summary counts: {proof.summary_counts()}\n"
    )

    if not proof.evaluations:
        return header + "\nNo compliance findings were generated for this business profile."

    sections = []
    for status in (VerdictStatus.VIOLATED, VerdictStatus.INDETERMINATE,
                   VerdictStatus.SATISFIED, VerdictStatus.NOT_APPLICABLE):
        items = proof.by_status(status)
        if not items:
            continue
        block = f"\n=== {status.value} ({len(items)}) ===\n" + "\n\n".join(_format_evaluation(e) for e in items)
        sections.append(block)

    return header + "\n".join(sections)


def build_messages(proof: ProofObject) -> list[dict]:
    """Builds the user message for the Layer 3 chat-completion call.

    The system prompt is supplied separately by Layer3Explainer so the
    prompt-construction layer remains deterministic and provider-neutral.
    """
    return [{"role": "user", "content": build_user_prompt(proof)}]
