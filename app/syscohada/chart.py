"""Plan comptable SYSCOHADA révisé — liste officielle complète (classes 1 à 9)."""

from __future__ import annotations

import json
from pathlib import Path


def _class_of(code: str) -> str:
    return code[0] if code else ""


def _parent_of(code: str) -> str:
    if len(code) <= 2:
        return ""
    if len(code) == 3:
        return code[:2]
    return code[:3]


def _level_of(code: str) -> int:
    return len(code)


def _type_of(code: str) -> str:
    """Type comptable : actif, passif, charge, produit, analytique."""
    c = code[0] if code else ""
    if c == "1":
        return "passif"
    if c in ("2", "3"):
        return "actif"
    if c == "4":
        if code.startswith(("409", "419", "42", "43", "44", "45", "46", "47")):
            if code.startswith("419"):
                return "passif"
            if code.startswith("409"):
                return "actif"
            if code.startswith(("421", "422", "423", "424", "425", "426", "427", "428")):
                return "passif"
            if code.startswith(("431", "432", "433", "438")):
                return "passif"
            if code.startswith(("441", "442", "443", "444", "445", "446", "447", "448", "449")):
                return "passif"
            return "passif"
        return "actif"
    if c == "5":
        return "actif"
    if c == "6":
        return "charge"
    if c == "7":
        return "produit"
    if c == "8":
        try:
            n = int(code[:2]) if len(code) >= 2 else int(code)
            return "produit" if n % 2 == 0 else "charge"
        except ValueError:
            return "charge"
    if c == "9":
        return "analytique"
    return "charge"


def _entry(code: str, label: str, account_type: str | None = None) -> dict:
    return {
        "code": code,
        "label": label,
        "type": account_type or _type_of(code),
        "class_code": _class_of(code),
        "parent_code": _parent_of(code),
        "level": _level_of(code),
    }


def _load_official_chart() -> list[dict]:
    data_path = Path(__file__).with_name("chart_official.json")
    if not data_path.is_file():
        raise FileNotFoundError(f"Plan SYSCOHADA introuvable : {data_path}")
    raw = json.loads(data_path.read_text(encoding="utf-8"))
    out: list[dict] = []
    for row in raw:
        code = str(row["code"])
        label = row.get("label") or code
        acc_type = row.get("type") or _type_of(code)
        out.append(_entry(code, label, acc_type))
    return out


SYSCOHADA_CHART: list[dict] = _load_official_chart()


def chart_by_class() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for acc in SYSCOHADA_CHART:
        out.setdefault(acc["class_code"], []).append(acc)
    return out
