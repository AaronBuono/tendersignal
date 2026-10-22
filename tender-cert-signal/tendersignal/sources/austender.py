"""Client for the public AusTender OCDS API.

No API key required. Docs: https://app.swaggerhub.com/apis/austender/ocds-api/1.1
We poll `findByDates/contractLastModified` so amendments to existing contracts are picked up
too, not just brand-new ones.
"""

import datetime as dt
import logging
import time
from typing import List, Optional

import requests

from .base import ContractRecord, TenderSource

logger = logging.getLogger(__name__)

# Observed in production: cron firing at exactly 06:00:00 can race the container's network/DNS
# coming up, causing every page fetch in that run to fail with a ConnectionError. A short retry
# with backoff clears this without needing to wait for the next scheduled run (up to a day later).
_MAX_CONNECT_RETRIES = 4
_RETRY_BACKOFF_SECONDS = 3

API_BASE = "https://api.tenders.gov.au/ocds"
CN_URL_TEMPLATE = "https://www.tenders.gov.au/cn/show/{contract_id}"


def _get_with_retries(sess: requests.Session, url: str, timeout: int) -> requests.Response:
    """GET with a few retries on connection-level failures (DNS not ready, connection reset, …).

    Does not retry on a plain HTTP error response (4xx/5xx) — those are returned as-is for the
    caller to handle (e.g. the 400/errorCode-100 "no records" case), only on the request never
    completing at all.
    """
    last_exc = None
    for attempt in range(1, _MAX_CONNECT_RETRIES + 1):
        try:
            return sess.get(url, headers={"accept": "application/json"}, timeout=timeout)
        except requests.exceptions.ConnectionError as exc:
            last_exc = exc
            logger.warning(
                "AusTender connection failed (attempt %d/%d): %s", attempt, _MAX_CONNECT_RETRIES, exc
            )
            if attempt < _MAX_CONNECT_RETRIES:
                time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
    raise last_exc


def _parse_iso(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_by_last_modified(
    start_iso: str,
    end_iso: str,
    session: Optional[requests.Session] = None,
    timeout: int = 30,
    max_pages: int = 50,
) -> List[ContractRecord]:
    """Fetch every OCDS release modified in [start_iso, end_iso) and flatten it into ContractRecords.

    Dates must be ISO 8601, e.g. "2026-08-01T00:00:00Z".

    The API caps each response at 100 releases and exposes a `links.next` cursor for more — but
    that cursor is not reliably scoped to the requested window: past the first page or two it can
    start returning releases dated months away from [start_iso, end_iso). So every release is
    filtered client-side against the window regardless of which page it came from, and paging
    stops once a full page comes back with nothing left in-window (plus a hard `max_pages` cap as
    a backstop against runaway pagination).
    """
    sess = session or requests.Session()
    start_dt, end_dt = _parse_iso(start_iso), _parse_iso(end_iso)
    url = f"{API_BASE}/findByDates/contractLastModified/{start_iso}/{end_iso}"

    records: List[ContractRecord] = []
    seen_urls = set()
    page = 0

    while url and page < max_pages:
        resp = _get_with_retries(sess, url, timeout)

        if resp.status_code == 400 and _is_no_records_response(resp):
            # The API's way of saying "zero results" is a 400 with errorCode 100, not an empty
            # 200. That's an expected, frequent case for a narrow/quiet window, not a failure.
            logger.debug("No AusTender records for %s .. %s", start_iso, end_iso)
            break

        resp.raise_for_status()
        payload = resp.json()
        page += 1

        in_window = 0
        for release in payload.get("releases", []) or []:
            release_dt = _parse_iso(release.get("date"))
            if release_dt is not None and start_dt is not None and end_dt is not None:
                if not (start_dt <= release_dt < end_dt):
                    continue
            in_window += 1
            records.extend(_parse_release(release))

        next_url = (payload.get("links") or {}).get("next")
        if not next_url or next_url in seen_urls or next_url == url or in_window == 0:
            break
        seen_urls.add(url)
        url = next_url

    if page >= max_pages:
        logger.warning(
            "Hit max_pages=%d paginating %s .. %s — results may be incomplete",
            max_pages, start_iso, end_iso,
        )
    return records


def _is_no_records_response(resp: requests.Response) -> bool:
    try:
        body = resp.json()
    except ValueError:
        return False
    return body.get("errorCode") == 100


def _party_by_id(parties, party_id):
    for p in parties:
        if p.get("id") == party_id:
            return p
    return None


def _first_with_role(parties, role):
    for p in parties:
        if role in (p.get("roles") or []):
            return p
    return None


def _parse_release(release: dict) -> List[ContractRecord]:
    parties = release.get("parties", []) or []
    awards = release.get("awards", []) or []
    agency = _first_with_role(parties, "procuringEntity")
    procurement_method = (release.get("tender") or {}).get("procurementMethod")

    out: List[ContractRecord] = []
    for contract in release.get("contracts", []) or []:
        award = next((a for a in awards if a.get("id") == contract.get("awardID")), None)

        supplier_party = None
        if award and award.get("suppliers"):
            supplier_party = _party_by_id(parties, award["suppliers"][0].get("id"))
        if supplier_party is None:
            supplier_party = _first_with_role(parties, "supplier")
        if supplier_party is None:
            # No supplier on this release at all — nothing to match against, skip it.
            continue

        abn = next(
            (
                ident.get("id")
                for ident in supplier_party.get("additionalIdentifiers", []) or []
                if ident.get("scheme") == "AU-ABN"
            ),
            None,
        )
        address = supplier_party.get("address") or {}
        value = contract.get("value") or {}
        unspsc = next(
            (
                (item.get("classification") or {}).get("id")
                for item in contract.get("items", []) or []
                if (item.get("classification") or {}).get("scheme") == "UNSPSC"
            ),
            None,
        )

        raw_amount = value.get("amount")
        try:
            amount = float(raw_amount) if raw_amount not in (None, "") else None
        except (TypeError, ValueError):
            amount = None

        contract_id = contract.get("id")
        out.append(
            ContractRecord(
                contract_id=contract_id,
                ocid=release.get("ocid"),
                supplier_name=supplier_party.get("name"),
                supplier_abn=abn,
                supplier_locality=address.get("locality"),
                supplier_region=address.get("region"),
                agency_name=agency.get("name") if agency else None,
                value_amount=amount,
                value_currency=value.get("currency"),
                unspsc_code=unspsc,
                description=contract.get("description") or contract.get("title"),
                date_signed=contract.get("dateSigned"),
                status=contract.get("status"),
                source="austender",
                tender_url=CN_URL_TEMPLATE.format(contract_id=contract_id) if contract_id else None,
                procurement_method=procurement_method,
                period_end_date=(contract.get("period") or {}).get("endDate"),
            )
        )
    return out


class AusTenderSource(TenderSource):
    key = "austender"

    def fetch(self, start_iso: str, end_iso: str) -> List[ContractRecord]:
        return fetch_by_last_modified(start_iso, end_iso)


SOURCE = AusTenderSource()
