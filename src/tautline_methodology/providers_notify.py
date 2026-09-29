"""The ``notify`` category: the chat seam, and the no-op that makes it optional.

`cross-thesis-2` states the failure this closes: chat was wired in *as if universal*, with no
null/no-op default, so a fresh adopter who does not use Google Chat inherited an enum refusal on a
stack they never chose. Registering Google Chat as one provider among others and shipping a null
peer beside it makes "I have no chat tool" an expressible answer rather than a validation failure.

**The Google Chat transport is gone** as of the 2026-08-28 process-bankruptcy demolition. Every
publisher that posted through it -- release-update cards, iteration reviews, milestone updates,
product notes, deploy-ready updates -- was deleted with the rest of the process engine, and
`cli.post_google_chat_webhook` went with them. The provider stays REGISTERED so that an adapter
naming `google-chat-webhook` still validates (membership, identity fields and secret-env format
checks are unaffected) and so the id does not have to be re-minted if a delivery seam returns. What
changed is that it no longer claims a capability it cannot serve: `post` is declared unavailable,
exactly as the Jira backlog provider declares its verbs, so a caller is refused BY NAME instead of
reaching a transport that is not there.
"""

from __future__ import annotations

from tautline_methodology.providers import PROVIDER_CATEGORIES, Provider, register_provider


class GoogleChatWebhookProvider(Provider):
    """Google Chat, declared for the `notify` category with no verb currently available.

    `unavailable_verbs` is derived by SUBTRACTION from the category contract rather than listed by
    hand, so a verb added to the contract later cannot silently become "available" on a provider
    that cannot serve it. Restoring delivery means ADDING the verb to `_IMPLEMENTED` in the same
    commit that adds its body back.
    """

    provider_id = "google-chat-webhook"
    category = "notify"
    supports_card = True
    _IMPLEMENTED: frozenset[str] = frozenset()
    unavailable_verbs = frozenset(PROVIDER_CATEGORIES["notify"]) - _IMPLEMENTED

    def post(
        self,
        payload: dict,
        *,
        target: str = "",
        label: str = "",
        dry_run: bool = False,
        failure_label: str = "",
    ) -> dict:
        """`target` is this provider's endpoint -- a Google Chat webhook URL. The contract names it
        `target` rather than `webhook_url` so one provider's vocabulary is not baked into the
        signature every other provider must implement.

        Unreachable: `require` refuses first on every dispatch path. Raising rather than returning a
        plausible ``delivered: False`` is deliberate -- a caller that bypassed the seam must fail
        loudly, not read a refusal as a successful no-op.
        """
        self.require("post")
        raise self.capability_exception("post")  # pragma: no cover - unreachable


class NullNotifyProvider(Provider):
    """No I/O, no exception, and a result that says plainly that nothing was delivered.

    Deliberately **not** a silent success. The dominant defect class in this codebase is a control
    that reads as present while doing nothing, so this verb returns ``delivered: False`` with a
    reason rather than an empty success. The complementary half of that guarantee lives in the
    adapter validator: a block that is ``enabled: true`` and resolves here is a misconfiguration and
    refuses at load, so silence-on-purpose and silence-by-accident stay distinguishable.
    """

    provider_id = "none"
    category = "notify"
    supports_card = False
    is_null = True
    unavailable_verbs = frozenset({"post"})

    def post(
        self,
        payload: dict | None = None,
        *,
        target: str = "",
        label: str = "",
        dry_run: bool = False,
        failure_label: str = "",
    ) -> dict:
        return {
            "delivered": False,
            "provider": self.provider_id,
            "reason": "no notify provider configured",
            "label": label,
        }


register_provider(GoogleChatWebhookProvider())
register_provider(NullNotifyProvider())
