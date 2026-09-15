"""
GET /api/ontology
GET /api/ontology/thresholds
GET /api/ontology/sections
=================================
Everything here is read directly from OntologyLoader (Layer 1). No
value is hardcoded in the API - if the .ttl file changes, these
endpoints change with it, automatically.

get_default_loader() already gives a process-wide singleton, and every
OntologyLoader accessor used here is itself @functools.lru_cache'd, so
there is no need to build a second cache in the API layer (item 97).
"""

from __future__ import annotations

import dataclasses

from fastapi import APIRouter

from api.exceptions import OntologyError
from api.serialization import ontology_module_metadata
from app.ontology.ontology_loader import OntologyLoader, get_default_loader

router = APIRouter(prefix="/ontology", tags=["ontology"])


def _loader() -> OntologyLoader:
    try:
        return get_default_loader()
    except Exception as exc:
        raise OntologyError(f"Ontology could not be loaded: {exc}") from exc


@router.get("")
def get_ontology_metadata() -> dict:
    onto = _loader()
    return {
        "ontology_version": onto.get_version(),
        "states": [dataclasses.asdict(s) for s in onto.get_all_states()],
        "special_category_states": list(onto.get_special_category_state_names()),
        "business_types": list(onto.get_business_type_names()),
        "supply_types": list(onto.get_supply_type_names()),
        "registration_statuses": list(onto.get_registration_status_names()),
        "return_frequencies": list(onto.get_return_frequency_names()),
        "modules": ontology_module_metadata(),
        "threshold_count": len(onto.get_all_thresholds()),
        "section_count": len(onto.get_all_sections()),
    }


@router.get("/thresholds")
def get_thresholds() -> list[dict]:
    onto = _loader()
    return [dataclasses.asdict(t) for t in onto.get_all_thresholds()]


@router.get("/sections")
def get_sections() -> list[dict]:
    onto = _loader()
    return [dataclasses.asdict(s) for s in onto.get_all_sections()]
