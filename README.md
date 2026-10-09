# SUL-Kaiso — lead finder

**To get today's leads:** double-click **`Run Kaiso Leads.command`**.

- First run installs everything (a few minutes, needs internet). After that it just runs.
- It finds new small-business leads that need ISO 9001 / 14001 / 45001, writes `leads.csv`, and
  updates your Google Sheet if you've set it up (one-time, ~5 min: `tender-cert-signal/sheets/SETUP.md`).
- macOS may ask you to allow it the first time: right-click the file → Open.
- Want to check your own list of businesses (an association member list, a prospect list)? Save it
  as a CSV with a `Company` column (optionally `ABN`, `State`, `Suburb`, `Standards`) and run, in
  Terminal from `tender-cert-signal/`: `./.venv/bin/tendersignal import-companies list.csv --label "name of list" --standards 9001,45001`
  then double-click the launcher again.

Details, settings and limits: `tender-cert-signal/README.md` and `tender-cert-signal/IDEAS.md`.
# tendersignal
