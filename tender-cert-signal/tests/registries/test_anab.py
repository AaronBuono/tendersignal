"""Parsing tests for the ANAB directory-of-accredited-organizations client, using real responses
captured 2026-09-12 from https://search.anab.org/index/searchorgs (POST, form-encoded `company`
field). No network access — see `tendersignal/registries/anab.py` for how these were captured
with plain curl.
"""

from tendersignal.registries.anab import _flatten_scopes, _parse_organisations

# Real response for company="1Source Metrology Corp" — a calibration lab, single match, Active.
ONE_SOURCE_RESPONSE = [
    {
        "address": "465 Pinebush Rd. Unit 2",
        "matches": 0,
        "name": "1Source Metrology Corp.",
        "letter_code": "",
        "city": "Cambridge",
        "state": "Ontario",
        "zip": "N1T 2J4",
        "country": "Canada",
        "contact_name": "Bill Reilly",
        "email": "bill@1sourcemetrology.com",
        "website": "www.1sourcemetrology.com",
        "phone": "905-988-0165",
        "effective_through": "05/21/2027",
        "certificate_number": "AD-2678",
        "certificate_file": None,
        "scope_file": None,
        "categories": {
            "Calibration Labs": ["Length - Dimensional Metrology", "Mass and Mass Related"],
            "Dimensional Measurement": ["3D Measurement"],
        },
        "accreditation_standard": "ISO/IEC 17025:2017",
        "accreditation_programs": "",
        "user_fields": [],
        "company": "new",
        "cert_and_scope_file": "1Source-Metrology-Corp-Cert-and-Scope-File-04-23-2026_1776972523.pdf",
        "accreditation_status": "Active",
        "satellites": [],
        "satelliteCount": 0,
        "responsible_staff": "Ronnie Dunn",
    }
]

# Real response for company="SGS" (truncated to one of the 16 real matches returned) — an
# inspection/testing entity whose accreditation is not Active, and whose "effective_through" is a
# free-text status string rather than a date. Exercises that quirk.
SGS_AXYS_RESPONSE = [
    {
        "address": "2045 Mills Road West",
        "matches": 0,
        "name": "SGS AXYS Analytical Services, Ltd.",
        "letter_code": "",
        "city": "Sidney",
        "state": "BC",
        "zip": "V8L 5X2",
        "country": "Canada",
        "contact_name": "Rhonda Stoddard",
        "email": "",
        "website": "www.axysanalytical.com",
        "phone": "260-655-5800",
        "effective_through": "VOLUNTARILY WITHDRAWN AS OF 02/22/2026 UNTIL FURTHER NOTICE",
        "certificate_number": "ADE-1861.02",
        "certificate_file": None,
        "scope_file": None,
        "categories": {"Testing Labs": ["Environmental Testing"]},
        "accreditation_standard": "ISO/IEC 17025:2017",
        "accreditation_programs": "US Department of Energy (DoE) Consolidated Audit Program (DOECAP) - Environmental Testing",
        "user_fields": [],
        "company": "new",
        "cert_and_scope_file": "SGS-AXYS-Analytical-Services-Ltd-Cert-and-Scope-File-02-22-2026_1771808992.pdf",
        "accreditation_status": "Voluntary Withdrawal",
        "satellites": [],
        "satelliteCount": 0,
        "responsible_staff": "Joseph Kieffer",
    }
]

# Real response for company="Zzzzznonexistentorgxyz123" (and, separately, for "Telstra" /
# "Boeing" — neither is an ANAB-accredited lab/inspection body, only businesses certified by an
# ANAB-accredited CB, which this directory does not cover). The live endpoint returns a bare `[]`.
NO_RESULTS_RESPONSE = []


def test_parse_organisations_extracts_real_fields():
    records = _parse_organisations(ONE_SOURCE_RESPONSE)
    assert len(records) == 1
    r = records[0]
    assert r.organisation_name == "1Source Metrology Corp."
    assert r.city == "Cambridge"
    assert r.country == "Canada"
    assert r.cab_name == "ANAB"  # ANAB is the direct accreditor for every org this endpoint lists
    assert r.status == "Active"
    assert r.expiry_date == "05/21/2027"
    assert r.certificate_id == "AD-2678"
    assert r.registry == "anab"
    assert r.scopes == [
        "ISO/IEC 17025:2017",
        "Calibration Labs: Length - Dimensional Metrology",
        "Calibration Labs: Mass and Mass Related",
        "Dimensional Measurement: 3D Measurement",
    ]


def test_parse_organisations_handles_non_date_expiry_and_status():
    records = _parse_organisations(SGS_AXYS_RESPONSE)
    assert len(records) == 1
    r = records[0]
    assert r.organisation_name == "SGS AXYS Analytical Services, Ltd."
    assert r.status == "Voluntary Withdrawal"
    # Not every "effective_through" value is a date — pass it through as-is, don't parse it.
    assert r.expiry_date == "VOLUNTARILY WITHDRAWN AS OF 02/22/2026 UNTIL FURTHER NOTICE"
    assert r.scopes == ["ISO/IEC 17025:2017", "Testing Labs: Environmental Testing"]


def test_parse_organisations_handles_empty_array_response():
    assert _parse_organisations(NO_RESULTS_RESPONSE) == []


def test_parse_organisations_handles_none_payload():
    assert _parse_organisations(None) == []


def test_parse_organisations_handles_unexpected_shape():
    # A malformed/non-list payload (e.g. an HTML error page served with a JSON content-type)
    # should fail soft rather than raise.
    assert _parse_organisations({"unexpected": "shape"}) == []


def test_flatten_scopes_skips_missing_standard_and_categories():
    assert _flatten_scopes({}) == []
    assert _flatten_scopes({"accreditation_standard": "ISO/IEC 17025:2017"}) == ["ISO/IEC 17025:2017"]
