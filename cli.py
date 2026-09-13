#!/usr/bin/env python3
"""
AuditSure CLI - Phase 9 Demo Interface
============================================
Three ways to run it:

  python3 cli.py --demo growing_manufacturer      # built-in example personas
  python3 cli.py --profile my_business.json       # your own JSON profile
  python3 cli.py --interactive                    # guided prompts, no JSON needed

Shows the compliance verdict (grouped, colour-coded proof chain of every
Section/Rule that fired) and the Layer 3 plain-English explanation
(dry-run by default - set GROQ_API_KEY for a real LLM-written one).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

# Make CLI output UTF-8-safe on Windows and redirected output.
# Windows console / subprocess encoding compatibility.
#
# Interactive terminal:
#   Use UTF-8 so Rich can display ₹ and other Unicode characters.
#
# Captured / redirected output:
#   Use ASCII so pytest's Windows cp1252 decoder can safely read it.
if hasattr(sys.stdout, "reconfigure"):
    if sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="ascii", errors="replace")

if hasattr(sys.stderr, "reconfigure"):
    if sys.stderr.isatty():
        sys.stderr.reconfigure(encoding="utf-8")
    else:
        sys.stderr.reconfigure(encoding="ascii", errors="replace")

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from auditsure_pipeline import generate_explanation
from business_profile import BusinessProfile, RegistrationStatus
from layer3_explainer import Layer3Explainer
from ontology_loader import OntologyLoader, get_default_loader
from profile_loader import ProfileLoadError, load_profile_from_json
from proof_object import ProofObject, VerdictStatus

EXAMPLES_DIR = Path(__file__).parent / "examples"

STATUS_STYLE = {
    VerdictStatus.VIOLATED: ("red", "FAIL"),
    VerdictStatus.INDETERMINATE: ("yellow", "?"),
    VerdictStatus.SATISFIED: ("green", "OK"),
    VerdictStatus.NOT_APPLICABLE: ("grey58", "N/A"),
}

STATUS_PRIORITY = {
    VerdictStatus.VIOLATED: 0,
    VerdictStatus.INDETERMINATE: 1,
    VerdictStatus.SATISFIED: 2,
    VerdictStatus.NOT_APPLICABLE: 3,
}

console = Console()


def render_summary(proof: ProofObject) -> None:
    counts = proof.summary_counts()
    table = Table(title=f"Compliance Summary - {proof.business_name} (FY {proof.financial_year})",
                   show_header=True, header_style="bold")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    for status in (VerdictStatus.VIOLATED, VerdictStatus.INDETERMINATE,
                   VerdictStatus.SATISFIED, VerdictStatus.NOT_APPLICABLE):
        color, icon = STATUS_STYLE[status]
        table.add_row(f"[{color}]{icon} {status.value}[/{color}]", str(counts[status.value]))
    console.print(table)
    console.print(f"[dim]Ontology version: {proof.ontology_version} | Generated: {proof.generated_at.isoformat()}[/dim]\n")


def render_proof_chain(proof: ProofObject, onto: OntologyLoader) -> None:
    """The 'proof chain' visualization: every Section/Rule that fired,
    grouped by module, sorted VIOLATED-first within each module so the
    most urgent findings are always at the top."""
    tree = Tree(f"[bold]GST Compliance Proof Chain: {proof.business_name}[/bold]")

    by_module: dict[str, list] = {}
    for e in proof.evaluations:
        by_module.setdefault(e.module.value, []).append(e)

    for module_name, evaluations in by_module.items():
        module_branch = tree.add(f"[bold cyan]{module_name}[/bold cyan]")
        for e in sorted(evaluations, key=lambda x: STATUS_PRIORITY[x.status]):
            color, icon = STATUS_STYLE[e.status]
            label = f"[{color}]{icon} {e.legal_citation} - {e.description}[/{color}]"
            leaf = module_branch.add(label)
            note = _format_value_note(e, onto)
            if note:
                leaf.add(f"[dim]{note}[/dim]")
    console.print(tree)
    console.print()


def _format_value_note(e, onto: OntologyLoader) -> str | None:
    """Formats computed_value/threshold_value using the threshold's OWN
    unit (INR / PERCENT / DAYS / YEARS / MONTHS) so a percentage rate
    isn't misleadingly rendered as if it were a rupee amount being
    compared against another rupee amount."""
    if e.computed_value is None:
        return None
    if e.threshold_id:
        try:
            unit = onto.get_threshold(e.threshold_id).unit
        except KeyError:
            unit = "INR"
        if unit == "PERCENT":
            return f"Rs {e.computed_value:,.2f} (at {e.threshold_value:.0f}% rate)"
        if unit in ("YEARS", "MONTHS"):
            return f"Rs {e.computed_value:,.2f} claim amount"
        # INR-vs-INR or unitless day-counts: the original direct comparison is meaningful
    if e.threshold_value is not None:
        return f"{e.computed_value:,.2f} vs threshold {e.threshold_value:,.2f}"
    return f"{e.computed_value:,.2f}"


def render_violations_detail(proof: ProofObject) -> None:
    violations = proof.violations()
    if not violations:
        console.print("[green]No violations found.[/green]\n")
        return
    console.print(Panel.fit("[bold red]Action Required[/bold red]", border_style="red"))
    for e in violations:
        console.print(f"[bold]{e.legal_citation}[/bold]  [dim]({e.rule_id})[/dim]")
        console.print(f"  {e.explanation_hint}\n")


def render_explanation(explanation: str) -> None:
    console.print(Panel.fit("[bold]Layer 3 Explanation[/bold]", border_style="blue"))
    console.print(Markdown(explanation))


def run_and_render(profile: BusinessProfile, onto: OntologyLoader, as_of: date) -> None:
    try:
        proof, explanation = generate_explanation(profile, onto, as_of_date=as_of,
                                                    explainer=Layer3Explainer())
    except ValueError as exc:
        console.print(f"[bold red]Profile validation failed:[/bold red] {exc}")
        sys.exit(1)

    render_summary(proof)
    render_proof_chain(proof, onto)
    render_violations_detail(proof)
    render_explanation(explanation)


# ------------------------------------------------------------------------
#  Interactive profile builder
# ------------------------------------------------------------------------

def prompt_str(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or (default or "")


def prompt_yes_no(label: str, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input(f"{label} ({suffix}): ").strip().lower()
    if not value:
        return default
    return value.startswith("y")


def build_profile_interactively(onto: OntologyLoader) -> BusinessProfile:
    console.print("[bold]AuditSure - Interactive Business Profile Builder[/bold]\n")

    name = prompt_str("Business name")
    console.print(f"[dim]Valid states include: {', '.join(onto.get_state_names()[:6])}, ...[/dim]")
    state = prompt_str("State (ontology id, e.g. Karnataka)")
    turnover = Decimal(prompt_str("Aggregate turnover for the FY (Rs)", "0"))
    fy = prompt_str("Financial year", "2025-26")

    console.print(f"[dim]Valid business types: {', '.join(onto.get_business_type_names())}[/dim]")
    business_type = prompt_str("Primary business type", "Trader")

    registered = prompt_yes_no("Currently GST registered?", default=False)
    registration_status = RegistrationStatus.ACTIVE if registered else RegistrationStatus.NOT_REGISTERED

    opts_composition = prompt_yes_no("Opting for the composition levy?", default=False)
    interstate = prompt_yes_no("Makes inter-State outward supply?", default=False)

    return BusinessProfile(
        name=name, state=state, aggregate_turnover=turnover, financial_year=fy,
        business_types=[business_type], registration_status=registration_status,
        opts_for_composition=opts_composition, makes_interstate_outward_supply=interstate,
    )


# ------------------------------------------------------------------------
#  Entry point
# ------------------------------------------------------------------------

def list_demo_personas() -> list[str]:
    return sorted(p.stem for p in EXAMPLES_DIR.glob("*.json"))


def main():
    parser = argparse.ArgumentParser(description="AuditSure GST compliance check - demo CLI (Phase 9)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--demo", metavar="NAME", help=f"run a built-in example persona: {', '.join(list_demo_personas())}")
    group.add_argument("--profile", metavar="PATH", help="run a business profile from a JSON file")
    group.add_argument("--interactive", action="store_true", help="build a profile via guided prompts")
    group.add_argument("--list-demos", action="store_true", help="list available demo personas and exit")
    parser.add_argument("--as-of", metavar="YYYY-MM-DD", help="evaluation date (default: today)")
    args = parser.parse_args()

    if args.list_demos:
        for name in list_demo_personas():
            console.print(f"  - {name}")
        return

    onto = get_default_loader()
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()

    if args.demo:
        path = EXAMPLES_DIR / f"{args.demo}.json"
        if not path.exists():
            console.print(f"[bold red]No such demo persona:[/bold red] {args.demo}")
            console.print(f"Available: {', '.join(list_demo_personas())}")
            sys.exit(1)
        profile = _load_profile_or_exit(str(path))
    elif args.profile:
        profile = _load_profile_or_exit(args.profile)
    elif args.interactive:
        profile = build_profile_interactively(onto)
    else:
        parser.print_help()
        return

    run_and_render(profile, onto, as_of)


def _load_profile_or_exit(path: str) -> BusinessProfile:
    try:
        return load_profile_from_json(path)
    except (ProfileLoadError, FileNotFoundError, ValueError) as exc:
        console.print(f"[bold red]Could not load profile from {path}:[/bold red] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
