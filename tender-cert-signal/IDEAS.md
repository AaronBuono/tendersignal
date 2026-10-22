# Ideas backlog

Captured from the initial project discussion, plus what we learned once we actually
poked at the two data sources. MVP scope is in README.md — this file is everything
we deliberately deferred or noted as a future direction.

## Confirmed data sources (as of 2026-08-25)

- **AusTender OCDS API** — `https://api.tenders.gov.au/ocds/findByDates/contractLastModified/{start}/{end}`
  (also `contractPublished`, `contractStart`, `contractEnd`, `findById/{CN_ID}`). Public, no API key,
  returns Open Contracting Data Standard JSON with supplier name + ABN + address, agency, contract
  value, UNSPSC classification, and dates. Docs: https://app.swaggerhub.com/apis/austender/ocds-api/1.1
  Weekly bulk export also exists on data.gov.au if a full historical backfill is ever needed.
- **JAS-ANZ register** — the public search UI at https://register.jasanz.org calls a plain public JSON
  API directly: `POST https://jasanzcupr-api.azurewebsites.net/api/V1/RegisterCertificate/GetAllFilterCertificate`.
  No auth, just needs a `referer` header in practice. Takes `organisationName` (server-side partial
  match) plus optional city/CAB/scheme/standard filters, returns certificate holder name, city,
  country, accredited certification body (CAB) name, status (Active/etc.), expiry, and scope
  (e.g. `QMS:ISO 9001:2015`). This means **no browser automation is needed in production** — both
  ingestion and matching are plain HTTP+JSON.

## Deferred out of MVP (revisit later)

- **Contact-detail enrichment** — MVP flags a lead but doesn't find a person to email. Next step
  would be ABN Lookup API (free, official ABN Register data) for registered business details, then a
  paid enrichment source (Apollo, Hunter.io, Clearbit) only if ABN Lookup doesn't yield enough.
- **CRM integration** — MVP exports leads to CSV. Later, push straight into Airtable/HubSpot via
  API so the team works a real pipeline instead of an ad-hoc spreadsheet.
- **Broader accreditor coverage** — investigated 2026-09-12, see "Widening the certificate
  register" below. One additional registry (ANAB) is live, but it doesn't close the actual gap
  this was aimed at — still treat "no match across all registered registries" as "no match found,"
  not "not certified," in any outreach copy.
- **Realtime notifications** — MVP runs on a daily cron and sends a digest. If the team wants
  same-hour alerts on very large contracts, add a "high value fast-path" check that runs more often
  and only for contracts over some $ threshold.
- **"Still uncertified after N months" hot list** — the recheck loop already re-tests old leads;
  once that's running for a while, a lead that's still uncertified after repeated rechecks is
  probably a *better*, more qualified lead (they've had time to certify and haven't) — worth
  surfacing that segment distinctly rather than treating every recheck the same.
- **Category-to-standard mapping refinement** — the UNSPSC → ISO standard table in
  `tendersignal/categories.py` is a reasonable first pass, not exhaustive. Worth a pass by someone
  who knows the standards landscape (e.g. does ISO 27001 belong on more categories than just
  IT/defence?).
- **Multi-country expansion** — same pattern (a government tenders register + a certification
  register) likely exists in NZ (GETS) since JAS-ANZ covers NZ too. Could reuse most of the pipeline.
  (Investigated 2026-09-12 — see below. Not currently reachable; revisit if MBIE's stated OCDS
  alignment for GETS ever ships.)

## Widening the tender funnel — researched 2026-09-12

Built a `TenderSource` adapter architecture (`tendersignal/sources/`) so any number of tender
feeds can be checkpointed, staged, and matched identically. Parallel-researched 9 candidate
sources for a genuine, headlessly-reachable public feed (API/OCDS/bulk export — not an HTML form
meant for a browser). **All 9 came back infeasible.** AusTender's OCDS API is the exception, not
the norm — worth knowing before assuming "surely the states have the same thing."

| Source | Verdict | Why |
|---|---|---|
| NSW eTendering | ❌ | The dedicated API is fully decommissioned (redirects to buy.nsw.gov.au). The OCP historical bulk archive is real but frozen since Feb 2025. buy.nsw.gov.au's CSV export worked once, then returned AWS WAF JS-challenges on every subsequent call — indistinguishable from "zero results," too dangerous for an unattended job. |
| VIC Tenders | ❌ | Site-wide Cloudflare bot-management (confirmed 403 via direct curl). No developer API, no live dataset on data.vic.gov.au. Even a third-party OSS scraper needs TLS-impersonation to get past it. |
| QLD QTenders | ❌ | Client-only Blazor WASM SPA; its `/api/*` backend is explicitly `Disallow`'d in robots.txt. data.qld.gov.au's alternative is a dead 2019 dataset plus 369 fragmented per-agency disclosure files, no ABN/OCID. |
| WA Tenders | ❌ | `robots.txt` disallows everything except the homepage. Search is a CSRF-nonce'd session-based HTML form POST, not an API. No OCDS, no data.wa.gov.au dataset. |
| SA Tenders and Contracts | ❌ | Cloudflare-challenge-gated on every page tested, including search (`cf-mitigated: challenge`). No OCDS, no CKAN dataset. Independently corroborated by a third-party AU-tenders OSS project marking it unsupported for the same reason. |
| TAS / NT / ACT | ❌ (all three) | TAS: search backend explicitly returns HTML fragments, not data, capped at 500 results, no pagination. NT: real site is `tendersonline.nt.gov.au` (not the URL originally guessed); its open-data listing is a metadata stub with no hosted file. ACT: Cloudflare Turnstile-gated live site; its open-data "Contracts Register" is a frozen 2017-2021 snapshot. |
| Local council / VendorPanel | ❌ | VendorPanel's public API only ever returns *open* tenders — no award/winner data exists there by design, not by access restriction. TenderLink/LGCA is Incapsula-walled. data.gov.au has exactly one council with real structured data (Townsville) — monthly aggregate totals only, no supplier names. |
| NZ GETS | ❌ | Its one real machine-readable feed (RSS) lists only open tenders, no awards/suppliers. The promising MBIE bulk-CSV dataset 404s (and is separately Incapsula-gated). NZ has *stated intent* to align GETS with OCDS as a future roadmap item, not shipped. |
| GrantConnect | ❌ | No API or bulk export exists. The one data.gov.au dataset that looked relevant is DISR-only (not whole-of-government) and its declared "CSV" resource is actually a broken pointer to an HTML help page. Live site returns CloudFront WAF 403s to direct requests. |

**Pattern worth internalising**: AusTender is unusual in publishing a real, documented, unauthenticated
OCDS API. Every state/territory portal checked instead relies on either an active bot-management
product (Cloudflare, AWS WAF, Incapsula) or a session/CSRF-bound HTML form as its *only* interface —
several explicitly `robots.txt`-disallow the very paths that would carry structured data. Treat that
as the default assumption for any future source, not the exception: verify a real API exists before
assuming this project's AusTender experience generalises.

**Legitimate next steps if AU/NZ state-level coverage matters enough to pursue further** (none of
these are "just build a scraper" — they're different tools for a different problem):
- A manual, negotiated data-sharing request to the relevant department (several explicitly listed a
  human contact channel for their open-data stub, e.g. NT's CAPS Assist office).
- Revisit specific ones on a schedule: buy.nsw.gov.au (its CSV export's shape would map cleanly onto
  `ContractRecord` *if* the WAF issue is ever resolved or a legitimate access path is granted), NZ
  GETS (if MBIE ships its stated OCDS alignment).
- The frozen historical archives (NSW's OCP dataset to Feb 2025, ACT's Contracts Register to 2017-2021)
  are still usable as one-time historical seed data, independent of the live-ingest question this
  round was actually about.

## Widening the certificate register — researched 2026-09-12

Built a `CertificationRegistry` adapter architecture (`tendersignal/registries/`), mirroring the
`TenderSource` pattern, so the matcher can query any number of registries in parallel per supplier
instead of just JAS-ANZ. Researched the 4 most plausible additional accreditors — the ones whose
scope actually overlaps JAS-ANZ's (ISO management-system certification), not adjacent things like
testing-lab accreditation or ESG schemes.

| Registry | Verdict | Why |
|---|---|---|
| **ANAB** (US) | ✅ Built | Real, unauthenticated JSON API (`search.anab.org/index/searchorgs`), no CAPTCHA, no auth. **But**: only covers organisations ANAB accredits *directly* — testing/calibration labs, inspection bodies, PT providers, medical labs, biobanks (ISO 17025/17020/17034/17043/15189/20387). Zero coverage of ISO/IEC 17021-1 (the standard that covers the CBs issuing ISO 9001/14001/27001 to ordinary businesses) — confirmed empirically, every one of ~2,677 directory entries falls under the lab/inspection-body standards, none under 17021-1. Real businesses (Telstra, Boeing) correctly return no results. So it's a genuine addition, just a narrower one than hoped: useful for tender suppliers who are themselves testing/cal/inspection outfits, not for closing the "held an ISO 9001 cert via a US-accredited CB" gap this exercise was actually aimed at. |
| **UKAS** (UK) | ❌ Not feasible | The actual certificate-holder search (CertCheck) is CAPTCHA-gated, and UKAS's own published Security Statement states it's deliberately designed to prevent bulk extraction ("inability to generate lists of data... cannot be used to support any mass marketing"). The CB-directory fallback is `robots.txt`-disallowed and wouldn't fit the data shape (accreditation bodies, not certificate holders) anyway. |
| **SCC** (Canada) | ❌ Not feasible | Cloudflare Managed Challenge on every path. Notably, its `robots.txt` explicitly names and disallows `ClaudeBot` (alongside GPTBot, CCBot, etc.) — about as direct an anti-automation signal as a site can give. |
| **IAF CertSearch** (global, multi-accreditor) | ❌ Not feasible (commercially, not technically) | The one that mattered most, since it aggregates across every national accreditor at once. A real, documented, versioned REST API exists (`api.iafcertsearch.org`) — but since mid-2025 even the plain website search is metered and account-gated, and search-by-organisation-name specifically requires a paid **Enterprise** subscription. Unlike the others, this isn't a technical dead end: if the project ever has an Enterprise-tier account and API key, the documented schema maps cleanly onto `CertificationRecord`. **Revisit if a subscription is ever acquired** — don't rediscover this from scratch. |

**Net effect**: the "Leidos problem" (a large, credible supplier showing as `no_match` because its
real ISO 27001 cert is likely accredited overseas, not through JAS-ANZ) is **still open**. ANAB
shipping doesn't fix it — the actual fix requires either an IAF CertSearch subscription, or UKAS
via some commercial arrangement (both explicitly offer this at a price), or accepting the
limitation as documented in the README and README/outreach copy. This is a case where the honest
engineering answer is "the free options are exhausted, the remaining ones cost money" rather than
"keep looking for a workaround" — the same posture this project already took after the AusTender
API showed up genuinely free while its state-level counterparts didn't.

## Entity resolution — researched 2026-09-12

- **ABN Lookup integration** — ✅ Built (`tendersignal/abn_lookup.py`). Real, documented JSON API
  at `abr.business.gov.au/json/`, confirmed live (a GUID-rejected call returns a proper JSON body
  with every field key present but blank, not a 404/HTML page). Genuinely free, but requires
  registering for a GUID (~2 minutes, just an email address) — this project can't self-provision
  one, so enrichment is entirely opt-in via `ABN_LOOKUP_GUID` in `.env` and no-ops cleanly without
  it. Since AusTender already gives us each supplier's exact ABN, this looks the record up *by
  ABN*, not by name — no fuzzy matching involved, unlike the certification-registry side. Feeds
  `supplier_canonical_name`, `supplier_entity_type_code`/`_name`, and (once populated)
  auto-excluding individuals/sole traders from the lead pool, which the real run's leads showed is
  real noise (named ARC grant recipients like "John Justin Finlay-Jones" showing up as "leads").
  **Auto-exclusion itself isn't wired up yet** — the data is now collected, but nothing currently
  filters on `supplier_entity_type_code == 'IND'`. Worth doing as a follow-up once there's real
  enrichment data to look at.
- **ASIC corporate-structure cross-check** — ❌ Not feasible with free data. Directly inspected
  ASIC's actual free weekly bulk CSV (`data.gov.au` dataset `asic-companies`) — its real header row
  is `Company Name, ACN, Type, Class, Sub Class, Status, Date of Registration, Date of
  Deregistration, Previous State of Registration, State Registration number, Modified since last
  report, Current Name Indicator, ABN, Current Name, Current Name Start Date`. No parent/subsidiary,
  ownership, or shareholding field exists anywhere in it. True corporate-hierarchy data (which
  would be needed to catch "the uncertified bidder's parent company is actually certified") is only
  available via ASIC's paid extracts or a third-party paid aggregator (e.g. CompanyData.com) — not
  a free public source. Not pursued further; revisit only if the project is ever willing to pay for
  one of those.

## Notes on risk / etiquette

- Both APIs are the same ones the public-facing websites call, at reasonable request volumes
  (daily ingestion window, one JAS-ANZ lookup per new supplier) — this is not different in kind
  from a person doing the same searches by hand, just automated. Still worth keeping request
  volume polite (rate-limited JAS-ANZ client, no parallel hammering) and revisiting if either site's
  terms of use change.
- Outreach messaging should avoid asserting a company is "not ISO certified" — say "no JAS-ANZ
  match found" and let a human confirm before treating it as fact (see accreditor-coverage note
  above).


## Small-business / company-first sourcing — researched 2026-10-07

Goal: reach small Segment B companies, not government-contract winners. State portals were already
ruled out above, so these are the alternatives checked:

- **ABN Bulk Extract** (data.gov.au, CC-BY 3.0): real and free, but fields are ABN, status, entity
  type, legal/business/trading names, state + postcode, ACN, GST status, DGR status. **No industry
  code and no size** — so it can't tell you which of millions of businesses are builders or
  cleaners. Usable only as a name/ABN lookup, or with a crude name-keyword filter (not built: it
  would be a lottery at ~1 registry lookup per second).
- **AusTender OCDS API**: documented endpoints are contract notices only (findById, and
  findByDates on published/start/end/lastModified). No open tenders.
- **AusTender "Latest Approaches to Markets" RSS** (data.gov.au dataset `efe713db-…`, CC-BY 3.0,
  Dept of Finance): an official feed of *open* federal tenders, updated daily. Not integrated:
  the data.gov.au page doesn't document the item fields, and tenders.gov.au refused automated
  access during this research, so it's unknown whether items say anything about ISO requirements
  (the real requirements usually sit in downloadable tender documents). Next step: someone opens
  the feed in a normal browser, checks a few items, and decides if it's worth an adapter. It's
  also federal, so it doesn't answer the state-level question.
- **Built instead:** `tendersignal import-companies` — any CSV of businesses (association member
  lists, licence-register exports, Kaiso's own prospect lists) flows through the same match
  pipeline. The list is the part that needs sourcing; the checking is automated.
- **Legal reminders:** tenders.vic.gov.au prohibits commercial reuse (unchanged). Outreach to the
  resulting leads should be checked against the Spam Act and worded "no JAS-ANZ match found",
  not "not certified".
