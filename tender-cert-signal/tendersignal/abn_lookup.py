"""Client for the ABN Lookup JSON API (Australian Business Register).

https://abr.business.gov.au/json/ is a real, documented JSON API — but unlike JAS-ANZ's register,
it requires a **free registered GUID** (a ~2-minute signup at
https://abr.business.gov.au/Tools/WebServices, no cost, just an email address) that this project
cannot self-provision. Confirmed live: calling it with no/invalid GUID returns a proper JSON body
(every field present but blank, plus `"Message": "The GUID entered is not recognised as a
Registered Party"`) rather than a 404 or an HTML page — so the endpoint and its field names are
real and confirmed, we just can't exercise the success path without a real GUID. Set
`ABN_LOOKUP_GUID` in `.env` to enable this; every caller in this project treats "not enabled" as
"skip enrichment entirely," not an error.

We already have each supplier's ABN directly from AusTender's own OCDS payload (the AU-ABN
identifier), so this looks a record up **by ABN**, not by name — a plain, unambiguous lookup, not
a fuzzy match. That's what makes it worth doing even though the fuzzy-matching machinery for
certification registries already exists: there's no ambiguity to resolve here at all.

Response shape (JSONP-wrapped as `callback({...})` even when no `callback` query param is passed —
strip that before parsing). Every one of these keys was directly observed in a real (GUID-rejected)
response; only the *values* below are illustrative, since a real success case needs a real GUID:
    {"Abn": "...", "AbnStatus": "...", "AbnStatusEffectiveFrom": "...", "Acn": "...",
     "AddressDate": null, "AddressPostcode": "...", "AddressState": "...", "BusinessName": [...],
     "EntityName": "...", "EntityTypeCode": "...", "EntityTypeName": "...", "Gst": null,
     "Message": "..."}
`BusinessName`'s element shape (plain strings vs. `{"OrganisationName": ...}` objects) is not
directly confirmed either way — `_extract_trading_names` below handles both defensively rather
than assuming one.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

API_URL = "https://abr.business.gov.au/json/AbnDetails.aspx"
_JSONP_WRAPPER = re.compile(r"^\s*callback\((.*)\)\s*;?\s*$", re.S)


@dataclass
class AbnDetails:
    abn: Optional[str]
    abn_status: Optional[str]
    entity_name: Optional[str]
    entity_type_code: Optional[str]
    entity_type_name: Optional[str]
    trading_names: List[str] = field(default_factory=list)
    state: Optional[str] = None
    postcode: Optional[str] = None
    gst_registered: Optional[bool] = None


def _strip_jsonp(text: str) -> dict:
    match = _JSONP_WRAPPER.match(text)
    payload = match.group(1) if match else text
    return json.loads(payload)


def _extract_trading_names(raw) -> List[str]:
    names = []
    for item in raw or []:
        if isinstance(item, str) and item:
            names.append(item)
        elif isinstance(item, dict):
            name = item.get("OrganisationName") or item.get("Name") or item.get("organisationName")
            if name:
                names.append(name)
    return names


def _parse_abn_details(payload: dict) -> Optional[AbnDetails]:
    if payload.get("Message"):
        # Every field comes back present-but-blank alongside a Message on failure (invalid GUID,
        # invalid/unknown ABN, etc.) rather than the key being omitted — treat any Message as "no
        # usable data," not just log it.
        logger.warning("ABN Lookup returned a message instead of data: %s", payload["Message"])
        return None
    if not payload.get("Abn") and not payload.get("EntityName"):
        return None
    return AbnDetails(
        abn=payload.get("Abn") or None,
        abn_status=payload.get("AbnStatus") or None,
        entity_name=payload.get("EntityName") or None,
        entity_type_code=payload.get("EntityTypeCode") or None,
        entity_type_name=payload.get("EntityTypeName") or None,
        trading_names=_extract_trading_names(payload.get("BusinessName")),
        state=payload.get("AddressState") or None,
        postcode=payload.get("AddressPostcode") or None,
        gst_registered=bool(payload["Gst"]) if payload.get("Gst") is not None else None,
    )


class AbnLookupClient:
    """Rate-limited, retrying client. `enabled` is False (and every lookup a no-op returning
    None) whenever no GUID is configured — callers should check `.enabled` to skip entirely
    rather than pay for a call that can only ever fail.
    """

    def __init__(
        self,
        guid: Optional[str] = None,
        rate_limit_seconds: float = 1.0,
        max_retries: int = 3,
        timeout: int = 15,
        session: Optional[requests.Session] = None,
    ):
        self.guid = guid or None
        self.rate_limit_seconds = rate_limit_seconds
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = session or requests.Session()
        self._last_call = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.guid)

    def _throttle(self):
        elapsed = time.monotonic() - self._last_call
        wait = self.rate_limit_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    def lookup_by_abn(self, abn: str) -> Optional[AbnDetails]:
        if not self.enabled or not abn:
            return None
        digits = re.sub(r"\D", "", abn)
        if len(digits) != 11:
            logger.warning("ABN %r is not 11 digits, skipping lookup", abn)
            return None

        params = {"abn": digits, "guid": self.guid}
        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            self._last_call = time.monotonic()
            try:
                resp = self.session.get(API_URL, params=params, timeout=self.timeout)
                resp.raise_for_status()
                return _parse_abn_details(_strip_jsonp(resp.text))
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                logger.warning(
                    "ABN Lookup failed for %r (attempt %d/%d): %s", abn, attempt, self.max_retries, exc
                )
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
        raise last_exc
