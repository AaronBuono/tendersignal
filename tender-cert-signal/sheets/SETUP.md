# Connect the lead sheet (one-time, ~5 minutes)

1. Create a new Google Sheet (any name). This is where your leads will live.
2. In the sheet: **Extensions → Apps Script**. Delete the starter code, paste in the whole of
   `leads_webhook.gs` from this folder.
3. At the top of the script, replace `change-me-to-a-long-random-string` with your own long random
   text (this is the password the tool uses). Save.
4. **Deploy → New deployment → type: Web app**.
   - Execute as: **Me**
   - Who has access: **Anyone**
   - Click Deploy, approve the permission prompt, and copy the **Web app URL** (ends in `/exec`).
5. Open `tender-cert-signal/.env` (created the first time you run the launcher) and fill in:
   ```
   SHEET_WEBHOOK_URL=<the /exec URL you copied>
   SHEET_WEBHOOK_TOKEN=<the same random text from step 3>
   ```
6. Run the launcher. A `Leads` tab appears and fills in.

Notes
- "Anyone" only means anyone *with the URL and the token* can send data in; the sheet itself stays
  private to you. Don't share the URL or token publicly, and rotate the token if it leaks.
- Re-running is safe: leads are matched on the **Lead ID** column, so nothing duplicates. The
  **Status / Owner / Notes** columns are yours — the tool never overwrites them.
- If you edit the script later, use **Deploy → Manage deployments → Edit → New version** or the
  change won't go live.
- This script has not yet been tested against a live Google account — if step 6 reports a failure,
  paste the message back and it can be fixed quickly.
