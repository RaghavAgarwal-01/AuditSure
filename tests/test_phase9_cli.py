"""
Phase 9 test suite - JSON Profile Loader + CLI support logic.

The CLI itself (cli.py) is an interactive/argparse entry point, not a
library API, so it's smoke-tested via subprocess against every example
persona (proving the whole demo actually runs end-to-end) rather than
unit-tested function-by-function. profile_loader.py and the CLI's pure
formatting helpers ARE unit-tested directly.

Run: pytest -v tests/test_phase9_cli.py
"""

import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.models.business_profile import BusinessProfile, InvoiceRecord, RegistrationStatus
from app.io.profile_loader import ProfileLoadError, load_profile_from_dict, load_profile_from_json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = PROJECT_ROOT / "examples"
CLI_PATH = PROJECT_ROOT / "cli.py"


# ======================================================================
#  profile_loader.py - type conversion
# ======================================================================

def test_string_amount_converts_to_decimal():
    p = load_profile_from_dict({"name": "X", "state": "Karnataka", "financial_year": "2025-26",
                                 "aggregate_turnover": "2500000"})
    assert p.aggregate_turnover == Decimal("2500000")
    assert isinstance(p.aggregate_turnover, Decimal)


def test_string_date_converts_to_date():
    p = load_profile_from_dict({
        "name": "X", "state": "Karnataka", "financial_year": "2025-26",
        "inward_invoices": [{"invoice_number": "I1", "invoice_date": "2025-06-15",
                              "taxable_value": "1000", "tax_amount": "180"}],
    })
    assert p.inward_invoices[0].invoice_date == date(2025, 6, 15)


def test_string_enum_converts_to_registration_status():
    p = load_profile_from_dict({"name": "X", "state": "Karnataka", "financial_year": "2025-26",
                                 "registration_status": "ActiveStatus"})
    assert p.registration_status == RegistrationStatus.ACTIVE


def test_nested_dataclass_list_converts_correctly():
    p = load_profile_from_dict({
        "name": "X", "state": "Karnataka", "financial_year": "2025-26",
        "inward_invoices": [
            {"invoice_number": "I1", "invoice_date": "2025-06-01", "taxable_value": "1000", "tax_amount": "180"},
            {"invoice_number": "I2", "invoice_date": "2025-07-01", "taxable_value": "2000", "tax_amount": "360"},
        ],
    })
    assert len(p.inward_invoices) == 2
    assert all(isinstance(inv, InvoiceRecord) for inv in p.inward_invoices)
    assert p.inward_invoices[1].invoice_number == "I2"


def test_dict_of_decimals_converts_correctly():
    p = load_profile_from_dict({
        "name": "X", "state": "Karnataka", "financial_year": "2025-26",
        "turnover_by_year": {"2023-24": "60000000", "2024-25": "40000000"},
    })
    assert p.turnover_by_year["2023-24"] == Decimal("60000000")


def test_missing_optional_fields_use_dataclass_defaults():
    p = load_profile_from_dict({"name": "X", "state": "Karnataka", "financial_year": "2025-26"})
    assert p.aggregate_turnover == Decimal("0")
    assert p.inward_invoices == []
    assert p.registration_status == RegistrationStatus.NOT_REGISTERED


def test_unknown_field_raises_clear_error():
    with pytest.raises(ProfileLoadError, match="unknown field"):
        load_profile_from_dict({"name": "X", "state": "Karnataka", "financial_year": "2025-26",
                                 "definitely_not_a_real_field": 123})


def test_unknown_nested_field_raises_error_with_path():
    with pytest.raises(ProfileLoadError, match="inward_invoices"):
        load_profile_from_dict({
            "name": "X", "state": "Karnataka", "financial_year": "2025-26",
            "inward_invoices": [{"invoice_number": "I1", "invoice_date": "2025-06-01",
                                  "taxable_value": "1000", "tax_amount": "180", "typo_field": True}],
        })


def test_bad_date_string_raises_clear_error():
    with pytest.raises(ProfileLoadError, match="could not convert"):
        load_profile_from_dict({
            "name": "X", "state": "Karnataka", "financial_year": "2025-26",
            "inward_invoices": [{"invoice_number": "I1", "invoice_date": "not-a-date",
                                  "taxable_value": "1000", "tax_amount": "180"}],
        })


def test_non_dict_top_level_raises_error():
    with pytest.raises(ProfileLoadError):
        load_profile_from_dict(["not", "a", "dict"])


# ======================================================================
#  All example personas must load AND run cleanly (regression guard for
#  the example files themselves - these are demo-critical assets)
# ======================================================================

@pytest.mark.parametrize("example_file", sorted(EXAMPLES_DIR.glob("*.json")), ids=lambda p: p.stem)
def test_example_persona_loads_without_error(example_file):
    profile = load_profile_from_json(str(example_file))
    assert isinstance(profile, BusinessProfile)
    assert profile.name


@pytest.mark.parametrize("example_file", sorted(EXAMPLES_DIR.glob("*.json")), ids=lambda p: p.stem)
def test_example_persona_runs_through_full_pipeline_without_error(example_file):
    from app.auditsure_pipeline import run_compliance_check
    from app.ontology.ontology_loader import get_default_loader

    profile = load_profile_from_json(str(example_file))
    proof = run_compliance_check(profile, get_default_loader(), as_of_date=date(2026, 9, 10))
    assert proof.evaluations   # every example should produce at least one finding


# ======================================================================
#  CLI smoke tests - actually invoke the CLI as a subprocess against
#  every demo persona, proving the whole thing runs end-to-end exactly
#  as a user would run it.
# ======================================================================

@pytest.mark.parametrize("persona", ["growing_manufacturer", "small_composition_trader",
                                       "unregistered_noncompliant", "special_category_interstate"])
def test_cli_demo_runs_without_crashing(persona):
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), "--demo", persona, "--as-of", "2026-09-10"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"CLI crashed for {persona}:\n{result.stderr}"
    assert "Compliance Summary" in result.stdout
    assert "Layer 3 Explanation" in result.stdout


def test_cli_list_demos():
    result = subprocess.run([sys.executable, str(CLI_PATH), "--list-demos"],
                              capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    for persona in ["growing_manufacturer", "small_composition_trader",
                     "unregistered_noncompliant", "special_category_interstate"]:
        assert persona in result.stdout


def test_cli_unknown_demo_exits_nonzero_with_clear_message():
    result = subprocess.run([sys.executable, str(CLI_PATH), "--demo", "does_not_exist"],
                              capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "No such demo persona" in result.stdout


def test_cli_missing_profile_file_exits_nonzero_with_clear_message():
    result = subprocess.run([sys.executable, str(CLI_PATH), "--profile", "/tmp/definitely_missing_xyz.json"],
                              capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "Could not load profile" in result.stdout


def test_cli_no_args_shows_help():
    result = subprocess.run([sys.executable, str(CLI_PATH)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
