"""Parsing tests for the JAS-ANZ register client, using a real response captured 2026-08-25 from
https://jasanzcupr-api.azurewebsites.net/api/V1/RegisterCertificate/GetAllFilterCertificate
(organisationName="Telstra").
"""

from tendersignal.registries.jasanz import _parse_certificates

TELSTRA_RESPONSE = {
    "data": {
        "certificateDtos": [
            {
                "certificateId": "c8b1dfbd-ccd8-ed11-a7c7-00224818a1d1",
                "expriryDate": "2026-10-13T00:00:00",
                "certificateName": "EMS 764395",
                "organisationName": "Telstra Group Limited",
                "countryName": "Australia",
                "cabName": "BSI Group ANZ Pty Limited",
                "city": "Melbourne",
                "statusValue": "937790000",
                "statusName": "Active",
                "scopes": [{"certificateId": "c8b1dfbd-ccd8-ed11-a7c7-00224818a1d1", "scopeName": "EMS:ISO 14001:2015"}],
            },
            {
                "certificateId": "52c6f91a-cdd8-ed11-a7c7-00224818ac1c",
                "expriryDate": "2026-12-06T00:00:00",
                "certificateName": "FS 764455",
                "organisationName": "Telstra Group Limited",
                "countryName": "Australia",
                "cabName": "BSI Group ANZ Pty Limited",
                "city": "Melbourne",
                "statusValue": "937790000",
                "statusName": "Active",
                "scopes": [{"certificateId": "52c6f91a-cdd8-ed11-a7c7-00224818ac1c", "scopeName": "QMS:ISO 9001:2015"}],
            },
        ],
        "count": 2,
    },
    "isSuccessful": True,
    "messageDetail": {"message_code": "5000", "message_shortcode": "JASANZ_RECORD_FOUND", "message_type": "Information", "message": "Record found."},
}

NO_RECORDS_RESPONSE = {
    "data": None,
    "isSuccessful": False,
    "messageDetail": {"message_code": "5001", "message_shortcode": "JASANZ_RECORD_NOT_FOUND", "message_type": "Information", "message": "No records found."},
}


def test_parse_certificates_extracts_real_fields():
    certs = _parse_certificates(TELSTRA_RESPONSE)
    assert len(certs) == 2
    first = certs[0]
    assert first.organisation_name == "Telstra Group Limited"
    assert first.city == "Melbourne"
    assert first.country == "Australia"
    assert first.cab_name == "BSI Group ANZ Pty Limited"
    assert first.status == "Active"
    assert first.scopes == ["EMS:ISO 14001:2015"]
    assert first.registry == "jasanz"  # default, so it reports correctly once other registries exist


def test_parse_certificates_handles_no_records_response():
    assert _parse_certificates(NO_RECORDS_RESPONSE) == []


def test_parse_certificates_handles_missing_data_key():
    assert _parse_certificates({"isSuccessful": True}) == []
