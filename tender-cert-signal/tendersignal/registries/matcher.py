"""Queries every registered CertificationRegistry for a supplier, in parallel, and pools whatever
candidate certificates come back for `matching.best_match` to score.

Registries run concurrently (each already rate-limits itself internally, the way JasanzClient
does) so total latency per supplier lookup is roughly the slowest single registry, not the sum of
every registry's own throttle — that matters the moment there's more than one registry, since
JAS-ANZ alone already rate-limits to ~1 request/second and a growing supplier backlog compounds a
sequential sum fast.
"""

import concurrent.futures
import logging
from typing import List

from .base import CertificationRecord, CertificationRegistry

logger = logging.getLogger(__name__)


class CertificationMatcher:
    def __init__(self, registries: List[CertificationRegistry]):
        self.registries = registries

    def search_by_name(self, organisation_name: str) -> List[CertificationRecord]:
        if not self.registries:
            return []
        candidates: List[CertificationRecord] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.registries)) as pool:
            futures = {
                pool.submit(registry.search_by_name, organisation_name): registry
                for registry in self.registries
            }
            for future in concurrent.futures.as_completed(futures):
                registry = futures[future]
                try:
                    candidates.extend(future.result())
                except Exception as exc:  # noqa: BLE001 - one registry failing shouldn't sink the others
                    logger.warning("[%s] lookup failed for %r: %s", registry.key, organisation_name, exc)
        return candidates
