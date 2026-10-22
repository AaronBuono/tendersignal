"""Import a list of companies (CSV) straight into the same match pipeline as tender suppliers.

This is the "company-first" route: instead of waiting for a company to win a government contract,
start from any list of small businesses in trades Kaiso serves — an industry-association member
list, a licence register export, a hand-built prospect list — and let the pipeline check each one
against the certification registries. Anything with no active cert becomes a lead, same as before.

Recognised CSV columns (case-insensitive, extra columns ignored; only a name is required):
    name / company / company name / supplier_name / business name
    abn
    state / region
    city / suburb / locality
    standards / standard     e.g. "9001, 14001" — what this company might need (else --standards)
    industry / category      free text, kept as the lead's description
"""

import csv
import re
from typing import Dict, List, Optional

from . import categories, db
from .sources.base import ContractRecord

_NAME_KEYS = ("name", "company", "company name", "supplier_name", "supplier name", "business name",
              "business_name", "company_name")


def _pick(row: Dict[str, str], *keys: str) -> Optional[str]:
    for key in keys:
        value = row.get(key)
        if value and value.strip():
            return value.strip()
    return None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def import_companies(conn, path: str, label: str, default_standards: Optional[str] = None) -> Dict[str, int]:
    """Stage every company in the CSV as a pending lead. Returns counts: added / skipped / invalid.

    Re-importing the same file is safe: companies already staged (matched by ABN, else by name)
    are skipped, not duplicated.
    """
    source = f"list:{_slug(label)}"
    default_hint = ", ".join(categories.parse_standards(default_standards)) or None
    counts = {"added": 0, "skipped": 0, "invalid": 0}

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row = {(k or "").strip().lower(): v for k, v in raw.items()}
            name = _pick(row, *_NAME_KEYS)
            if not name:
                counts["invalid"] += 1
                continue

            abn_digits = re.sub(r"\D", "", _pick(row, "abn") or "")
            abn = abn_digits if len(abn_digits) == 11 else None
            hint_text = _pick(row, "standards", "standard")
            hint = ", ".join(categories.parse_standards(hint_text)) if hint_text else default_hint
            if not hint:
                # No Kaiso standard for this company -> it can never be a lead, don't stage it.
                counts["invalid"] += 1
                continue

            rec = ContractRecord(
                contract_id=abn or _slug(name),
                ocid=None,
                supplier_name=name,
                supplier_abn=abn,
                supplier_locality=_pick(row, "city", "suburb", "locality"),
                supplier_region=_pick(row, "state", "region"),
                agency_name=label,
                value_amount=None,
                value_currency=None,
                unspsc_code=None,
                description=_pick(row, "industry", "category"),
                date_signed=None,
                status=None,
                source=source,
            )
            if not db.upsert_contract_if_new(conn, rec, standards_hint=hint):
                counts["skipped"] += 1
            else:
                counts["added"] += 1

    conn.commit()
    return counts
