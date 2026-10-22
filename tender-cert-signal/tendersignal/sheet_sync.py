"""Push the current leads into a Google Sheet through a tiny Google Apps Script web app.

Why Apps Script instead of the Google Sheets API: the API needs a Google Cloud project, a service
account and a shared key file — a lot of setup for a non-developer. An Apps Script web app is
~2 minutes (paste a script into the sheet, deploy, copy the URL) and works exactly like the Slack
webhook already used here. See `sheets/SETUP.md` and `sheets/leads_webhook.gs`.

The script keys each row on the first column (`Lead ID`): new leads are appended, existing ones
get their machine-filled columns refreshed, and the team's own columns (Status / Owner / Notes)
are never overwritten.
"""

import logging
from typing import List, Optional

import requests

from .export import lead_dicts

logger = logging.getLogger(__name__)


def push_leads(rows: List, url: Optional[str], token: Optional[str], timeout: int = 60) -> Optional[dict]:
    """POST every current lead to the sheet. Returns the script's JSON reply, or None if the
    sheet isn't configured. Raises on a failed/rejected request so the caller can report it."""
    if not url or not token:
        return None
    payload = {"token": token, "leads": lead_dicts(rows)}
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError(
            "The sheet webhook did not return JSON — check SHEET_WEBHOOK_URL is the web app's "
            "'/exec' URL and the script is deployed for 'Anyone'."
        ) from exc
    if not data.get("ok"):
        raise RuntimeError(f"Sheet webhook rejected the update: {data.get('error', data)}")
    logger.info("Sheet updated: %s", data)
    return data
