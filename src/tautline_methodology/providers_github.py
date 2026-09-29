"""GitHub as one registered provider of the `backlog` and `issues` categories.

**The GitHub board and issues transports are gone** as of the 2026-08-28 process-bankruptcy
demolition. Board/milestone/goal sync -- `goal-advance` board writes, `backlog-provider-*`,
`backlog-board-*`, milestone progress markers, stakeholder-question plumbing -- was deleted with
the rest of the process engine, and every `cli.github_backlog_*` / `cli.github_issues_*` function
these verbs delegated to went with it.

Both providers stay REGISTERED, and that is the point of registering them here rather than
hardcoding an enum. An adapter that names `github-projects` or `github-issues` still validates:
membership, per-provider identity fields (`owner`, `projectNumber`, ...) and the secret-env format
checks are unaffected, so a literal credential in `apiTokenEnv` is still refused. What changed is
that neither provider claims a capability it cannot serve. Every verb is declared unavailable, so a
caller is refused BY NAME rather than reaching a transport that is not there -- the same shape the
Jira backlog provider has always had, and the shape the capability probe exists for.
"""

from __future__ import annotations

from pathlib import Path

from tautline_methodology.providers import PROVIDER_CATEGORIES, Provider, register_provider


class GitHubProjectsBacklogProvider(Provider):
    """GitHub Projects (ProjectV2) as the backlog board, declared with no verb available.

    `unavailable_verbs` is derived by SUBTRACTION from the category contract rather than listed by
    hand, so a verb added to the contract later cannot silently become "available" on a provider
    that cannot serve it. Restoring a verb means adding it to `_IMPLEMENTED` in the same commit
    that adds its body back.
    """

    provider_id = "github-projects"
    category = "backlog"
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


class GitHubIssuesProvider(Provider):
    """GitHub Issues as the work-item body a board item points at, declared with no verb available.

    Registered as its OWN category so an adopter may run one provider's board over another
    provider's issues. Nothing here may assume `backlog` and `issues` resolve to the same provider.
    """

    provider_id = "github-issues"
    category = "issues"
    _IMPLEMENTED: frozenset[str] = frozenset()
    unavailable_verbs = frozenset(PROVIDER_CATEGORIES["issues"]) - _IMPLEMENTED

    def _unreachable(self, verb: str) -> None:
        raise self.capability_exception(verb)

    def item_body(self, data: dict, target: Path, item: dict) -> tuple[str, str]:
        self._unreachable("item_body")
        return ("", "")  # pragma: no cover - unreachable

    def post_comment(
        self, data: dict, target: Path, item: dict, body: str, context: str
    ) -> str:
        self._unreachable("post_comment")
        return ""  # pragma: no cover - unreachable


register_provider(GitHubProjectsBacklogProvider())
register_provider(GitHubIssuesProvider())
