"""Shared contract every certification-registry adapter implements.

The matcher (`CertificationMatcher` in `matcher.py`) doesn't know or care whether a candidate came
from JAS-ANZ, UKAS, ANAB, or IAF CertSearch — it queries every registered `CertificationRegistry`
for a supplier name, pools every `CertificationRecord` that comes back, and scores the combined
pool the same way `matching.best_match` always has. See `tendersignal/registries/jasanz.py` for
the reference implementation and `tendersignal/registries/README.md` for how to add another.
"""

import abc
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CertificationRecord:
    organisation_name: Optional[str]
    city: Optional[str]
    country: Optional[str]
    cab_name: Optional[str]  # the certification/accreditation body that issued it
    status: Optional[str]
    expiry_date: Optional[str]
    scopes: List[str] = field(default_factory=list)
    certificate_id: Optional[str] = None

    # Added when this went from JAS-ANZ-only to multi-registry — defaulted so old call sites keep
    # working unchanged. New registries should set it to their own `key`.
    registry: str = "jasanz"


class CertificationRegistry(abc.ABC):
    """One adapter per certification/accreditation register.

    `key` must be short, stable, and filesystem/db-safe (it ends up in `match_registry` on a
    matched contract) — once a registry ships, don't rename its key without a data migration.
    """

    key: str

    @abc.abstractmethod
    def search_by_name(self, organisation_name: str) -> List[CertificationRecord]:
        """Return every certificate this registry holds for a name resembling `organisation_name`.

        Exact matching is not required here — the caller (`matching.best_match`) does its own
        fuzzy scoring against whatever candidates come back, the same way JAS-ANZ's own
        server-side partial match already works. Return an empty list for "no results", not an
        exception. It's fine to raise for a genuine failure (network down, unexpected response
        shape): `CertificationMatcher` treats that as this one registry failing soft for this
        lookup, while every other registered registry still gets queried.
        """
        raise NotImplementedError
