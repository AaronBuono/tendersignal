"""Tests for the multi-source schema: migrating an old single-source DB, upsert/amendment
semantics, and the renewal-window query.
"""

import sqlite3

from tendersignal import db
from tendersignal.sources.base import ContractRecord

OLD_SCHEMA = """
CREATE TABLE contracts (
    contract_id TEXT PRIMARY KEY,
    ocid TEXT,
    supplier_name TEXT NOT NULL,
    supplier_abn TEXT,
    supplier_locality TEXT,
    supplier_region TEXT,
    agency_name TEXT,
    value_amount REAL,
    value_currency TEXT,
    unspsc_code TEXT,
    description TEXT,
    date_signed TEXT,
    first_seen TEXT NOT NULL,
    match_status TEXT NOT NULL DEFAULT 'pending',
    match_score REAL,
    match_org_name TEXT,
    match_cab_name TEXT,
    match_error TEXT,
    relevant_standards TEXT,
    notified INTEGER NOT NULL DEFAULT 0,
    recheck_after TEXT
);
"""


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def test_migration_backfills_global_id_on_a_pre_multi_source_db():
    conn = make_conn()
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO contracts (contract_id, supplier_name, first_seen, match_status) "
        "VALUES ('CN999', 'Legacy Pty Ltd', '2026-01-01T00:00:00Z', 'no_match')"
    )
    conn.commit()

    db.init_schema(conn)  # must not error, and must not drop the existing row

    row = conn.execute("SELECT * FROM contracts WHERE contract_id = 'CN999'").fetchone()
    assert row["global_id"] == "austender:CN999"
    assert row["source"] == "austender"
    assert row["last_seen"] == row["first_seen"]
    assert row["amendment_count"] == 0

    # Running it again must be a no-op, not a second backfill/error.
    db.init_schema(conn)
    assert conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] == 1


def test_upsert_contract_inserts_then_amends_in_place():
    conn = make_conn()
    db.init_schema(conn)

    rec = ContractRecord(
        contract_id="CN1", ocid="o", supplier_name="Acme Pty Ltd", supplier_abn="123",
        supplier_locality="Perth", supplier_region="WA", agency_name="An Agency",
        value_amount=1000.0, value_currency="AUD", unspsc_code="72140000",
        description="Original scope", date_signed="2026-01-01", status="active",
        source="austender",
    )
    is_new = db.upsert_contract(conn, rec)
    assert is_new is True

    amended = ContractRecord(
        contract_id="CN1", ocid="o", supplier_name="Acme Pty Ltd", supplier_abn="123",
        supplier_locality="Perth", supplier_region="WA", agency_name="An Agency",
        value_amount=1500.0, value_currency="AUD", unspsc_code="72140000",
        description="Amended scope", date_signed="2026-01-01", status="active",
        source="austender",
    )
    is_new_again = db.upsert_contract(conn, amended)
    assert is_new_again is False

    row = conn.execute("SELECT * FROM contracts WHERE global_id = 'austender:CN1'").fetchone()
    assert row["value_amount"] == 1500.0
    assert row["description"] == "Amended scope"
    assert row["amendment_count"] == 1
    assert conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] == 1  # not duplicated


def test_different_sources_with_the_same_raw_contract_id_do_not_collide():
    conn = make_conn()
    db.init_schema(conn)

    a = ContractRecord(
        contract_id="C1", ocid=None, supplier_name="A Pty Ltd", supplier_abn=None,
        supplier_locality=None, supplier_region=None, agency_name=None, value_amount=None,
        value_currency=None, unspsc_code=None, description=None, date_signed=None, status=None,
        source="austender",
    )
    b = ContractRecord(
        contract_id="C1", ocid=None, supplier_name="B Pty Ltd", supplier_abn=None,
        supplier_locality=None, supplier_region=None, agency_name=None, value_amount=None,
        value_currency=None, unspsc_code=None, description=None, date_signed=None, status=None,
        source="nsw_etendering",
    )
    assert db.upsert_contract(conn, a) is True
    assert db.upsert_contract(conn, b) is True
    assert conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] == 2


def test_get_contracts_nearing_renewal(monkeypatch):
    import datetime as dt

    conn = make_conn()
    db.init_schema(conn)

    soon = (dt.date.today() + dt.timedelta(days=10)).isoformat()
    far = (dt.date.today() + dt.timedelta(days=400)).isoformat()

    db.upsert_contract(conn, ContractRecord(
        contract_id="SOON", ocid=None, supplier_name="Soon Pty Ltd", supplier_abn=None,
        supplier_locality=None, supplier_region=None, agency_name=None, value_amount=None,
        value_currency=None, unspsc_code=None, description=None, date_signed=None, status=None,
        period_end_date=soon,
    ))
    db.upsert_contract(conn, ContractRecord(
        contract_id="FAR", ocid=None, supplier_name="Far Pty Ltd", supplier_abn=None,
        supplier_locality=None, supplier_region=None, agency_name=None, value_amount=None,
        value_currency=None, unspsc_code=None, description=None, date_signed=None, status=None,
        period_end_date=far,
    ))

    rows = db.get_contracts_nearing_renewal(conn, within_days=60)
    assert [r["contract_id"] for r in rows] == ["SOON"]
