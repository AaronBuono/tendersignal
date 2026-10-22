# Adding a tender source

Every source is a small adapter implementing `TenderSource` from `base.py`. The pipeline
(`pipeline.run_ingest`) treats every registered source identically: it tracks that source's own
sync checkpoint, calls `.fetch(start_iso, end_iso)`, stages whatever comes back, and matches every
staged contract against JAS-ANZ the same way regardless of where it came from.

## Steps

1. **Research first, build second.** Check whether the platform has an actual public API, bulk
   export, or open-data feed (JSON/XML/CSV/OCDS) — not just an HTML search form meant for a
   browser. Use the same approach that found AusTender's real OCDS endpoints and JAS-ANZ's
   register API: search for official docs, then inspect real network requests (a browser's
   dev tools / Playwright network capture) if the docs are thin, then confirm with a plain `curl`
   outside a browser context. If there's no headless-reachable public data source — only a
   login-gated portal, a form that requires solving a CAPTCHA, or explicit anti-automation
   measures — **don't build a scraper that fights that**. Write up why it's not feasible instead;
   that's a legitimate, useful answer.

2. **Implement the adapter** in `tendersignal/sources/<key>.py`:
   - A `<Something>Source(TenderSource)` class with a short, stable `key` (lowercase,
     underscore-separated, e.g. `nsw_etendering`).
   - `fetch(start_iso, end_iso) -> List[ContractRecord]`, returning `ContractRecord`s (import from
     `.base`) with as many fields populated as the source actually provides. Leave the rest
     `None` — don't invent data (e.g. don't guess an ABN if the source doesn't supply one).
   - Handle the source's own quirks explicitly and document them in a docstring, the way
     `austender.py` documents the API's pagination-drift and "400 means zero results" behaviours.
     Real APIs are never as clean as their docs promise — assume there's at least one, verify it,
     don't guess.
   - Add a retry for transient connection failures (see `austender._get_with_retries` for the
     pattern) if the source is a plain HTTP call.
   - Expose a module-level `SOURCE = <Something>Source()` singleton — that's what gets registered.

3. **Test it** in `tests/sources/test_<key>.py`, fully offline: capture 1-2 *real* responses from
   the live source while researching it, and use them as fixtures (see
   `tests/sources/test_austender.py`). No test should make a real network call.

4. **Report back, don't wire it in yourself.** Leave `tendersignal/sources/__init__.py`,
   `pipeline.py`, `db.py` and every other existing file untouched — those get one integration pass
   afterward to avoid clashing edits when multiple sources are being built at once. Just create
   your new files, run your new tests, and report: feasible or not, what you found, what you
   built, test results.

## ContractRecord fields worth knowing

- `source` — set this to your adapter's `key`.
- `tender_url` — a direct link to the public notice, if the source has stable URLs for one.
- `procurement_method` — e.g. "open" / "limited" / a panel or standing-offer arrangement, if the
  source distinguishes these.
- `period_end_date` — the contract's end date, if published — feeds renewal-window tracking.
- Everything else mirrors what AusTender already provides: supplier name/ABN/locality/region,
  agency name, value + currency, a category code if there is an equivalent to UNSPSC, description,
  date signed, status.
