# Connect shared work manifests to observed PR and CI outcomes

Add optional work status --remote observations for declared GitHub PRs: open/draft/merged/closed state and CI for the observed head SHA. Reuse duplicate PR lookups, bound the whole refresh, preserve declared state, and expose unavailable/unknown without gates. Default status/startup/backlog behavior remains unchanged. Ship terminal and JSON output, accurate docs, and real installed-package verification; no dashboard, scheduler, new review rounds, or automatic remote work.

Completed 2026-09-29: [Tautline 0.150.0](https://github.com/Tautlines/tautline/releases/tag/v0.150.0) is published on GitHub, PyPI and npm. Source CI passed 2,830 tests; public source CI passed; the exact published PyPI wheel passed 88 workflow commands including live PR observations and independent-clone regression checks.

Source and installed runtime include the optional PR outcome view. Default startup and work pickup remain unchanged. The one assembled review found no material actionable issues. Follow-up polish is queued for a compact visual fleet view and registry propagation handling.
