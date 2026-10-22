"""End-to-end pipeline test with the network fully stubbed out: fake tender-source records in,
fake JAS-ANZ responses in, assert the DB and notification digest come out right.

Sources are injected via `pipeline.ALL_SOURCES` (a FakeSource implementing TenderSource), so this
file tests the pipeline's multi-source orchestration itself, independent of any real adapter.
"""

import sqlite3
from typing import List

import requests

from tendersignal import db, pipeline
from tendersignal.registries.base import CertificationRecord
from tendersignal.sources.base import ContractRecord, TenderSource


class FakeSource(TenderSource):
    """A source whose `.fetch()` is scripted per-test, or raises if told to."""

    def __init__(self, key="fake", records=None, error=None):
        self.key = key
        self._records = records or []
        self._error = error
        self.calls = 0

    def fetch(self, start_iso: str, end_iso: str) -> List[ContractRecord]:
        self.calls += 1
        if self._error:
            raise self._error
        return self._records


class FakeCertificationMatcher:
    """Returns a match only for 'Certified Co', nothing for anyone else."""

    def search_by_name(self, organisation_name, page_size=25):
        if "certified co" in organisation_name.lower():
            return [
                CertificationRecord(
                    certificate_id="abc", organisation_name="Certified Co Pty Ltd", city=None,
                    country="Australia", cab_name="Some CAB", status="Active",
                    expiry_date="2027-01-01", scopes=["QMS:ISO 9001:2015"],
                )
            ]
        return []


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_schema(conn)
    return conn


def test_full_cycle_flags_uncertified_supplier_as_lead(monkeypatch):
    conn = make_conn()

    fake_records = [
        ContractRecord(
            contract_id="CN1", ocid="ocid1", supplier_name="Certified Co Pty Ltd",
            supplier_abn="111", supplier_locality="Sydney", supplier_region="NSW",
            agency_name="Some Agency", value_amount=50000.0, value_currency="AUD",
            unspsc_code="72140000", description="Building works", date_signed="2026-08-01",
            status="active",
        ),
        ContractRecord(
            contract_id="CN2", ocid="ocid2", supplier_name="Uncertified Builders Pty Ltd",
            supplier_abn="222", supplier_locality="Perth", supplier_region="WA",
            agency_name="Other Agency", value_amount=200000.0, value_currency="AUD",
            unspsc_code="72140000", description="Renovation", date_signed="2026-08-02",
            status="active",
        ),
    ]
    source = FakeSource(key="austender", records=fake_records)
    monkeypatch.setattr(pipeline, "ALL_SOURCES", [source])

    staged = pipeline.run_ingest(conn)
    assert staged == 2

    # Running ingest again with the same fake records must not duplicate rows, only amend them.
    staged_again = pipeline.run_ingest(conn)
    assert staged_again == 0
    amended = conn.execute("SELECT amendment_count FROM contracts WHERE contract_id = 'CN1'").fetchone()
    assert amended["amendment_count"] == 1

    pipeline.run_matching(conn, client=FakeCertificationMatcher())

    leads = db.get_unnotified_leads(conn)
    assert [lead.contract_id for lead in leads] == ["CN2"]
    assert leads[0].relevant_standards == ["ISO 9001", "ISO 45001"]

    certified_row = conn.execute("SELECT * FROM contracts WHERE contract_id = 'CN1'").fetchone()
    assert certified_row["match_status"] == "certified"

    notified_count = pipeline.run_notify(conn, webhook_url=None)
    assert notified_count == 1
    # Second call: already notified, nothing new to send.
    assert pipeline.run_notify(conn, webhook_url=None) == 0


def test_ingest_fails_soft_when_one_source_is_unreachable(monkeypatch):
    conn = make_conn()

    good = FakeSource(key="good", records=[
        ContractRecord(
            contract_id="OK1", ocid="o", supplier_name="Fine Pty Ltd", supplier_abn=None,
            supplier_locality=None, supplier_region=None, agency_name="A",
            value_amount=1000.0, value_currency="AUD", unspsc_code=None, description=None,
            date_signed=None, status="active",
        ),
    ])
    broken = FakeSource(key="broken", error=requests.exceptions.ConnectionError("network not ready"))
    monkeypatch.setattr(pipeline, "ALL_SOURCES", [broken, good])

    staged = pipeline.run_ingest(conn)
    # The broken source contributes nothing, but the good one still gets ingested.
    assert staged == 1
    assert db.get_sync_state(conn, "last_modified_checkpoint:broken") is None
    assert db.get_sync_state(conn, "last_modified_checkpoint:good") is not None


def test_min_contract_value_filter(monkeypatch):
    conn = make_conn()

    monkeypatch.setattr(pipeline.config, "MIN_CONTRACT_VALUE", 100000.0)

    fake_records = [
        ContractRecord(
            contract_id="CNSMALL", ocid="o", supplier_name="Tiny Pty Ltd", supplier_abn=None,
            supplier_locality=None, supplier_region=None, agency_name="A",
            value_amount=500.0, value_currency="AUD", unspsc_code=None, description=None,
            date_signed=None, status="active",
        ),
    ]
    monkeypatch.setattr(pipeline, "ALL_SOURCES", [FakeSource(records=fake_records)])

    staged = pipeline.run_ingest(conn)
    assert staged == 0


def test_multiple_sources_use_independent_checkpoints(monkeypatch):
    conn = make_conn()
    a = FakeSource(key="source_a", records=[])
    b = FakeSource(key="source_b", records=[])
    monkeypatch.setattr(pipeline, "ALL_SOURCES", [a, b])

    pipeline.run_ingest(conn)
    assert a.calls == 1
    assert b.calls == 1
    assert db.get_sync_state(conn, "last_modified_checkpoint:source_a") is not None
    assert db.get_sync_state(conn, "last_modified_checkpoint:source_b") is not None


def _record(contract_id, name, unspsc, value=50000.0, abn=None):
    return ContractRecord(
        contract_id=contract_id, ocid="o", supplier_name=name, supplier_abn=abn,
        supplier_locality=None, supplier_region=None, agency_name="A",
        value_amount=value, value_currency="AUD", unspsc_code=unspsc, description=None,
        date_signed=None, status="active",
    )


def test_out_of_scope_supplier_is_never_looked_up_and_never_a_lead(monkeypatch):
    conn = make_conn()
    # 50xxxxxx = food (ISO 22000 only) -> nothing Kaiso handles.
    monkeypatch.setattr(pipeline, "ALL_SOURCES", [FakeSource(records=[_record("F1", "Cafe Pty Ltd", "50000000")])])
    pipeline.run_ingest(conn)

    class ExplodingMatcher:
        def search_by_name(self, *a, **k):
            raise AssertionError("registry must not be queried for out-of-scope suppliers")

    pipeline.run_matching(conn, client=ExplodingMatcher())
    row = conn.execute("SELECT match_status FROM contracts WHERE contract_id='F1'").fetchone()
    assert row["match_status"] == "out_of_scope"
    assert db.get_unnotified_leads(conn) == []


def test_max_contract_value_filter(monkeypatch):
    conn = make_conn()
    monkeypatch.setattr(pipeline.config, "MAX_CONTRACT_VALUE", 1000000.0)
    monkeypatch.setattr(
        pipeline, "ALL_SOURCES",
        [FakeSource(records=[_record("BIG", "Huge Pty Ltd", "72140000", value=9_000_000.0)])],
    )
    assert pipeline.run_ingest(conn) == 0


def test_sole_traders_and_government_are_excluded_from_leads(monkeypatch):
    conn = make_conn()
    monkeypatch.setattr(
        pipeline, "ALL_SOURCES",
        [FakeSource(records=[
            _record("C1", "Real Builders Pty Ltd", "72140000"),
            _record("C2", "Jane Citizen", "72140000"),
        ])],
    )
    pipeline.run_ingest(conn)
    pipeline.run_matching(conn, client=FakeCertificationMatcher())
    conn.execute("UPDATE contracts SET supplier_entity_type_code='PRV' WHERE contract_id='C1'")
    conn.execute("UPDATE contracts SET supplier_entity_type_code='IND' WHERE contract_id='C2'")
    assert [l.contract_id for l in db.get_unnotified_leads(conn)] == ["C1"]
    assert [r["contract_id"] for r in db.get_all_leads(conn)] == ["C1"]


def test_failed_source_is_recorded_for_the_cli_to_report(monkeypatch):
    conn = make_conn()
    broken = FakeSource(key="broken", error=requests.exceptions.ConnectionError("down"))
    monkeypatch.setattr(pipeline, "ALL_SOURCES", [broken])
    pipeline.run_ingest(conn)
    assert pipeline.last_ingest_failures == ["broken"]
    monkeypatch.setattr(pipeline, "ALL_SOURCES", [FakeSource(key="ok")])
    pipeline.run_ingest(conn)
    assert pipeline.last_ingest_failures == []


def test_lead_reads_respect_the_value_cap_even_for_older_staged_rows(monkeypatch):
    conn = make_conn()
    monkeypatch.setattr(pipeline.config, "MAX_CONTRACT_VALUE", 0)  # simulate rows staged under the old, looser cap
    monkeypatch.setattr(
        pipeline, "ALL_SOURCES",
        [FakeSource(records=[
            _record("SMALL", "Small Builders Pty Ltd", "72140000", value=100000.0),
            _record("BIG", "Big Builders Pty Ltd", "72140000", value=1_900_000.0),
        ])],
    )
    pipeline.run_ingest(conn)
    pipeline.run_matching(conn, client=FakeCertificationMatcher())
    assert len(db.get_all_leads(conn)) == 2
    assert [r["contract_id"] for r in db.get_all_leads(conn, max_value=500000)] == ["SMALL"]
    assert [l.contract_id for l in db.get_unnotified_leads(conn, max_value=500000)] == ["SMALL"]


def test_matching_commits_progress_periodically(monkeypatch):
    conn = make_conn()
    records = [_record(f"P{i}", f"Firm {i} Pty Ltd", "72140000") for i in range(30)]
    monkeypatch.setattr(pipeline, "ALL_SOURCES", [FakeSource(records=records)])
    pipeline.run_ingest(conn)

    class StopAfter25:
        n = 0

        def search_by_name(self, name, page_size=25):
            StopAfter25.n += 1
            if StopAfter25.n == 27:
                raise KeyboardInterrupt  # simulates the user closing the window mid-run
            return []

    try:
        pipeline.run_matching(conn, client=StopAfter25())
    except KeyboardInterrupt:
        pass
    conn.rollback()  # whatever was never committed is lost, as on a real crash
    done = conn.execute("SELECT count(*) c FROM contracts WHERE match_status != 'pending'").fetchone()["c"]
    assert done >= 24
