# Adding a certification registry

Every registry is a small adapter implementing `CertificationRegistry` from `base.py`. The
matcher (`CertificationMatcher` in `matcher.py`) treats every registered registry identically: it
queries each one (in parallel) for a supplier name, pools every `CertificationRecord` that comes
back, and `matching.best_match` scores the combined pool the same way regardless of which registry
a candidate came from.

## Steps

1. **Research first, build second.** Check whether the registry has an actual public API, bulk
   export, or search endpoint reachable without a browser — not just an HTML search form. Use the
   same approach that found JAS-ANZ's real register API: search for official docs, then inspect
   real network requests (browser dev tools / a Playwright network capture) if docs are thin, then
   confirm with a plain `curl` outside a browser context. If there's no headless-reachable public
   data source — only a login-gated portal, one that requires solving a CAPTCHA, or explicit
   anti-automation measures — **don't build a scraper that fights that**. Write up why it's not
   feasible instead; that's a legitimate, useful answer (see `IDEAS.md` for what this looked like
   the last time this project researched a batch of sources — most of AusTender's state-level
   tender-portal counterparts turned out the same way).

2. **Implement the adapter** in `tendersignal/registries/<key>.py`:
   - A `<Something>Registry(CertificationRegistry)` (or a client class, see `jasanz.py`) with a
     short, stable `key` (lowercase, underscore-separated, e.g. `ukas`, `anab`).
   - `search_by_name(organisation_name) -> List[CertificationRecord]`, returning
     `CertificationRecord`s (import from `.base`) with as many fields populated as the registry
     actually provides, and `registry` set to your `key`. Leave the rest `None`/empty — don't
     invent data the source doesn't give you.
   - Document any real quirks you find, the way `jasanz.py` documents that its API has no official
     published contract and its field names are observed behaviour, not a guarantee.
   - Rate-limit and retry your own requests (see `JasanzClient` for the pattern) — the matcher
     queries every registry in parallel, so it's each registry's own job to be polite to its
     source, not the matcher's.

3. **Test it** in `tests/registries/test_<key>.py`, fully offline: capture 1-2 *real* responses
   from the live registry while researching it, and use them as fixtures (see
   `tests/registries/test_jasanz.py`). No test may hit the network.

4. **Report back, don't wire it in yourself.** Leave `tendersignal/registries/__init__.py`,
   `pipeline.py`, `db.py` and every other existing file untouched — those get one integration pass
   afterward to avoid clashing edits when multiple registries are being built at once. Just create
   your new files, run your new tests, and report: feasible or not, what you found, what you
   built, test results.

## A note on what actually reduces false "no match" results

JAS-ANZ only accredits certification bodies operating in Australia/NZ. A business can hold a
perfectly legitimate ISO certificate issued by a body accredited elsewhere (UKAS in the UK, ANAB
in the US, SCC in Canada, etc.) and correctly show up as "no JAS-ANZ match" while still being
certified — that's the known limitation documented in the main README. The registries worth
prioritising are the ones that close that gap: other national accreditation bodies, and especially
any registry that aggregates across *multiple* accreditors at once (e.g. IAF CertSearch), since one
of those is worth several single-country ones.
