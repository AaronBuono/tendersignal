"""Registry of every tender-source adapter the pipeline knows about.

To add a new source: write a module here implementing `TenderSource` (see `base.py`), expose a
module-level `SOURCE` instance, then add it to `ALL_SOURCES` below. Nothing else in the pipeline
needs to change — `pipeline.run_ingest` iterates `ALL_SOURCES` and checkpoints/stages/matches each
one identically.
"""

from .austender import SOURCE as AUSTENDER
from .base import ContractRecord, TenderSource

ALL_SOURCES = [
    AUSTENDER,
]

__all__ = ["ContractRecord", "TenderSource", "ALL_SOURCES"]
