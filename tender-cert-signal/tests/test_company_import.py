"""Company-first path: a CSV list of businesses flows through the same match -> lead pipeline."""

import sqlite3

from tendersignal import company_import, db, pipeline
from tests.test_pipeline import FakeCertificationMatcher


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_schema(conn)
    return conn


def write_csv(tmp_path, text):
    p = tmp_path / "list.csv"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_import_stages_companies_and_flows_to_leads(tmp_path):
    conn = make_conn()
    path = write_csv(tmp_path, (
        "Company,ABN,State,Suburb,Standards,Industry\n"
        "Uncertified Plumbing Pty Ltd,12 345 678 901,VIC,Geelong,\"9001, 45001\",Plumbing\n"
        "Certified Co Pty Ltd,,NSW,Sydney,9001,Manufacturing\n"
        "Wrong Standard Pty Ltd,,QLD,Cairns,27001,IT\n"
        ",,,,,\n"
    ))
    counts = company_import.import_companies(conn, path, label="Vic Builders Assoc")
    assert counts == {"added": 2, "skipped": 0, "invalid": 2}

    pipeline.run_matching(conn, client=FakeCertificationMatcher())
    leads = db.get_unnotified_leads(conn)
    assert [l.supplier_name for l in leads] == ["Uncertified Plumbing Pty Ltd"]
    assert leads[0].relevant_standards == ["ISO 9001", "ISO 45001"]
    assert leads[0].source == "list:vic-builders-assoc"
    certified = conn.execute("SELECT match_status FROM contracts WHERE supplier_name LIKE 'Certified Co%'").fetchone()
    assert certified["match_status"] == "certified"


def test_reimporting_the_same_list_does_not_duplicate_or_amend(tmp_path):
    conn = make_conn()
    path = write_csv(tmp_path, "name,standards\nAcme Builders Pty Ltd,9001\n")
    assert company_import.import_companies(conn, path, "list a")["added"] == 1
    again = company_import.import_companies(conn, path, "list a")
    assert again["added"] == 0 and again["skipped"] == 1
    row = conn.execute("SELECT amendment_count FROM contracts").fetchone()
    assert row["amendment_count"] == 0


def test_default_standards_flag_applies_to_rows_without_their_own(tmp_path):
    conn = make_conn()
    path = write_csv(tmp_path, "name\nNo Standards Col Pty Ltd\n")
    assert company_import.import_companies(conn, path, "x")["invalid"] == 1
    assert company_import.import_companies(conn, path, "x", default_standards="9001,14001")["added"] == 1
