"""Client for ANAB's public "Directory of Accredited Organizations" register.

https://search.anab.org is a plain server-rendered search form (jQuery + `$.ajax`) that posts to
a JSON backend at ``/index/searchorgs`` and renders the results client-side. Confirmed for real
with a bare `curl` (no browser, no cookies, no auth header, no CAPTCHA) — see the module-level
research notes in the PR/report that added this file for the exact commands used.

IMPORTANT SCOPE LIMITATION — read before wiring this into the matcher:

ANAB accredits two very different kinds of thing, and this directory only covers one of them:

1. Organisations ANAB accredits *directly*: testing/calibration laboratories (ISO/IEC 17025),
   inspection bodies (ISO/IEC 17020), reference material producers (ISO 17034), proficiency
   testing providers (ISO/IEC 17043), medical/clinical testing labs (ISO 15189), and biobanks
   (ISO 20387). ``search.anab.org`` covers *only* this population — confirmed empirically: a
   blank search returned ~2,677 organisations and every one of them carried one of exactly those
   six standards.
2. Management-systems certification bodies ANAB accredits under ISO/IEC 17021-1 (the CBs that
   then go on to issue ISO 9001 / ISO 14001 / ISO 27001 etc. certificates to ordinary
   businesses) and product-certification bodies under ISO/IEC 17065. This directory contains
   *zero* entries under either standard — it is not a route to "does this tender-winning
   business hold an ISO 9001 certificate issued by an ANAB-accredited CB". Businesses like
   Telstra or Boeing (tested directly against this endpoint) return no results, as expected,
   because they are not themselves ANAB accredited — their certifier would be.

So this adapter is a genuine, real, headlessly-reachable ANAB data source, but it answers a
narrower question than the JAS-ANZ adapter does: "is this organisation itself an ANAB-accredited
lab/inspection-body/PT-provider/etc." rather than "does this organisation hold an ISO 9001-style
certificate issued by *some* ANAB-accredited certification body". It's still useful — plenty of
tender-relevant suppliers (environmental/materials testing labs, inspection agencies, calibration
houses) are ANAB-accredited organisations in their own right — just don't expect it to close the
ISO-9001/14001 gap JAS-ANZ leaves for US-certified suppliers. ANAB does not appear to publish a
public certificate-holder search for that population, nor a machine-readable list of its
accredited CBs (the closest such page, https://anab.ansi.org/directories/, is an HTML directory
page, not an API, and wasn't scraped here per the "no HTML-search-form scraping" rule).

Other observed quirks:
- No auth, no session cookie required, no CAPTCHA. A bare `POST` with just a `company` field
  works; the site's own form also serializes empty `keyword`, `certificateNumber`, `country`,
  `state`, `city`, `zip`, `accreditation_status`, `standard` fields, which we include for parity
  even though testing showed they aren't required.
- Matching is server-side substring/fuzzy match on `company` (and separately on `keyword`); it
  returns `[]` (a bare JSON array, not an envelope) for no matches, and an array of org dicts
  otherwise. There's no pagination — a blank query returns the entire directory.
- `effective_through` is documented here as "expiry date" but is not always a date: for
  non-Active accreditations it can be a free-text status string, e.g.
  ``"VOLUNTARILY WITHDRAWN AS OF 02/22/2026 UNTIL FURTHER NOTICE"``. Passed through as-is —
  parse it defensively downstream, don't assume it's always `YYYY-MM-DD`-shaped.
- `categories` is a dict of {category group: [scope item, ...]}, e.g.
  ``{"Calibration Labs": ["Length - Dimensional Metrology"]}``. Flattened into `scopes` as
  ``"<group>: <item>"`` strings, with the `accreditation_standard` (e.g. "ISO/IEC 17025:2017")
  prepended as its own scope entry so it isn't lost.
- There is no separate "certifying body" in this dataset distinct from ANAB itself — ANAB is the
  direct accreditor of every organisation this endpoint returns, so `cab_name` is always the
  literal string ``"ANAB"``. That's a real observation, not an invented default.
- No official published API contract, same caveat as JAS-ANZ: treat field names as
  observed-behaviour and fail soft if the shape changes.
"""

import logging
import time
from typing import List, Optional

import requests

from .base import CertificationRecord, CertificationRegistry

logger = logging.getLogger(__name__)

API_URL = "https://search.anab.org/index/searchorgs"
HEADERS = {
    "accept": "application/json, text/plain, */*",
    "referer": "https://search.anab.org/",
    "user-agent": "Mozilla/5.0 (compatible; tender-cert-signal/0.1; MVP research tool)",
}


def _empty_search_form(organisation_name: str) -> dict:
    # Mirrors every field #labSearchForm serializes on the live site. Only `company` was found to
    # be necessary in testing, but sending the rest blank keeps this aligned with the real form
    # in case the backend ever starts requiring them.
    return {
        "keyword": "",
        "company": organisation_name,
        "certificateNumber": "",
        "country": "",
        "state": "",
        "city": "",
        "zip": "",
        "accreditation_status": "",
        "standard": "",
    }


def _flatten_scopes(org: dict) -> List[str]:
    scopes = []
    standard = org.get("accreditation_standard")
    if standard:
        scopes.append(standard)
    for group, items in (org.get("categories") or {}).items():
        for item in items or []:
            if item:
                scopes.append(f"{group}: {item}")
    return scopes


def _parse_organisations(payload) -> List[CertificationRecord]:
    if not payload:
        return []
    if not isinstance(payload, list):
        # Unexpected shape (e.g. an error page fronted by the same content-type) — fail soft.
        return []
    records = []
    for org in payload:
        if not isinstance(org, dict):
            continue
        records.append(
            CertificationRecord(
                certificate_id=org.get("certificate_number"),
                organisation_name=org.get("name"),
                city=org.get("city"),
                country=org.get("country"),
                cab_name="ANAB",
                status=org.get("accreditation_status"),
                expiry_date=org.get("effective_through"),
                scopes=_flatten_scopes(org),
                registry="anab",
            )
        )
    return records


class AnabRegistry(CertificationRegistry):
    """Rate-limited, retrying client for search.anab.org's directory of accredited organisations.

    See the module docstring for the important scope limitation: this only covers organisations
    ANAB accredits directly (testing/calibration labs, inspection bodies, PT providers, medical
    labs, biobanks), not businesses certified by an ANAB-accredited management-systems CB.
    """

    key = "anab"

    def __init__(
        self,
        rate_limit_seconds: float = 1.0,
        max_retries: int = 3,
        timeout: int = 20,
        session: Optional[requests.Session] = None,
    ):
        self.rate_limit_seconds = rate_limit_seconds
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = session or requests.Session()
        self._last_call = 0.0

    def _throttle(self):
        elapsed = time.monotonic() - self._last_call
        wait = self.rate_limit_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    def search_by_name(self, organisation_name: str) -> List[CertificationRecord]:
        if not organisation_name or not organisation_name.strip():
            return []
        form = _empty_search_form(organisation_name)

        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            self._last_call = time.monotonic()
            try:
                resp = self.session.post(API_URL, data=form, headers=HEADERS, timeout=self.timeout)
                resp.raise_for_status()
                return _parse_organisations(resp.json())
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning(
                    "ANAB lookup for %r failed (attempt %d/%d): %s",
                    organisation_name, attempt, self.max_retries, exc,
                )
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
        raise last_exc
