"""Command-line entry point. Run `python -m tendersignal.cli --help` (or `tendersignal --help`
once installed) for usage.
"""

import argparse
import logging
import sys

from . import company_import, config, db, export, pipeline, sheet_sync


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tendersignal")
    parser.add_argument("--db", default=None, help="Path to the SQLite DB file (default: $DB_PATH or tendersignal.db)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialise the database schema and exit")
    sub.add_parser("run", help="Ingest new tenders, match against JAS-ANZ, and send the lead digest")
    sub.add_parser("recheck", help="Re-check previously-flagged leads for newer certification")

    go_p = sub.add_parser(
        "go", help="Do everything: fetch, match, recheck, write leads.csv and update the Google Sheet"
    )
    go_p.add_argument("--out", default="leads.csv", help="CSV path (default: leads.csv)")

    imp_p = sub.add_parser(
        "import-companies",
        help="Add a CSV list of small businesses to be checked for certification (company-first)",
    )
    imp_p.add_argument("file", help="CSV with at least a company name column")
    imp_p.add_argument("--label", required=True, help="Where this list came from, e.g. 'vic-builders-assoc'")
    imp_p.add_argument(
        "--standards", default=None,
        help="Standards to assume for rows without their own, e.g. '9001,45001'",
    )

    export_p = sub.add_parser("export", help="Export current open leads to CSV")
    export_p.add_argument("--out", default="leads.csv", help="Output CSV path (default: leads.csv)")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    conn = db.get_connection(args.db or config.DB_PATH)
    db.init_schema(conn)

    if args.command == "init":
        print("Database initialised.")
        return 0

    if args.command == "run":
        n = pipeline.run_once(conn, webhook_url=config.SLACK_WEBHOOK_URL)
        print(f"Notified {n} new lead(s).")
        return 0

    if args.command == "recheck":
        n = pipeline.run_recheck(conn)
        print(f"Recheck complete: {n} lead(s) resolved to certified.")
        return 0

    if args.command == "go":
        return _go(conn, args.out)

    if args.command == "import-companies":
        counts = company_import.import_companies(conn, args.file, args.label, args.standards)
        print(
            f"Imported {counts['added']} new compan(ies); {counts['skipped']} already known; "
            f"{counts['invalid']} skipped (no name, or no ISO 9001/14001/45001 to check). "
            "Run `go` to check them against the registers."
        )
        return 0

    if args.command == "export":
        rows = db.get_all_leads(conn)
        export.write_leads_csv(rows, args.out)
        print(f"Exported {len(rows)} open lead(s) to {args.out}")
        return 0

    parser.print_help()
    return 1


def _go(conn, out_path: str) -> int:
    """The one command a non-technical user runs. Each step is independent: a failure in one
    (e.g. the sheet being unreachable) is reported plainly and doesn't undo or block the rest."""
    print("1/4  Fetching new contracts and checking certification registers (this can take a while)...")
    db.reset_errors_to_pending(conn)
    conn.commit()
    pipeline.run_ingest(conn)
    pipeline.run_enrich_abn(conn)
    checked = pipeline.run_matching(conn)

    print("2/4  Re-checking older leads in case they've since certified...")
    resolved = pipeline.run_recheck(conn)

    if config.SLACK_WEBHOOK_URL:
        pipeline.run_notify(conn, webhook_url=config.SLACK_WEBHOOK_URL)

    rows = db.get_all_leads(conn, max_value=config.MAX_CONTRACT_VALUE)
    print("3/4  Writing the leads file...")
    export.write_leads_csv(rows, out_path)

    print("4/4  Updating the Google Sheet...")
    sheet_status = "not set up (see sheets/SETUP.md) — leads are in the CSV only"
    if config.SHEET_WEBHOOK_URL and config.SHEET_WEBHOOK_TOKEN:
        try:
            sheet_sync.push_leads(rows, config.SHEET_WEBHOOK_URL, config.SHEET_WEBHOOK_TOKEN)
            sheet_status = "updated"
        except Exception as exc:  # noqa: BLE001 - report, don't crash; the CSV is already written
            sheet_status = f"FAILED ({exc}) — leads are still in the CSV"

    print()
    if pipeline.last_ingest_failures:
        print(
            "WARNING: could not reach "
            + ", ".join(pipeline.last_ingest_failures)
            + " this run (internet down, or the site is blocking requests). No new contracts were "
            "fetched; it will retry the same window next time."
        )
    print(f"Checked {checked} new supplier(s); {resolved} older lead(s) turned out to be certified.")
    print(f"Open leads: {len(rows)}  |  CSV: {out_path}  |  Sheet: {sheet_status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
