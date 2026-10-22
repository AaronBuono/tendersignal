"""Orchestrates one end-to-end cycle: ingest new awards -> match against certification registries -> notify.

Designed to be safe to run repeatedly (e.g. from cron): each source's ingestion is checkpointed
in sync_state independently, and contracts already in the DB are updated in place (see
db.upsert_contract) rather than re-inserted or re-notified.
"""

import datetime as dt
import logging
import sqlite3
from typing import Optional

from . import categories, config, db, notify
from .abn_lookup import AbnLookupClient
from .matching import best_match
from .registries import ALL_REGISTRIES
from .registries.matcher import CertificationMatcher
from .sources import ALL_SOURCES
from .sources.base import TenderSource

logger = logging.getLogger(__name__)

# Keys of sources whose fetch failed during the most recent run_ingest(), so the CLI can say so
# plainly instead of leaving a non-technical user to read "0 new leads" as "nothing happened".
last_ingest_failures: list = []


def _iso(d: dt.datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _checkpoint_key(source: TenderSource) -> str:
    return f"last_modified_checkpoint:{source.key}"


def run_ingest_one(conn: sqlite3.Connection, source: TenderSource) -> int:
    """Pull new/changed contracts from a single source since its own last checkpoint.

    Returns the count of brand-new contracts staged (amendments to already-seen ones are applied
    in place and don't count here — see db.upsert_contract).
    """
    now = dt.datetime.now(dt.timezone.utc)
    checkpoint = db.get_sync_state(conn, _checkpoint_key(source))
    if checkpoint:
        start = dt.datetime.strptime(checkpoint, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    else:
        start = now - dt.timedelta(days=config.LOOKBACK_DAYS)

    start_iso, end_iso = _iso(start), _iso(now)
    logger.info("[%s] fetching contracts modified %s .. %s", source.key, start_iso, end_iso)
    try:
        records = source.fetch(start_iso, end_iso)
    except Exception as exc:  # noqa: BLE001 - one source being down shouldn't skip the others,
        # or skip matching/notify for anything already staged. The checkpoint is left untouched
        # so this source's window is simply retried in full next run.
        logger.error("[%s] fetch failed, skipping ingest for this run: %s", source.key, exc)
        last_ingest_failures.append(source.key)
        return 0
    logger.info("[%s] fetched %d contract record(s)", source.key, len(records))

    staged = 0
    for rec in records:
        if not rec.contract_id or not rec.supplier_name:
            continue
        if config.MIN_CONTRACT_VALUE and (rec.value_amount or 0) < config.MIN_CONTRACT_VALUE:
            continue
        if config.MAX_CONTRACT_VALUE and (rec.value_amount or 0) > config.MAX_CONTRACT_VALUE:
            continue  # too big to be the small business Kaiso is after
        rec.source = source.key  # authoritative regardless of what the adapter set
        if db.upsert_contract(conn, rec):
            staged += 1

    db.set_sync_state(conn, _checkpoint_key(source), end_iso)
    conn.commit()
    logger.info("[%s] %d new contract(s) staged for registry matching", source.key, staged)
    return staged


def run_ingest(conn: sqlite3.Connection) -> int:
    """Run ingestion for every registered source. One source failing doesn't stop the rest."""
    total = 0
    last_ingest_failures.clear()
    for source in ALL_SOURCES:
        total += run_ingest_one(conn, source)
    return total


def run_enrich_abn(conn: sqlite3.Connection, client: Optional[AbnLookupClient] = None) -> int:
    """Enrich contracts that have a known ABN but no ABN Lookup data yet (canonical legal name,
    entity type, trading names). A no-op if ABN_LOOKUP_GUID isn't configured — see abn_lookup.py.
    """
    client = client or AbnLookupClient(guid=config.ABN_LOOKUP_GUID)
    if not client.enabled:
        return 0

    rows = db.get_contracts_needing_abn_enrichment(conn)
    if not rows:
        return 0
    logger.info("Enriching %d contract(s) via ABN Lookup", len(rows))

    enriched = 0
    for row in rows:
        try:
            details = client.lookup_by_abn(row["supplier_abn"])
        except Exception as exc:  # noqa: BLE001 - one bad ABN shouldn't kill the whole run
            logger.warning("ABN Lookup failed for %r: %s", row["supplier_abn"], exc)
            details = None
        db.set_supplier_enrichment(conn, row["global_id"], details)
        if details:
            enriched += 1

    conn.commit()
    return enriched


def _standards_for(row) -> list:
    """Kaiso standards for a staged row: an explicit hint (imported company lists) wins,
    otherwise derive from the contract's UNSPSC code."""
    hint = row["standards_hint"]
    if hint:
        return categories.parse_standards(hint)
    return categories.relevant_standards(row["unspsc_code"])


def run_matching(conn: sqlite3.Connection, client: Optional[CertificationMatcher] = None) -> int:
    """Look up every pending contract's supplier against every registered certification registry."""
    rows = db.get_pending_contracts(conn)
    if not rows:
        return 0
    logger.info("Matching %d contract(s) against %d registered registry(s)", len(rows), len(ALL_REGISTRIES))
    client = client or CertificationMatcher(ALL_REGISTRIES)

    for i, row in enumerate(rows, start=1):
        if i % 25 == 0:
            # Save as we go (a closed window or dropped connection no longer loses everything)
            # and show a running count so a long run doesn't look frozen.
            conn.commit()
            logger.info("Checked %d/%d suppliers...", i, len(rows))
            print(f"   ...checked {i}/{len(rows)}", flush=True)
        standards = _standards_for(row)
        if not standards:
            # Nothing Kaiso can help this supplier with — don't spend a registry lookup on it.
            db.mark_out_of_scope(conn, row["global_id"])
            continue
        try:
            candidates = client.search_by_name(row["supplier_name"])
            match, score = best_match(
                row["supplier_name"], row["supplier_locality"], candidates,
                threshold=config.MATCH_THRESHOLD,
            )
        except Exception as exc:  # noqa: BLE001 - a bad supplier lookup shouldn't kill the whole run
            logger.warning("Registry lookup failed for %r: %s", row["supplier_name"], exc)
            db.mark_error(conn, row["global_id"], str(exc))
            continue

        if match:
            db.mark_certified(conn, row["global_id"], match, score)
        else:
            recheck_after = (
                dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=config.RECHECK_DAYS)
            ).date().isoformat()
            db.mark_no_match(conn, row["global_id"], score, standards, recheck_after)

    conn.commit()
    return len(rows)


def run_notify(conn: sqlite3.Connection, webhook_url: Optional[str] = None) -> int:
    """Send (or print) the digest of not-yet-notified leads. Returns count notified."""
    leads = db.get_unnotified_leads(conn)
    if not leads:
        logger.info("No new leads to notify")
        return 0

    if webhook_url:
        notify.send_slack_digest(webhook_url, leads)
        logger.info("Sent digest of %d lead(s) to webhook", len(leads))
    else:
        print(notify.format_digest(leads))

    db.mark_notified(conn, [lead.global_id for lead in leads])
    conn.commit()
    return len(leads)


def run_once(conn: sqlite3.Connection, webhook_url: Optional[str] = None) -> int:
    """Ingest -> match -> notify. This is the command a daily cron job should run."""
    db.reset_errors_to_pending(conn)
    conn.commit()
    run_ingest(conn)
    run_enrich_abn(conn)
    run_matching(conn)
    return run_notify(conn, webhook_url)


def run_recheck(conn: sqlite3.Connection, client: Optional[CertificationMatcher] = None) -> int:
    """Re-test leads whose recheck_after date has passed, in case they've since been certified."""
    today_iso = dt.date.today().isoformat()
    rows = db.get_leads_due_for_recheck(conn, today_iso)
    if not rows:
        return 0
    logger.info("Re-checking %d lead(s) due for recheck", len(rows))
    client = client or CertificationMatcher(ALL_REGISTRIES)

    resolved = 0
    for row in rows:
        try:
            candidates = client.search_by_name(row["supplier_name"])
            match, score = best_match(
                row["supplier_name"], row["supplier_locality"], candidates,
                threshold=config.MATCH_THRESHOLD,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Recheck lookup failed for %r: %s", row["supplier_name"], exc)
            continue

        if match:
            db.mark_certified(conn, row["global_id"], match, score)
            resolved += 1
        else:
            standards = _standards_for(row)
            recheck_after = (
                dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=config.RECHECK_DAYS)
            ).date().isoformat()
            db.mark_no_match(conn, row["global_id"], score, standards, recheck_after)

    conn.commit()
    logger.info("Recheck done: %d resolved to certified", resolved)
    return resolved
