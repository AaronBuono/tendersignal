"""Format and send the lead digest. Slack incoming webhook for MVP; anything else that accepts
a `{"text": "..."}` POST (Mattermost, Teams via a connector) works the same way.
"""

import logging
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)


def _format_value(amount: Optional[float]) -> str:
    return f"${amount:,.0f}" if amount else "value n/a"


def format_digest(leads: List) -> Optional[str]:
    if not leads:
        return None
    lines = [f"*{len(leads)} new tender award(s) with no JAS-ANZ certification match found:*", ""]
    for lead in leads:
        standards = ", ".join(lead.relevant_standards) if lead.relevant_standards else "ISO 9001"
        source_tag = f"[{lead.source}] " if getattr(lead, "source", "austender") != "austender" else ""
        line = (
            f"• {source_tag}*{lead.supplier_name}* ({lead.agency_name or 'unknown agency'}) — "
            f"{_format_value(lead.value_amount)} — likely gap: {standards}"
        )
        if lead.tender_url:
            line += f"\n   <{lead.tender_url}|{lead.contract_id}>"
        else:
            line += f"\n   {lead.contract_id}"
        lines.append(line)
    return "\n".join(lines)


def send_slack_digest(webhook_url: str, leads: List, timeout: int = 15) -> bool:
    text = format_digest(leads)
    if not text:
        return False
    resp = requests.post(webhook_url, json={"text": text}, timeout=timeout)
    resp.raise_for_status()
    return True
