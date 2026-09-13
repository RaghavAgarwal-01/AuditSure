"""
AuditSure - JSON Profile Loader
====================================
Deserializes a BusinessProfile (and its nested InvoiceRecord /
OutwardSupplyRecord / TaxPaymentRecord / RefundClaim / AppealRecord
dataclasses) from a plain JSON-compatible dict, handling the type
conversions dataclasses.asdict() can't reverse automatically: string ->
Decimal, string -> date, string -> RegistrationStatus enum, and nested
list-of-dicts -> list-of-dataclass-instances.

This is genuinely shared infrastructure, not CLI-only: a future REST
API's request body would go through the exact same loader.
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, get_args, get_origin, Union

from app.models.business_profile import (
    AppealRecord, BusinessProfile, InvoiceRecord, OutwardSupplyRecord,
    RefundClaim, RegistrationStatus, TaxPaymentRecord,
)


class ProfileLoadError(ValueError):
    """Raised with a field-path-aware message when a JSON profile is malformed."""


def _unwrap_optional(tp):
    if get_origin(tp) is Union:
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return tp


def _convert_value(value: Any, target_type: Any, path: str) -> Any:
    if value is None:
        return None
    target_type = _unwrap_optional(target_type)

    try:
        if target_type is Decimal:
            return Decimal(str(value))
        if target_type is date:
            return date.fromisoformat(value)
        if isinstance(target_type, type) and issubclass(target_type, Enum):
            return target_type(value)
        if is_dataclass(target_type):
            return _dict_to_dataclass(value, target_type, path)
    except Exception as exc:
        raise ProfileLoadError(f"{path}: could not convert {value!r} to {target_type}: {exc}") from exc

    origin = get_origin(target_type)
    if origin is list:
        (item_type,) = get_args(target_type)
        return [_convert_value(v, item_type, f"{path}[{i}]") for i, v in enumerate(value)]
    if origin is dict:
        _key_type, val_type = get_args(target_type)
        return {k: _convert_value(v, val_type, f"{path}.{k}") for k, v in value.items()}

    return value   # str, bool, int, float pass through unchanged


def _dict_to_dataclass(data: dict, cls, path: str = ""):
    if not isinstance(data, dict):
        raise ProfileLoadError(f"{path}: expected an object for {cls.__name__}, got {type(data).__name__}")

    known_fields = {f.name: f.type for f in fields(cls)}
    unknown = set(data) - set(known_fields)
    if unknown:
        raise ProfileLoadError(f"{path}: unknown field(s) for {cls.__name__}: {sorted(unknown)}")

    kwargs = {}
    for name, type_hint in known_fields.items():
        if name not in data:
            continue   # let the dataclass default apply
        kwargs[name] = _convert_value(data[name], type_hint, f"{path}.{name}" if path else name)

    return cls(**kwargs)


# Resolve string type hints (from `from __future__ import annotations` in
# business_profile.py) to actual types, so _convert_value's isinstance/
# issubclass checks work correctly.
def _resolve_types(cls):
    import typing
    hints = typing.get_type_hints(cls)
    for f in fields(cls):
        f.type = hints[f.name]


for _cls in (BusinessProfile, InvoiceRecord, OutwardSupplyRecord, TaxPaymentRecord, RefundClaim, AppealRecord):
    _resolve_types(_cls)


def load_profile_from_dict(data: dict) -> BusinessProfile:
    return _dict_to_dataclass(data, BusinessProfile)


def load_profile_from_json(path: str) -> BusinessProfile:
    with open(path) as f:
        data = json.load(f)
    return load_profile_from_dict(data)
