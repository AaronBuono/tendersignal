"""Environment-driven configuration. Load once, import the module, read attributes."""

import os

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.environ.get("DB_PATH", "tendersignal.db")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL") or None
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "3"))
MATCH_THRESHOLD = int(os.environ.get("MATCH_THRESHOLD", "87"))
JASANZ_RATE_LIMIT_SECONDS = float(os.environ.get("JASANZ_RATE_LIMIT_SECONDS", "1.0"))
RECHECK_DAYS = int(os.environ.get("RECHECK_DAYS", "30"))
MIN_CONTRACT_VALUE = float(os.environ.get("MIN_CONTRACT_VALUE", "0") or 0)

# Free, but requires registering for a GUID at https://abr.business.gov.au/Tools/WebServices —
# ABN-enrichment is skipped entirely if this is unset.
ABN_LOOKUP_GUID = os.environ.get("ABN_LOOKUP_GUID") or None

# Lead-quality filters (the pipeline is aimed at small businesses Kaiso can actually help).
# Contracts above this AUD value are skipped as "too big" (0 = no cap). Contract value is only a
# rough proxy for company size, so treat the default as a starting guess and tune it.
MAX_CONTRACT_VALUE = float(os.environ.get("MAX_CONTRACT_VALUE", "500000") or 0)

# Lead sheet sync: URL + shared secret of the Google Apps Script web app (see sheets/SETUP.md).
# Both unset = skip the sheet sync and just write leads.csv.
SHEET_WEBHOOK_URL = os.environ.get("SHEET_WEBHOOK_URL") or None
SHEET_WEBHOOK_TOKEN = os.environ.get("SHEET_WEBHOOK_TOKEN") or None
