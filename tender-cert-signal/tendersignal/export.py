"""Lead export: CSV for hand-off, and the same rows as dicts for the Google Sheet sync."""

import csv
import json
import sqlite3
from typing import Dict, List

# Column order is shared by the CSV and the Google Sheet. `global_id` is the stable row key the
# sheet uses to tell "new lead" from "update to a lead already in the sheet".
FIELDNAMES = [
    "global_id", "supplier_name", "supplier_canonical_name", "supplier_abn",
    "supplier_locality", "supplier_region", "supplier_entity_type_name",
    "relevant_standards", "source", "agency_name", "value_amount", "description",
    "date_signed", "period_end_date", "match_score", "first_seen", "tender_url",
]


def lead_dicts(rows: List[sqlite3.Row]) -> List[Dict[str, object]]:
    out = []
    for row in rows:
        d = dict(row)
        if d.get("relevant_standards"):
            d["relevant_standards"] = ", ".join(json.loads(d["relevant_standards"]))
        out.append({k: ("" if d.get(k) is None else d.get(k)) for k in FIELDNAMES})
    return out


def write_leads_csv(rows: List[sqlite3.Row], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(lead_dicts(rows))
