"""Fuzzy-match a supplier name against certification-registry candidates (JAS-ANZ, and whatever
else is registered — see `registries/`).

Most registries do their own server-side partial match on organisation name, so by the time we
get here the candidate list is usually short. This module's job is just to decide whether any
candidate is *confidently* the same legal entity — legal-suffix noise ("Pty Ltd", "T/A ...") is
the main source of false negatives, so it's stripped before scoring.
"""

import re
from typing import List, Optional, Tuple

from rapidfuzz import fuzz

from .registries.base import CertificationRecord

_LEGAL_SUFFIXES = re.compile(
    r"\b("
    r"pty\.?\s*ltd\.?|proprietary\s+limited|ltd\.?|limited|"
    r"p/?l|inc\.?|incorporated|corp\.?|corporation|"
    r"holdings?|group|australia|aus"
    r")\b",
    re.IGNORECASE,
)
_TRADING_AS = re.compile(r"\b(trading\s+as|t/a)\b.*$", re.IGNORECASE)


def normalise(name: str) -> str:
    """Lowercase, strip punctuation, drop legal suffixes and any trailing "trading as" clause."""
    if not name:
        return ""
    name = _TRADING_AS.sub("", name)
    name = name.lower()
    name = re.sub(r"[^\w\s]", " ", name)
    name = _LEGAL_SUFFIXES.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def score_candidate(supplier_name: str, supplier_locality: Optional[str], candidate: CertificationRecord) -> float:
    score = fuzz.WRatio(normalise(supplier_name), normalise(candidate.organisation_name or ""))
    if supplier_locality and candidate.city and supplier_locality.strip().lower() == candidate.city.strip().lower():
        score = min(100.0, score + 5)
    return score


def best_match(
    supplier_name: str,
    supplier_locality: Optional[str],
    candidates: List[CertificationRecord],
    threshold: float = 87,
) -> Tuple[Optional[CertificationRecord], float]:
    """Return (best_candidate_or_None, score). None means no candidate cleared the threshold.

    Only Active certificates are considered (see the note below).
    """
    if not candidates:
        return None, 0.0

    # Only Active certificates count as "certified". An expired/suspended/withdrawn cert is the
    # same gap as no cert at all for outreach purposes (and a lapsed holder is arguably a better
    # lead), so it must never turn a supplier into a "certified" match.
    pool = [c for c in candidates if (c.status or "").strip().lower() == "active"]
    if not pool:
        return None, 0.0

    scored = sorted(
        ((score_candidate(supplier_name, supplier_locality, c), c) for c in pool),
        key=lambda pair: pair[0],
        reverse=True,
    )
    top_score, top_candidate = scored[0]
    if top_score >= threshold:
        return top_candidate, top_score
    return None, top_score
