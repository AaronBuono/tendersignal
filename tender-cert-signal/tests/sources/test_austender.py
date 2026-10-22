"""Parsing tests for the AusTender OCDS client, using a trimmed real release as fixture data
(captured 2026-08-25 from https://api.tenders.gov.au/ocds/findByDates/contractPublished/...).
"""

from unittest.mock import Mock

import requests

from tendersignal.sources.austender import _parse_release, fetch_by_last_modified

RELEASE_FIXTURE = {
    "ocid": "prod-d740a630857f4e9689dfc23590348696",
    "id": "prod-d740a630857f4e9689dfc23590348696-e6a3f943817b34b4b812d94aa4420b49",
    "date": "2026-08-07T06:58:06Z",
    "parties": [
        {
            "id": "bb91a5aecfca13f0309c9f6d3c31b205",
            "name": "KAH AUSTRALIA PTY LTD T/A SYDNEY BOULEVARD",
            "additionalIdentifiers": [{"id": "51052003139", "scheme": "AU-ABN"}],
            "address": {
                "streetAddress": "90 WILLIAM STREET", "locality": "EAST SYDNEY",
                "region": "NSW", "postalCode": "2011", "countryName": "AUSTRALIA",
            },
            "roles": ["supplier"],
        },
        {
            "id": "a53d41cfab4756eb3bf206cf880ce7a1",
            "name": "Fair Work Commission",
            "roles": ["procuringEntity"],
            "additionalIdentifiers": [{"id": "93614579199", "scheme": "AU-ABN"}],
            "address": {},
            "contactPoint": {"email": "tenders@finance.gov.au"},
        },
    ],
    "awards": [
        {
            "id": "CN4267652-09ce2a5c80e04b6bb278fb4e7014a90e",
            "suppliers": [{"id": "bb91a5aecfca13f0309c9f6d3c31b205", "name": "KAH AUSTRALIA PTY LTD T/A SYDNEY BOULEVARD"}],
            "status": "active",
            "date": "2026-08-07T06:58:06Z",
        }
    ],
    "contracts": [
        {
            "id": "CN4267652",
            "awardID": "CN4267652-09ce2a5c80e04b6bb278fb4e7014a90e",
            "dateSigned": "2026-08-07T06:58:06Z",
            "description": "Stakeholder Engagement",
            "title": "CON/FWC_CON_SYS/CON001502/3",
            "items": [{"id": "90110000-x", "classification": {"scheme": "UNSPSC", "id": "90110000"}}],
            "value": {"currency": "AUD", "amount": "17238.00"},
            "status": "active",
        }
    ],
}


def test_parse_release_extracts_supplier_and_agency():
    records = _parse_release(RELEASE_FIXTURE)
    assert len(records) == 1
    rec = records[0]
    assert rec.contract_id == "CN4267652"
    assert rec.supplier_name == "KAH AUSTRALIA PTY LTD T/A SYDNEY BOULEVARD"
    assert rec.supplier_abn == "51052003139"
    assert rec.supplier_locality == "EAST SYDNEY"
    assert rec.agency_name == "Fair Work Commission"
    assert rec.value_amount == 17238.00
    assert rec.value_currency == "AUD"
    assert rec.unspsc_code == "90110000"
    assert rec.tender_url == "https://www.tenders.gov.au/cn/show/CN4267652"


def test_parse_release_skips_contract_without_supplier():
    fixture = {
        "ocid": "x", "parties": [], "awards": [],
        "contracts": [{"id": "CN0000001", "value": {}}],
    }
    assert _parse_release(fixture) == []


def test_parse_release_handles_missing_value_amount():
    fixture = dict(RELEASE_FIXTURE)
    fixture["contracts"] = [dict(RELEASE_FIXTURE["contracts"][0], value={})]
    records = _parse_release(fixture)
    assert records[0].value_amount is None


def test_fetch_treats_400_no_records_as_empty_list():
    # The live API returns HTTP 400 with errorCode 100 for a window with zero results — this is
    # an expected, frequent case (e.g. a quiet overnight window), not a real failure.
    fake_response = Mock(status_code=400)
    fake_response.json.return_value = {"errorCode": 100, "message": "No Records found for Date Range [...]"}
    fake_session = Mock()
    fake_session.get.return_value = fake_response

    records = fetch_by_last_modified("2026-08-25T00:00:00Z", "2026-08-25T01:00:00Z", session=fake_session)
    assert records == []
    fake_response.raise_for_status.assert_not_called()


def _mock_response(status_code=200, json_body=None):
    resp = Mock(status_code=status_code)
    resp.json.return_value = json_body or {}
    return resp


def test_fetch_follows_pagination_across_pages():
    page1 = _mock_response(json_body={
        "releases": [dict(RELEASE_FIXTURE, date="2026-08-24T20:00:00Z")],
        "links": {"next": "https://api.tenders.gov.au/ocds/findByDates/contractLastModified/x?cursor=1"},
    })
    page2 = _mock_response(json_body={
        "releases": [dict(RELEASE_FIXTURE, date="2026-08-24T10:00:00Z")],
        "links": {},
    })
    fake_session = Mock()
    fake_session.get.side_effect = [page1, page2]

    records = fetch_by_last_modified(
        "2026-08-24T00:00:00Z", "2026-08-25T00:00:00Z", session=fake_session
    )
    assert len(records) == 2
    assert fake_session.get.call_count == 2


def test_fetch_drops_releases_outside_the_requested_window():
    # Simulates the observed real-world behaviour: past page 1, the cursor can return releases
    # dated well outside [start, end). Those must be filtered out, not silently ingested.
    page1 = _mock_response(json_body={
        "releases": [dict(RELEASE_FIXTURE, date="2026-08-24T20:00:00Z")],
        "links": {"next": "https://api.tenders.gov.au/ocds/findByDates/contractLastModified/x?cursor=1"},
    })
    page2_drifted = _mock_response(json_body={
        "releases": [dict(RELEASE_FIXTURE, date="2026-04-29T06:44:01Z", ocid="stale-ocid")],
        "links": {"next": "https://api.tenders.gov.au/ocds/findByDates/contractLastModified/x?cursor=2"},
    })
    fake_session = Mock()
    fake_session.get.side_effect = [page1, page2_drifted]

    records = fetch_by_last_modified(
        "2026-08-24T00:00:00Z", "2026-08-25T00:00:00Z", session=fake_session
    )
    # Only the in-window release survives; pagination stops once a page is entirely out-of-window.
    assert len(records) == 1
    assert records[0].ocid != "stale-ocid"
    assert fake_session.get.call_count == 2


def test_fetch_stops_at_max_pages_and_warns(caplog):
    same_page = _mock_response(json_body={
        "releases": [dict(RELEASE_FIXTURE, date="2026-08-24T20:00:00Z", ocid=f"ocid-{i}") for i in range(1)],
        "links": {"next": "https://api.tenders.gov.au/ocds/findByDates/contractLastModified/x?cursor=loop"},
    })
    # Every page returns a *different* next cursor so the loop-detection guard doesn't kick in,
    # forcing the max_pages backstop to be what actually stops it.
    responses = []
    for i in range(5):
        responses.append(_mock_response(json_body={
            "releases": [dict(RELEASE_FIXTURE, date="2026-08-24T20:00:00Z", ocid=f"ocid-{i}")],
            "links": {"next": f"https://api.tenders.gov.au/ocds/findByDates/contractLastModified/x?cursor={i}"},
        }))
    fake_session = Mock()
    fake_session.get.side_effect = responses

    records = fetch_by_last_modified(
        "2026-08-24T00:00:00Z", "2026-08-25T00:00:00Z", session=fake_session, max_pages=3
    )
    assert fake_session.get.call_count == 3
    assert len(records) == 3
    assert any("Hit max_pages" in r.message for r in caplog.records)


def test_fetch_retries_past_transient_connection_errors(monkeypatch):
    # Mirrors what happened in production: cron fires before the container's network/DNS is up,
    # the first attempt(s) fail with a ConnectionError, then a later attempt succeeds.
    monkeypatch.setattr("time.sleep", lambda seconds: None)  # don't actually wait in tests

    ok_response = _mock_response(json_body={
        "releases": [dict(RELEASE_FIXTURE, date="2026-08-24T20:00:00Z")], "links": {},
    })
    fake_session = Mock()
    fake_session.get.side_effect = [
        requests.exceptions.ConnectionError("DNS not ready"),
        requests.exceptions.ConnectionError("DNS not ready"),
        ok_response,
    ]

    records = fetch_by_last_modified(
        "2026-08-24T00:00:00Z", "2026-08-25T00:00:00Z", session=fake_session
    )
    assert len(records) == 1
    assert fake_session.get.call_count == 3


def test_fetch_raises_after_exhausting_connection_retries(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    fake_session = Mock()
    fake_session.get.side_effect = requests.exceptions.ConnectionError("still down")

    try:
        fetch_by_last_modified("2026-08-24T00:00:00Z", "2026-08-25T00:00:00Z", session=fake_session)
        assert False, "expected ConnectionError to propagate after retries are exhausted"
    except requests.exceptions.ConnectionError:
        pass
    assert fake_session.get.call_count == 4  # _MAX_CONNECT_RETRIES


def test_fetch_still_raises_on_other_400s():
    fake_response = Mock(status_code=400)
    fake_response.json.return_value = {"errorCode": 999, "message": "Something else went wrong"}
    fake_response.raise_for_status.side_effect = Exception("boom")
    fake_session = Mock()
    fake_session.get.return_value = fake_response

    try:
        fetch_by_last_modified("2026-08-25T00:00:00Z", "2026-08-25T01:00:00Z", session=fake_session)
        assert False, "expected an exception"
    except Exception as exc:
        assert str(exc) == "boom"
