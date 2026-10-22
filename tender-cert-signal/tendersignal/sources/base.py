"""Shared contract every tender-source adapter implements.

The pipeline doesn't know or care whether a contract came from AusTender, NSW eTendering, or NZ
GETS — it just calls `.fetch()` on every registered `TenderSource` and treats the returned
`ContractRecord`s identically: checkpoint, stage, match against JAS-ANZ, notify. See
`tendersignal/sources/austender.py` for the reference implementation and
`tendersignal/sources/README.md` for how to add a new one.
"""

import abc
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ContractRecord:
    contract_id: str  # id unique *within* this source (not necessarily globally)
    ocid: Optional[str]
    supplier_name: str
    supplier_abn: Optional[str]
    supplier_locality: Optional[str]
    supplier_region: Optional[str]
    agency_name: Optional[str]
    value_amount: Optional[float]
    value_currency: Optional[str]
    unspsc_code: Optional[str]
    description: Optional[str]
    date_signed: Optional[str]
    status: Optional[str]

    # Added when the single-source (AusTender-only) version of this project grew into a
    # multi-source one — all have defaults so old call sites (and old tests) keep working
    # unchanged; new adapters should set what they can.
    source: str = "austender"
    tender_url: Optional[str] = None          # direct link to the public notice, if there is one
    procurement_method: Optional[str] = None  # e.g. "open", "limited", "panel" / standing offer
    period_end_date: Optional[str] = None     # contract end date, for renewal-window tracking

    @property
    def global_id(self) -> str:
        """Namespaced id, unique across every source combined — the DB's real dedup key."""
        return f"{self.source}:{self.contract_id}"


class TenderSource(abc.ABC):
    """One adapter per tender-publishing platform.

    `key` must be short, stable, and filesystem/db-safe (it's used in DB rows and sync_state
    checkpoint keys) — once a source ships, don't rename its key without a data migration.
    """

    key: str

    @abc.abstractmethod
    def fetch(self, start_iso: str, end_iso: str) -> List[ContractRecord]:
        """Return every contract/award modified in [start_iso, end_iso), in ContractRecord shape.

        Dates are ISO 8601 UTC, e.g. "2026-08-01T00:00:00Z". Must not raise for "zero results in
        this window" — return an empty list for that. It's fine to raise for a genuine failure
        (network down, unexpected response shape, auth expired): the pipeline treats that as this
        one source's ingest failing soft for this run — exactly the AusTender-outage recovery
        already built into `pipeline.run_ingest` — while every other registered source still runs.
        """
        raise NotImplementedError
