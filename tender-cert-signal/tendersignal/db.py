"""SQLite persistence. Plain sqlite3 stdlib — no ORM, this is small enough not to need one.

One row per contract we've ever seen, from any source, carrying its match state through:
pending -> (certified | no_match | error). `sync_state` holds each source's own incremental-fetch
checkpoint (keyed per source, e.g. "checkpoint:austender") and any other single-value settings.

Rows are keyed by `global_id` (`f"{source}:{contract_id}"`), not the source's own contract_id
alone, since two different sources are free to reuse the same id shape (there's no reason NSW
eTendering and AusTender would ever agree on a numbering scheme, but nothing stops it either).
"""

import datetime as dt
import json
import sqlite3
from types import SimpleNamespace
from typing import Iterable, List, Optional

from .abn_lookup import AbnDetails
from .registries.base import CertificationRecord
from .sources.base import ContractRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS contracts (
    global_id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'austender',
    contract_id TEXT NOT NULL,
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
    tender_url TEXT,
    procurement_method TEXT,
    period_end_date TEXT,
    amendment_count INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    match_status TEXT NOT NULL DEFAULT 'pending',
    match_score REAL,
    match_org_name TEXT,
    match_cab_name TEXT,
    match_registry TEXT,
    match_error TEXT,
    relevant_standards TEXT,
    notified INTEGER NOT NULL DEFAULT 0,
    recheck_after TEXT,
    supplier_entity_type_code TEXT,
    supplier_entity_type_name TEXT,
    supplier_canonical_name TEXT,
    supplier_abn_status TEXT,
    standards_hint TEXT
);

CREATE INDEX IF NOT EXISTS idx_contracts_match_status ON contracts(match_status);
CREATE INDEX IF NOT EXISTS idx_contracts_notified ON contracts(notified);
CREATE INDEX IF NOT EXISTS idx_contracts_recheck ON contracts(recheck_after);
"""
# idx_contracts_source and idx_contracts_global_id_unique are created in _migrate_existing_table,
# not here — on a DB from before multi-source support, `source` doesn't exist as a column until
# the ALTER TABLE migration below runs, so an index on it can't be part of the initial schema.

# Columns added after the original single-source (AusTender-only) release. Each entry is applied
# with ALTER TABLE ... ADD COLUMN only if missing, so this is safe to run against the existing
# production DB as well as a brand-new one. NOT NULL + DEFAULT lets SQLite backfill existing rows
# in the same statement.
_MIGRATIONS = [
    ("source", "TEXT NOT NULL DEFAULT 'austender'"),
    ("global_id", "TEXT"),
    ("tender_url", "TEXT"),
    ("procurement_method", "TEXT"),
    ("period_end_date", "TEXT"),
    ("amendment_count", "INTEGER NOT NULL DEFAULT 0"),
    ("last_seen", "TEXT"),
    ("match_registry", "TEXT"),
    ("supplier_entity_type_code", "TEXT"),
    ("supplier_entity_type_name", "TEXT"),
    ("supplier_canonical_name", "TEXT"),
    ("supplier_abn_status", "TEXT"),
    ("standards_hint", "TEXT"),
]


def get_connection(path: Optional[str] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or "tendersignal.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate_existing_table(conn)
    conn.commit()


def _migrate_existing_table(conn: sqlite3.Connection) -> None:
    """Upgrade a DB created before multi-source support existed. No-op on a fresh DB."""
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(contracts)").fetchall()}
    for column, ddl in _MIGRATIONS:
        if column not in existing_cols:
            conn.execute(f"ALTER TABLE contracts ADD COLUMN {column} {ddl}")

    # Backfill global_id / last_seen for rows that predate those columns. contract_id was the
    # sole primary key in that era and every one of those rows is from AusTender, so this is exact
    # for all pre-existing data, not a guess.
    conn.execute(
        "UPDATE contracts SET global_id = source || ':' || contract_id WHERE global_id IS NULL"
    )
    conn.execute("UPDATE contracts SET last_seen = first_seen WHERE last_seen IS NULL")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_contracts_global_id_unique ON contracts(global_id)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_contracts_source ON contracts(source)")
    # Every row certified before multi-registry support existed was necessarily matched against
    # JAS-ANZ, since that was the only registry there was.
    conn.execute(
        "UPDATE contracts SET match_registry = 'jasanz' "
        "WHERE match_status = 'certified' AND match_registry IS NULL"
    )


# ABN Lookup entity types that are never a lead for Kaiso: individuals/sole traders (the real
# run's leads were full of named grant recipients) and government bodies. IND is confirmed from a
# real run; the three government codes are from the ABR's published code list but have not been
# seen in live data here yet.
EXCLUDED_ENTITY_TYPE_CODES = ("IND", "CGE", "SGE", "LGE")
_NOT_EXCLUDED_ENTITY = (
    "COALESCE(supplier_entity_type_code, '') NOT IN ("
    + ", ".join(f"'{c}'" for c in EXCLUDED_ENTITY_TYPE_CODES)
    + ")"
)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- sync_state -------------------------------------------------------------

def get_sync_state(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_sync_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO sync_state(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# --- contracts ---------------------------------------------------------------

def contract_exists(conn: sqlite3.Connection, global_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM contracts WHERE global_id = ?", (global_id,)).fetchone()
    return row is not None


def upsert_contract(conn: sqlite3.Connection, rec: ContractRecord) -> bool:
    """Insert a new contract, or refresh a previously-seen one's mutable fields (an amendment).

    Returns True if this was a brand-new row (should be matched against JAS-ANZ), False if it was
    an update to an existing one (match_status is left alone — this only tracks that the source
    data changed, it doesn't force a re-match; see IDEAS.md for re-matching-on-material-change as
    a further refinement).
    """
    now = _now_iso()
    if contract_exists(conn, rec.global_id):
        conn.execute(
            """UPDATE contracts SET
                 value_amount = ?, value_currency = ?, description = ?,
                 tender_url = ?, procurement_method = ?, period_end_date = ?,
                 amendment_count = amendment_count + 1, last_seen = ?
               WHERE global_id = ?""",
            (
                rec.value_amount, rec.value_currency, rec.description,
                rec.tender_url, rec.procurement_method, rec.period_end_date,
                now, rec.global_id,
            ),
        )
        return False

    conn.execute(
        """INSERT INTO contracts
           (global_id, source, contract_id, ocid, supplier_name, supplier_abn, supplier_locality,
            supplier_region, agency_name, value_amount, value_currency, unspsc_code, description,
            date_signed, tender_url, procurement_method, period_end_date, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            rec.global_id, rec.source, rec.contract_id, rec.ocid, rec.supplier_name,
            rec.supplier_abn, rec.supplier_locality, rec.supplier_region, rec.agency_name,
            rec.value_amount, rec.value_currency, rec.unspsc_code, rec.description,
            rec.date_signed, rec.tender_url, rec.procurement_method, rec.period_end_date,
            now, now,
        ),
    )
    return True


def upsert_contract_if_new(conn: sqlite3.Connection, rec: ContractRecord, standards_hint: Optional[str] = None) -> bool:
    """Stage a record only if it isn't already known (used for imported company lists, where a
    re-import must not count as an "amendment"). Returns True if a new row was added."""
    if contract_exists(conn, rec.global_id):
        return False
    upsert_contract(conn, rec)
    if standards_hint:
        conn.execute("UPDATE contracts SET standards_hint = ? WHERE global_id = ?", (standards_hint, rec.global_id))
    return True


def get_pending_contracts(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute("SELECT * FROM contracts WHERE match_status = 'pending'").fetchall()


def mark_certified(conn: sqlite3.Connection, global_id: str, match: CertificationRecord, score: float) -> None:
    conn.execute(
        """UPDATE contracts
           SET match_status = 'certified', match_score = ?, match_org_name = ?, match_cab_name = ?,
               match_registry = ?
           WHERE global_id = ?""",
        (score, match.organisation_name, match.cab_name, match.registry, global_id),
    )


def mark_no_match(
    conn: sqlite3.Connection, global_id: str, score: float, standards: List[str], recheck_after: str
) -> None:
    conn.execute(
        """UPDATE contracts
           SET match_status = 'no_match', match_score = ?, relevant_standards = ?, recheck_after = ?
           WHERE global_id = ?""",
        (score, json.dumps(standards), recheck_after, global_id),
    )


def mark_out_of_scope(conn: sqlite3.Connection, global_id: str) -> None:
    """The supplier's industry maps to no standard Kaiso handles — not a lead, never looked up."""
    conn.execute(
        "UPDATE contracts SET match_status = 'out_of_scope' WHERE global_id = ?", (global_id,)
    )


def mark_error(conn: sqlite3.Connection, global_id: str, error_message: str) -> None:
    conn.execute(
        "UPDATE contracts SET match_status = 'error', match_error = ? WHERE global_id = ?",
        (error_message[:500], global_id),
    )


def reset_errors_to_pending(conn: sqlite3.Connection) -> int:
    """So a transient failure (network blip, etc.) gets retried on the next run."""
    cur = conn.execute("UPDATE contracts SET match_status = 'pending', match_error = NULL WHERE match_status = 'error'")
    return cur.rowcount


def _row_to_lead(row: sqlite3.Row) -> SimpleNamespace:
    standards = json.loads(row["relevant_standards"]) if row["relevant_standards"] else []
    return SimpleNamespace(
        global_id=row["global_id"],
        source=row["source"],
        contract_id=row["contract_id"],
        tender_url=row["tender_url"],
        supplier_name=row["supplier_name"],
        supplier_abn=row["supplier_abn"],
        agency_name=row["agency_name"],
        value_amount=row["value_amount"],
        unspsc_code=row["unspsc_code"],
        relevant_standards=standards,
        match_score=row["match_score"],
    )


def _max_value_clause(max_value: Optional[float]) -> str:
    """SQL fragment hiding leads above `max_value` AUD (list-imported companies have no value and
    are never hidden). Applied when *reading* leads so tightening the cap also clears leads that
    were staged under an older, looser cap."""
    return f"AND (value_amount IS NULL OR value_amount <= {float(max_value)}) " if max_value else ""


def get_unnotified_leads(conn: sqlite3.Connection, max_value: Optional[float] = None) -> List[SimpleNamespace]:
    rows = conn.execute(
        "SELECT * FROM contracts WHERE match_status = 'no_match' AND notified = 0 "
        f"AND {_NOT_EXCLUDED_ENTITY} {_max_value_clause(max_value)}"
        "ORDER BY value_amount DESC NULLS LAST"
    ).fetchall()
    return [_row_to_lead(r) for r in rows]


def mark_notified(conn: sqlite3.Connection, global_ids: Iterable[str]) -> None:
    conn.executemany(
        "UPDATE contracts SET notified = 1 WHERE global_id = ?",
        [(gid,) for gid in global_ids],
    )


def get_leads_due_for_recheck(conn: sqlite3.Connection, today_iso: str) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM contracts WHERE match_status = 'no_match' AND recheck_after <= ?",
        (today_iso,),
    ).fetchall()


def get_all_leads(conn: sqlite3.Connection, max_value: Optional[float] = None) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM contracts WHERE match_status = 'no_match' "
        f"AND {_NOT_EXCLUDED_ENTITY} {_max_value_clause(max_value)}ORDER BY value_amount DESC NULLS LAST"
    ).fetchall()


def get_contracts_needing_abn_enrichment(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    """Contracts with a known ABN that haven't been through ABN Lookup enrichment yet.

    Idempotent and safe to call every run whether or not ABN_LOOKUP_GUID is configured — with no
    GUID, pipeline.run_enrich_abn short-circuits before ever calling this.
    """
    return conn.execute(
        "SELECT global_id, supplier_abn FROM contracts "
        "WHERE supplier_abn IS NOT NULL AND supplier_abn != '' "
        "AND supplier_entity_type_code IS NULL"
    ).fetchall()


def set_supplier_enrichment(conn: sqlite3.Connection, global_id: str, details: Optional[AbnDetails]) -> None:
    """Record an ABN Lookup result — or, if `details` is None (lookup failed or returned no
    usable data), an empty-string sentinel so this row isn't re-selected by
    get_contracts_needing_abn_enrichment() forever. NULL means "not attempted yet"; empty string
    means "attempted, nothing usable came back."
    """
    conn.execute(
        """UPDATE contracts SET
             supplier_entity_type_code = ?, supplier_entity_type_name = ?,
             supplier_canonical_name = ?, supplier_abn_status = ?
           WHERE global_id = ?""",
        (
            (details.entity_type_code or "") if details else "",
            (details.entity_type_name or "") if details else "",
            (details.entity_name or "") if details else "",
            (details.abn_status or "") if details else "",
            global_id,
        ),
    )


def get_contracts_nearing_renewal(conn: sqlite3.Connection, within_days: int = 60) -> List[sqlite3.Row]:
    """Contracts whose period_end_date falls within the next `within_days` — a second, later
    opportunity to reach the same supplier around their retender."""
    cutoff = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=within_days)).date().isoformat()
    today = dt.date.today().isoformat()
    return conn.execute(
        "SELECT * FROM contracts WHERE period_end_date IS NOT NULL "
        "AND period_end_date BETWEEN ? AND ? ORDER BY period_end_date ASC",
        (today, cutoff),
    ).fetchall()
