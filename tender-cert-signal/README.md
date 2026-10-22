# tender-cert-signal

Cross-references recently-awarded [AusTender](https://www.tenders.gov.au/) contracts against the
public [JAS-ANZ certified organisations register](https://register.jasanz.org) to surface a proxy
signal: *"this business just won a government contract, and we can't find a JAS-ANZ-accredited ISO
certificate for it."* That's a lead — either a sales opportunity (if you sell certification
services) or a compliance flag (if you're checking supply-chain risk).

See [`IDEAS.md`](IDEAS.md) for everything deliberately deferred out of this MVP.

## How it works

1. **Ingest** — every registered tender source (see `tendersignal/sources/`) is polled independently,
   each with its own checkpoint, for contracts modified since its last run, and new/amended ones are
   staged in SQLite. Currently that's just [AusTender's OCDS API](https://app.swaggerhub.com/apis/austender/ocds-api/1.1)
   (public, no API key) — see "Widening the tender funnel" below for why it's the only one.
2. **Match** — for each new supplier, queries the JAS-ANZ register's public search API and
   fuzzy-matches the result against the supplier name (see `tendersignal/matching.py`).
3. **Notify** — anything with no confident match is a lead. Sends a digest to a Slack webhook
   (or prints it, if none is configured) and marks it notified so it's never sent twice.
4. **Recheck** — a separate command re-tests old leads later, in case they've since been certified.

Both APIs turned out to be plain, unauthenticated JSON endpoints once inspected directly (see
`IDEAS.md` for how these were found) — there's no browser automation or HTML scraping anywhere in
this pipeline, which makes it a lot more robust than it originally sounded.

## Widening the tender funnel

The pipeline is built around a `TenderSource` adapter interface (`tendersignal/sources/base.py`) so
any number of tender feeds can be checkpointed and matched identically — adding one is meant to be
"write an adapter," not "restructure the pipeline." See `tendersignal/sources/README.md` for the
contract.

AusTender is currently the *only* registered source, not because nothing else was considered: nine
other candidates (every AU state/territory tender portal, NZ GETS, GrantConnect, and a local-council
aggregator) were researched and none exposed a genuine, headlessly-reachable public feed — most are
behind active bot-management (Cloudflare, AWS WAF, Incapsula), one dedicated API is fully
decommissioned, and a couple of promising-looking bulk datasets turned out dead or years stale. Full
findings, per source, are in `IDEAS.md`.

## What counts as a lead

A supplier is a lead only if (a) its industry maps to a standard Kaiso handles (`categories.py`; an
unknown industry is *out of scope*, not defaulted to ISO 9001), (b) no **active** certificate matches
(expired/suspended certs no longer count as "certified"), and (c) it isn't an individual or a
government body (requires `ABN_LOOKUP_GUID`; without it sole traders can still appear).

## Known limitation

Matching runs against every registered `CertificationRegistry` (`tendersignal/registries/`) in
parallel — currently JAS-ANZ (AU/NZ) and ANAB (US, but only for organisations it accredits
*directly*: testing/cal labs, inspection bodies, etc. — not ISO 9001/14001/27001-style certificates
issued by an ANAB-accredited management-systems body). A business can still hold a perfectly
legitimate ISO management-system certificate accredited by UKAS, IAF-affiliated bodies, or another
national accreditor with no registered adapter, and correctly show up here as "no match." The
closest thing to a full fix (IAF CertSearch, which aggregates across accreditors globally) turned
out to require a paid Enterprise subscription — see `IDEAS.md` for the full research. Treat a
flagged lead as "no match across registered registries found," not "definitely uncertified," and
word any outreach accordingly.

## Quick start (non-technical)

Double-click `../Run Kaiso Leads.command`. It sets itself up on first run, then does everything
`tendersignal go` does: fetch → match → recheck → write `leads.csv` → update the Google Sheet
(`sheets/SETUP.md`). Leads are limited to what Kaiso can serve (ISO 9001/14001/45001), skip sole
traders/government (needs the ABN Lookup GUID), and skip contracts over `MAX_CONTRACT_VALUE`.

**Company-first leads:** `tendersignal import-companies list.csv --label "..." [--standards 9001,45001]`
stages any CSV of small businesses and checks each against the registers on the next `go`.

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -e .
cp .env.example .env   # edit SLACK_WEBHOOK_URL etc. as needed
```

## Usage

```bash
# One-off: create the DB schema
./.venv/bin/tendersignal init

# The main loop — run this daily (via cron/systemd timer, see below)
./.venv/bin/tendersignal run

# Re-test previously-flagged leads for newer certification
./.venv/bin/tendersignal recheck

# Dump all currently-open leads to CSV for the sales/compliance team
./.venv/bin/tendersignal export --out leads.csv
```

Put `-v` *before* the subcommand for debug logging, e.g. `tendersignal -v run`.

On the very first `run`, there's no checkpoint yet, so it backfills `LOOKBACK_DAYS` (default: 3)
days of AusTender history. Every run after that only fetches what changed since the last checkpoint.

## Configuration

All via environment variables / `.env` (see `.env.example` for the full list with defaults):

| Variable | Purpose |
|---|---|
| `DB_PATH` | SQLite file path |
| `SLACK_WEBHOOK_URL` | Where the lead digest gets posted. Unset = printed to stdout |
| `LOOKBACK_DAYS` | First-run backfill window |
| `MATCH_THRESHOLD` | Fuzzy-match score (0–100) to count as "certified" |
| `JASANZ_RATE_LIMIT_SECONDS` | Delay between JAS-ANZ lookups (politeness) |
| `RECHECK_DAYS` | How long before a lead is re-tested |
| `MIN_CONTRACT_VALUE` | Skip contracts below this AUD value entirely |
| `MAX_CONTRACT_VALUE` | Skip contracts above this AUD value (default 500,000; a rough proxy for "too big") |
| `SHEET_WEBHOOK_URL` / `SHEET_WEBHOOK_TOKEN` | Google Sheet sync via Apps Script — see `sheets/SETUP.md` |
| `ABN_LOOKUP_GUID` | Optional. Enables ABN-based supplier enrichment (canonical name, entity type). Free GUID from https://abr.business.gov.au/Tools/WebServices — unset = skipped entirely |

## Running it continually

This is a batch pipeline, not a long-lived daemon — schedule it. A daily cadence matches how often
AusTender awards actually land; there's no need for anything more real-time for the MVP.

**cron:**
```cron
# 6am daily: ingest, match, notify
0 6 * * * cd /path/to/tender-cert-signal && ./.venv/bin/tendersignal run >> tendersignal.log 2>&1
# Weekly recheck of old leads
0 7 * * 1 cd /path/to/tender-cert-signal && ./.venv/bin/tendersignal recheck >> tendersignal.log 2>&1
```

**systemd timer** (`~/.config/systemd/user/tendersignal.service` + a matching `.timer` with
`OnCalendar=daily`) works the same way if you'd rather not use cron.

## Development

```bash
./.venv/bin/pip install -e . pytest
./.venv/bin/pytest -q
```

Tests run fully offline against fixture data (including real captured API responses) — no network
calls happen during `pytest`.

## Project layout

```
tendersignal/
  sources/
    base.py       ContractRecord + the TenderSource adapter interface
    austender.py  AusTender OCDS API client + OCDS -> ContractRecord parsing (the reference adapter)
    README.md     How to add a new tender source
  registries/
    base.py       CertificationRecord + the CertificationRegistry adapter interface
    jasanz.py     JAS-ANZ register API client (the reference adapter)
    anab.py       ANAB directory client (narrower scope — see its module docstring)
    matcher.py    CertificationMatcher: queries every registered registry in parallel
    README.md     How to add a new certification registry
  matching.py     Fuzzy name matching between a supplier and registry candidates
  categories.py   UNSPSC code -> relevant ISO standard(s) mapping
  db.py           SQLite persistence (contracts, per-source sync checkpoints, amendment tracking)
  pipeline.py     Orchestrates ingest (across all sources) -> match (across all registries) -> notify -> recheck
  notify.py       Slack webhook digest formatting/sending
  export.py       CSV export for CRM hand-off
  cli.py          `tendersignal` command-line entry point
tests/            Offline unit + pipeline tests (tests/sources/, tests/registries/ mirror their packages)
IDEAS.md          Backlog / deferred ideas / API discovery notes (funnel- and registry-widening research)
```
