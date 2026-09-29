"""Jira Cloud as a registered backlog provider — declared, and not yet implemented.

This module is deliberately almost empty, and that is the release's whole point. An adapter can now
**name and configure** a Jira board: `siteUrl`, `projectKey`, optionally `boardId`, plus `emailEnv`
and `apiTokenEnv` naming the environment variables that hold the account email and API token. The
adapter loads, validates and renders.

It cannot yet **drive** one. Every board verb is declared unavailable, so each refuses by name
rather than failing obscurely — the state the capability probe was built for in this program's
first release: a provider may legitimately be named while a verb is unavailable, and saying so
precisely is better than a crash or, far worse, a silent fall back to GitHub.

**Nothing here has spoken to a real Jira instance.** The endpoints and field shapes this provider
will use come from documentation, not from a live call, and no credentials exist in the environment
that built it. It must not be described as *supported* anywhere user-facing until a live validation
run is recorded — authenticate, JQL-search, read transitions, transition a scratch issue, post a
comment. That is filed as a hard-to-reverse decision awaiting the operator.

The verbs are defined rather than omitted because the contract requires every category verb to exist
with a callable signature the contract can bind. Their bodies are unreachable: `Provider.require`
refuses before any of them is entered, and `resolve_category_provider` calls it on every dispatch.
"""

from __future__ import annotations

from pathlib import Path

from tautline_methodology.providers import PROVIDER_CATEGORIES, Provider, register_provider


class JiraBacklogProvider(Provider):
    """Jira Cloud, declared for the `backlog` category with no verb yet available.

    `unavailable_verbs` is derived from the category contract rather than listed by hand: a verb
    added to the contract later must not silently become "available" on a provider that cannot serve
    it. Implementing one means removing it from this set in the same commit that adds its body.
    """

    provider_id = "jira"
    category = "backlog"
    #: Derived by SUBTRACTION from the category contract, never listed: a verb added to the contract
    #: later must not silently become available on a provider that cannot serve it. Implementing
    #: one means adding it here in the same commit that adds its body.
    _IMPLEMENTED: frozenset[str] = frozenset()
    unavailable_verbs = frozenset(PROVIDER_CATEGORIES["backlog"]) - _IMPLEMENTED

    def _unreachable(self, verb: str) -> None:
        # Defence in depth. `require` refuses first on every dispatch path, so reaching a body here
        # means a caller bypassed the seam -- which should fail loudly rather than return a
        # plausible empty value that reads as "the board has nothing in it".
        raise self.capability_exception(verb)

    def list_items(
        self, data: dict, target: Path, limit: int = 100, use_scope_query: bool = True
    ) -> list[dict]:
        self._unreachable("list_items")
        return []  # pragma: no cover - unreachable

    def list_fields(self, data: dict, target: Path, refresh: bool = False) -> list[dict]:
        self._unreachable("list_fields")
        return []  # pragma: no cover - unreachable

    def board_identity(self, data: dict, target: Path) -> dict:
        self._unreachable("board_identity")
        return {}  # pragma: no cover - unreachable

    def board_order(self, data: dict, target: Path) -> dict[str, int]:
        self._unreachable("board_order")
        return {}  # pragma: no cover - unreachable

    def set_status(self, data: dict, target: Path, item_ref: str, status: str) -> dict:
        self._unreachable("set_status")
        return {}  # pragma: no cover - unreachable

    def export_item(
        self, data: dict, target: Path, item_id: str, field_name: str, value: str
    ) -> None:
        self._unreachable("export_item")


register_provider(JiraBacklogProvider())
