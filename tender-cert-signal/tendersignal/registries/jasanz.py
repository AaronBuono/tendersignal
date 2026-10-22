"""Client for the public JAS-ANZ certified-organisations register.

The search UI at https://register.jasanz.org calls a plain JSON API directly — no auth token,
just a `referer` header in practice. Confirmed by inspecting the network calls the SPA makes and
replaying them directly with curl. There is no official published API contract for this, so treat
field names as observed-behaviour, not a stable guarantee, and fail soft if the shape changes.
"""

import logging
import time
from typing import List, Optional

import requests

from .base import CertificationRecord, CertificationRegistry

logger = logging.getLogger(__name__)

API_URL = "https://jasanzcupr-api.azurewebsites.net/api/V1/RegisterCertificate/GetAllFilterCertificate"
HEADERS = {
    "content-type": "application/json",
    "accept": "application/json, text/plain, */*",
    "referer": "https://register.jasanz.org/",
    "user-agent": "Mozilla/5.0 (compatible; tender-cert-signal/0.1; MVP research tool)",
}

# Backward-compatible alias — this project called it JasanzCertificate before there was more than
# one registry. Same type as the generic CertificationRecord now used everywhere.
JasanzCertificate = CertificationRecord


def _empty_search_body(organisation_name: str, page_size: int) -> dict:
    return {
        "certificateId": None,
        "PageNumber": 0,
        "PageSize": page_size,
        "schemeOwnerId": None,
        "organisationName": organisation_name,
        "tradingName": None,
        "certification": None,
        "city": None,
        "cab": None,
        "certScope": None,
        "certStatus": None,
        "country": [],
        "certificationStandards": [],
        "cabs": [],
        "programs": [],
        "isicCodes": [],
        "schemes": [],
        "certificateNumbers": [],
    }


def _parse_certificates(payload: dict) -> List[CertificationRecord]:
    if not payload.get("isSuccessful"):
        return []
    certs = []
    for c in (payload.get("data") or {}).get("certificateDtos", []) or []:
        certs.append(
            CertificationRecord(
                certificate_id=c.get("certificateId"),
                organisation_name=c.get("organisationName"),
                city=c.get("city"),
                country=c.get("countryName"),
                cab_name=c.get("cabName"),
                status=c.get("statusName"),
                expiry_date=c.get("expriryDate"),
                scopes=[s.get("scopeName") for s in c.get("scopes", []) or [] if s.get("scopeName")],
                registry="jasanz",
            )
        )
    return certs


class JasanzClient(CertificationRegistry):
    """Rate-limited, retrying client. One instance per pipeline run."""

    key = "jasanz"

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

    def search_by_name(self, organisation_name: str, page_size: int = 25) -> List[CertificationRecord]:
        if not organisation_name or not organisation_name.strip():
            return []
        body = _empty_search_body(organisation_name, page_size)

        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            self._last_call = time.monotonic()
            try:
                resp = self.session.post(API_URL, json=body, headers=HEADERS, timeout=self.timeout)
                resp.raise_for_status()
                return _parse_certificates(resp.json())
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning(
                    "JAS-ANZ lookup for %r failed (attempt %d/%d): %s",
                    organisation_name, attempt, self.max_retries, exc,
                )
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
        raise last_exc
