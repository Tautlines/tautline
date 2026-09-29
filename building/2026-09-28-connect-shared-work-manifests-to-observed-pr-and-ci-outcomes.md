# Connect shared work manifests to observed PR and CI outcomes

Add optional work status --remote observations for declared GitHub PRs: open/draft/merged/closed state and CI for the observed head SHA. Reuse duplicate PR lookups, bound the whole refresh, preserve declared state, and expose unavailable/unknown without gates. Default status/startup/backlog behavior remains unchanged. Ship terminal and JSON output, accurate docs, and real installed-package verification; no dashboard, scheduler, new review rounds, or automatic remote work.
