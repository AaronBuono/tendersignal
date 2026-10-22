"""Map a contract's UNSPSC code to the ISO standard(s) Kaiso can actually help with.

Kaiso only handles ISO 9001 (quality), ISO 14001 (environment) and ISO 45001 (health & safety).
A supplier whose work only points at some other standard (27001, 22000, 13485, ...) is not a lead
Kaiso can serve, so `relevant_standards` returns an empty list for it and the pipeline skips it
entirely (status `out_of_scope`) instead of cluttering the lead sheet.

This is still a first-pass mapping, not an authoritative one — see IDEAS.md. Segment = first two
digits of the UNSPSC code. A missing or unmapped segment is treated as out of scope, because
guessing "ISO 9001" for an unknown industry is exactly how the sheet fills up with companies
that have no real need.
"""

from typing import List, Optional

KAISO_STANDARDS = ("ISO 9001", "ISO 14001", "ISO 45001")

# segment -> (label, [Kaiso standards that are plausibly relevant])
# Segments whose only plausible standard is outside Kaiso's three were deliberately dropped:
# 10/50/90 (food safety, ISO 22000), 83/92 (information security, ISO 27001).
UNSPSC_SEGMENT_STANDARDS = {
    "11": ("Mineral and Textile and Inedible Plant and Animal Materials", ["ISO 9001"]),
    "12": ("Chemicals including Bio Chemicals and Gas Materials", ["ISO 9001", "ISO 14001"]),
    "23": ("Industrial Manufacturing and Processing Machinery and Accessories", ["ISO 9001"]),
    "25": ("Commercial and Military and Private Vehicles and Accessories", ["ISO 9001"]),
    "27": ("Tools and General Machinery", ["ISO 9001"]),
    "30": ("Structures and Building and Construction Materials", ["ISO 9001", "ISO 45001"]),
    "32": ("Electronic Components and Supplies", ["ISO 9001"]),
    "39": ("Electrical Systems and Lighting and Components and Supplies", ["ISO 9001"]),
    "40": ("Distribution and Conditioning Systems and Equipment", ["ISO 9001", "ISO 14001"]),
    "42": ("Medical Equipment and Accessories and Supplies", ["ISO 9001"]),
    "43": ("Information Technology Broadcasting and Telecommunications", ["ISO 9001"]),
    "46": ("Defense and Law Enforcement and Security and Safety Equipment", ["ISO 9001"]),
    "70": ("Farming and Fishing and Forestry and Wildlife Contracting Services", ["ISO 14001"]),
    "72": ("Building and Facility Construction and Maintenance Services", ["ISO 9001", "ISO 45001"]),
    "76": ("Industrial Cleaning Services", ["ISO 9001", "ISO 14001"]),
    "77": ("Environmental Services", ["ISO 14001"]),
    "80": ("Management and Business Professionals and Administrative Services", ["ISO 9001"]),
    "81": ("Engineering and Research and Technology Based Services", ["ISO 9001"]),
    "85": ("Healthcare Services", ["ISO 9001"]),
}


def relevant_standards(unspsc_code: Optional[str]) -> List[str]:
    """Kaiso-serviceable standards for this UNSPSC code, or [] if none (=> out of scope)."""
    if not unspsc_code or len(unspsc_code) < 2:
        return []
    entry = UNSPSC_SEGMENT_STANDARDS.get(unspsc_code[:2])
    return list(entry[1]) if entry else []


def parse_standards(text: Optional[str]) -> List[str]:
    """Normalise a free-text standards list ("9001, 14001", "ISO 45001") to Kaiso's three.

    Anything that isn't one of Kaiso's standards is dropped. Used for companies imported from a
    CSV, where there is no UNSPSC code to map from.
    """
    if not text:
        return []
    found = []
    for std in KAISO_STANDARDS:
        number = std.split()[1]
        if number in text and std not in found:
            found.append(std)
    return found
