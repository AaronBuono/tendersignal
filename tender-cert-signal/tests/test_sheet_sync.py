import json
import sqlite3

import pytest

from tendersignal import db, export, sheet_sync


class FakeResp:
    def __init__(self, payload=None, text=None, status=200):
        self._payload, self.text, self.status = payload, text, status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError("http error")

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _rows():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_schema(conn)
    conn.execute(
        "INSERT INTO contracts (global_id, source, contract_id, supplier_name, first_seen, last_seen, "
        "match_status, relevant_standards, value_amount) VALUES "
        "('austender:CN1','austender','CN1','Builders Pty Ltd','2026-10-01','2026-10-01','no_match','[\"ISO 9001\"]',5000)"
    )
    return db.get_all_leads(conn)


def test_not_configured_is_a_noop():
    assert sheet_sync.push_leads(_rows(), None, None) is None


def test_push_sends_token_and_flattened_leads(monkeypatch):
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen.update(url=url, body=json)
        return FakeResp({"ok": True, "added": 1, "updated": 0, "total": 1})

    monkeypatch.setattr(sheet_sync.requests, "post", fake_post)
    out = sheet_sync.push_leads(_rows(), "https://script.example/exec", "secret")
    assert out["added"] == 1
    assert seen["body"]["token"] == "secret"
    lead = seen["body"]["leads"][0]
    assert lead["global_id"] == "austender:CN1" and lead["relevant_standards"] == "ISO 9001"
    assert set(lead) == set(export.FIELDNAMES)
    json.dumps(seen["body"])  # must be JSON-serialisable


def test_rejected_token_raises(monkeypatch):
    monkeypatch.setattr(sheet_sync.requests, "post", lambda *a, **k: FakeResp({"ok": False, "error": "bad token"}))
    with pytest.raises(RuntimeError, match="bad token"):
        sheet_sync.push_leads(_rows(), "u", "t")


def test_non_json_reply_raises_helpful_error(monkeypatch):
    monkeypatch.setattr(sheet_sync.requests, "post", lambda *a, **k: FakeResp(None, text="<html>"))
    with pytest.raises(RuntimeError, match="/exec"):
        sheet_sync.push_leads(_rows(), "u", "t")
