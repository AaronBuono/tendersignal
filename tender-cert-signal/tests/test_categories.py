from tendersignal.categories import parse_standards, relevant_standards


def test_construction_segment_maps_to_quality_and_safety():
    assert relevant_standards("72140000") == ["ISO 9001", "ISO 45001"]


def test_it_segment_only_keeps_standards_kaiso_handles():
    # IT used to map to ISO 27001 too; Kaiso doesn't handle it, so only 9001 remains.
    assert relevant_standards("43230000") == ["ISO 9001"]


def test_segments_with_only_non_kaiso_standards_are_out_of_scope():
    assert relevant_standards("50000000") == []  # food -> ISO 22000 only
    assert relevant_standards("92000000") == []  # defence services -> ISO 27001 only


def test_unknown_segment_is_out_of_scope():
    assert relevant_standards("99999999") == []


def test_missing_code_is_out_of_scope():
    assert relevant_standards(None) == []
    assert relevant_standards("") == []


def test_parse_standards_keeps_only_kaiso_standards():
    assert parse_standards("ISO 9001, 14001, ISO 27001") == ["ISO 9001", "ISO 14001"]
    assert parse_standards("27001") == []
    assert parse_standards(None) == []
