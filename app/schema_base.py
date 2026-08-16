"""Base schémas — normalisation des champs vides."""
from __future__ import annotations

from typing import Annotated, Union, get_args, get_origin

from pydantic import BaseModel, model_validator


def _unwrap_annotation(annotation):
    origin = get_origin(annotation)
    if origin is Annotated:
        return get_args(annotation)[0]
    return annotation


def _annotation_allows_none(annotation) -> bool:
    ann = _unwrap_annotation(annotation)
    if ann is type(None):
        return True
    origin = get_origin(ann)
    if origin is Union:
        return type(None) in get_args(ann)
    return False


class PeyaSchema(BaseModel):
    """Normalise les champs vides selon le type déclaré."""

    @model_validator(mode="before")
    @classmethod
    def normalize_empty_fields(cls, data):
        if not isinstance(data, dict):
            return data
        out = dict(data)
        fields = getattr(cls, "model_fields", {})
        for key, val in list(out.items()):
            field = fields.get(key)
            if field is None:
                continue
            ann = field.annotation
            if _annotation_allows_none(ann):
                if val == "" or val is None:
                    out[key] = None
            elif _unwrap_annotation(ann) is str and val is None:
                out[key] = ""
        return out
