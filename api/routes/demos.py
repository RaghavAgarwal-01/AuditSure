"""
GET /api/demos
GET /api/demos/{name}
===========================
Discovers actual files under examples/ - no persona is hardcoded here.
The listing returns lightweight presentation metadata (read as plain
JSON, not through the domain loader) so the payload stays small; the
detail endpoint returns the full canonical profile, built through the
same app.io.profile_loader used everywhere else, and rendered with
BusinessProfile.to_dict() (the domain's own canonical representation -
see item 34).

Path-traversal safety: the persona name is restricted to a strict
charset before it ever touches the filesystem, and the resolved path
is checked to still live inside EXAMPLES_DIR.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter

from api.config import EXAMPLES_DIR
from api.exceptions import DemoNotFoundError, ProfileValidationError
from api.schemas import DemoSummary
from app.io.profile_loader import ProfileLoadError, load_profile_from_json

router = APIRouter(prefix="/demos", tags=["demos"])

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _list_demo_files() -> list:
    return sorted(EXAMPLES_DIR.glob("*.json"), key=lambda p: p.stem)


def _resolve_demo_path(name: str):
    """Returns the resolved Path for `name`, or None if invalid/outside
    EXAMPLES_DIR/missing. Never raises on a malicious name - it just
    fails closed."""
    if not _NAME_PATTERN.match(name):
        return None
    examples_root = EXAMPLES_DIR.resolve()
    candidate = (EXAMPLES_DIR / f"{name}.json").resolve()
    if examples_root not in candidate.parents:
        return None
    if not candidate.is_file():
        return None
    return candidate


@router.get("", response_model=list[DemoSummary])
def list_demos() -> list[DemoSummary]:
    summaries: list[DemoSummary] = []
    for path in _list_demo_files():
        try:
            with open(path) as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue  # skip an unreadable file rather than failing the whole listing
        summaries.append(
            DemoSummary(
                id=path.stem,
                name=raw.get("name"),
                state=raw.get("state"),
                financial_year=raw.get("financial_year"),
                business_types=raw.get("business_types", []),
                aggregate_turnover=raw.get("aggregate_turnover"),
                registration_status=raw.get("registration_status"),
            )
        )
    return summaries


@router.get("/{name}")
def get_demo(name: str) -> dict:
    path = _resolve_demo_path(name)
    if path is None:
        raise DemoNotFoundError(f"No demo persona named '{name}'.")

    try:
        profile = load_profile_from_json(str(path))
    except ProfileLoadError as exc:
        # The repository's own example file failed to parse - surface it
        # as a validation error rather than a silent 500.
        raise ProfileValidationError(f"Demo '{name}' failed to load: {exc}") from exc

    return {"id": name, "profile": profile.to_dict()}
