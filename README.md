# Summer 2027 internship tracker

Requires Python 3.11+, with no third-party packages or secrets for log mode.

Run `python agent.py --log internships_log.md --dry-run` to preview, or omit `--dry-run` to append new matches. The daily workflow runs at approximately 13:17 UTC and supports manual dispatch. Existing URLs seed deduplication; existing entries are preserved. All-source failure stops the run. Partial failures are reported. This bot finds postings; it does not submit applications.

## Recovery

All 360 available commits, from root `848bf641d656b483585ebfab4a9e73edb49abe22` to `c58ec9e31cf44b81b71f1596da1a2f18d383b4db`, contain only `internships_log.md`. The latest parent is `fa651fe900ce03bb69589c998ddc8390943b32a7`. Only master was available. No implementation deletion exists in this history; a separate or rewritten history cannot be ruled out.

Recovered the scraper and configuration from the earlier Summer-2027-SWE-Internship-Agent.zip, then added append-only log mode and adapted its daily workflow. The ZIP is a recovery source, not proof of the code that produced the historical commits. Its configuration covers 15 Greenhouse, Lever, and Ashby boards and filters/ranks Summer 2027 roles. SMTP mode remains available locally; the workflow only writes the log.
