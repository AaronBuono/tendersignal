"""Tests for the ABN Lookup client.

The GUID-rejected response (real_error_response below) was genuinely captured live from
https://abr.business.gov.au/json/AbnDetails.aspx on 2026-09-12 — it confirms the JSONP wrapper,
every field key, and the failure-message behaviour. A real *success* response needs a registered
GUID this project doesn't have, so the "success" fixtures below use those same confirmed keys with
constructed (not captured) example values — see the module docstring in abn_lookup.py for that
distinction.
"""

from unittest.mock import Mock

from tendersignal.abn_lookup import AbnLookupClient, _parse_abn_details, _strip_jsonp

REAL_ERROR_RESPONSE_TEXT = (
    'callback({"Abn":"","AbnStatus":"","AbnStatusEffectiveFrom":"","Acn":"","AddressDate":null,'
    '"AddressPostcode":"","AddressState":"","BusinessName":[],"EntityName":"","EntityTypeCode":"",'
    '"EntityTypeName":"","Gst":null,"Message":"The GUID entered is not recognised as a Registered Party"}'
    ')'
)

# Constructed (not captured) — real field names, illustrative values.
CONSTRUCTED_SUCCESS_PAYLOAD = {
    "Abn": "51824753556",
    "AbnStatus": "Active",
    "AbnStatusEffectiveFrom": "2010-01-01",
    "Acn": "824753556",
    "AddressDate": "2020-01-01",
    "AddressPostcode": "2000",
    "AddressState": "NSW",
    "BusinessName": ["Example Trading Co"],
    "EntityName": "EXAMPLE PTY LTD",
    "EntityTypeCode": "PRV",
    "EntityTypeName": "Australian Private Company",
    "Gst": True,
    "Message": "",
}


def test_strip_jsonp_handles_the_real_wrapper():
    parsed = _strip_jsonp(REAL_ERROR_RESPONSE_TEXT)
    assert parsed["Message"] == "The GUID entered is not recognised as a Registered Party"
    assert parsed["Abn"] == ""


def test_strip_jsonp_handles_plain_json_without_wrapper():
    assert _strip_jsonp('{"Abn": "123"}') == {"Abn": "123"}


def test_parse_abn_details_returns_none_on_message():
    parsed = _strip_jsonp(REAL_ERROR_RESPONSE_TEXT)
    assert _parse_abn_details(parsed) is None


def test_parse_abn_details_extracts_real_fields():
    details = _parse_abn_details(CONSTRUCTED_SUCCESS_PAYLOAD)
    assert details is not None
    assert details.entity_name == "EXAMPLE PTY LTD"
    assert details.entity_type_code == "PRV"
    assert details.abn_status == "Active"
    assert details.trading_names == ["Example Trading Co"]
    assert details.gst_registered is True


def test_parse_abn_details_handles_object_shaped_business_names():
    payload = dict(CONSTRUCTED_SUCCESS_PAYLOAD, BusinessName=[{"OrganisationName": "Other Trading Name"}])
    details = _parse_abn_details(payload)
    assert details.trading_names == ["Other Trading Name"]


def test_client_disabled_without_a_guid():
    client = AbnLookupClient(guid=None)
    assert client.enabled is False
    assert client.lookup_by_abn("51824753556") is None


def test_client_rejects_malformed_abn_without_a_network_call():
    client = AbnLookupClient(guid="fake-guid")
    fake_session = Mock()
    client.session = fake_session
    assert client.lookup_by_abn("not-an-abn") is None
    fake_session.get.assert_not_called()


def test_client_lookup_by_abn_end_to_end_with_mocked_session():
    fake_response = Mock(status_code=200)
    fake_response.text = 'callback(' + __import__("json").dumps(CONSTRUCTED_SUCCESS_PAYLOAD) + ')'
    fake_session = Mock()
    fake_session.get.return_value = fake_response

    client = AbnLookupClient(guid="fake-guid", session=fake_session, rate_limit_seconds=0)
    details = client.lookup_by_abn("51 824 753 556")  # spaced, like a human would type it
    assert details.entity_name == "EXAMPLE PTY LTD"
    called_params = fake_session.get.call_args.kwargs["params"]
    assert called_params["abn"] == "51824753556"  # spaces stripped before the request
