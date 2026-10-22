"""Matching tests, using real JAS-ANZ register results captured 2026-08-25 as fixture candidates.

(JAS-ANZ was the only registry when these were captured; matching.py itself is registry-agnostic
and works identically regardless of which registry a CertificationRecord came from.)
"""

from tendersignal.matching import best_match, normalise
from tendersignal.registries.base import CertificationRecord

TELSTRA_CANDIDATES = [
    CertificationRecord(
        certificate_id="c8b1dfbd", organisation_name="Telstra Group Limited", city="Melbourne",
        country="Australia", cab_name="BSI Group ANZ Pty Limited", status="Active",
        expiry_date="2026-10-13", scopes=["EMS:ISO 14001:2015"],
    ),
    CertificationRecord(
        certificate_id="52c6f91a", organisation_name="Telstra Group Limited", city="Melbourne",
        country="Australia", cab_name="BSI Group ANZ Pty Limited", status="Active",
        expiry_date="2026-12-06", scopes=["QMS:ISO 9001:2015"],
    ),
]

WOOLWORTHS_CANDIDATES = [
    CertificationRecord(
        certificate_id="2c1366a8", organisation_name="Terrywhite Chemmart Woolworths S/C Blackwood",
        city="BLACKWOOD", country="Australia", cab_name="Pharmacy Guild of Australia", status="Active",
        expiry_date="2027-09-15", scopes=["QCPP-PGA:AS 85000:2017"],
    ),
]


def test_normalise_strips_legal_suffix_and_trading_as():
    assert normalise("KAH AUSTRALIA PTY LTD T/A SYDNEY BOULEVARD") == "kah"


def test_normalise_handles_none_and_empty():
    assert normalise(None) == ""
    assert normalise("") == ""


def test_best_match_finds_confident_match():
    match, score = best_match("Telstra Group Limited", "Melbourne", TELSTRA_CANDIDATES)
    assert match is not None
    assert match.certificate_id in {"c8b1dfbd", "52c6f91a"}
    assert score >= 87


def test_best_match_rejects_unrelated_candidate():
    # "Acme Consulting" bears no resemblance to any Woolworths-branded pharmacy franchisee.
    match, score = best_match("Acme Consulting Pty Ltd", None, WOOLWORTHS_CANDIDATES)
    assert match is None
    assert score < 87


def test_best_match_with_no_candidates():
    match, score = best_match("Anyone Pty Ltd", None, [])
    assert match is None
    assert score == 0.0


def test_best_match_prefers_active_over_expired():
    candidates = [
        CertificationRecord(
            certificate_id="expired", organisation_name="Example Co Pty Ltd", city="Perth",
            country="Australia", cab_name="SomeCAB", status="Suspended", expiry_date="2020-01-01",
            scopes=["QMS:ISO 9001:2015"],
        ),
        CertificationRecord(
            certificate_id="active", organisation_name="Example Co Pty Ltd", city="Perth",
            country="Australia", cab_name="SomeCAB", status="Active", expiry_date="2027-01-01",
            scopes=["QMS:ISO 9001:2015"],
        ),
    ]
    match, score = best_match("Example Co Pty Ltd", "Perth", candidates)
    assert match.certificate_id == "active"


def test_expired_only_certificate_is_not_a_match():
    """A lapsed cert is the same gap as no cert: it must not turn the supplier into 'certified'."""
    candidates = [
        CertificationRecord(
            certificate_id="lapsed", organisation_name="Example Co Pty Ltd", city="Perth",
            country="Australia", cab_name="SomeCAB", status="Expired", expiry_date="2024-01-01",
            scopes=["QMS:ISO 9001:2015"],
        ),
    ]
    match, score = best_match("Example Co Pty Ltd", "Perth", candidates)
    assert match is None
