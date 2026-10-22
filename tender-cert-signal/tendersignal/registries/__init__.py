"""Registry of every certification-register adapter the matcher knows about.

To add a new one: write a module here implementing `CertificationRegistry` (see `base.py`),
expose a module-level `REGISTRY` instance, then add it to `ALL_REGISTRIES` below. Nothing else
needs to change — `CertificationMatcher` (in `matcher.py`) queries every registered registry the
same way regardless of how many there are.
"""

from .. import config
from .anab import AnabRegistry
from .base import CertificationRecord, CertificationRegistry
from .jasanz import JasanzClient

JASANZ = JasanzClient(rate_limit_seconds=config.JASANZ_RATE_LIMIT_SECONDS)
ANAB = AnabRegistry()

ALL_REGISTRIES = [
    JASANZ,
    ANAB,
]

__all__ = ["CertificationRecord", "CertificationRegistry", "ALL_REGISTRIES"]
