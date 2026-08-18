"""Response-guard detection leaves: pure text scanners over an assistant response plus the
response-guard marker constants they consult. The stateful guard handlers (response_guard,
response_guard_hook, ...) stay in bin/tautline; they reach lane/adapter/goal state and delegate
the pure scans here."""

from __future__ import annotations

import argparse
import json
import re
import sys

from .guards import (
    response_guard_context_scan_text,
    response_guard_monitor_scan_text,
    response_guard_policy_scan_text,
    text_contains_any,
)


RESPONSE_GUARD_PASSIVE_MONITOR_PHRASES = [
    "yielding until then",
    "will notify",
    "will be notified",
    "will report verdict",
    "monitor armed",
    "monitor watches",
    "monitor is running",
    "waiting on merge",
    "waiting on checks",
    "waiting for notification",
    "waiting for harness notification",
    "waiting for the harness notification",
    "waiting for completion",
    "waiting for the background command",
    "ci is processing",
    "checks are in progress",
    "still in progress",
    "deploy is underway",
    "review running",
    "review is running",
    "preflight still running",
    "preflight just started",
    "preflight is running",
    "preflight has started",
    "preflight run is in progress",
    "preflight underway",
    "preflight to complete",
    "final preflight underway",
    "will push as soon as",
    "r2 running",
    "r3 running",
    "quality gates are running",
    "wakeup in",
    "wake up in",
    "i'll check back",
    "i'll update when",
    "i'll resume when",
    "i'll continue when",
    "i'll be notified",
    "will resume when",
    "will continue when",
    "will signal completion",
    "will ping when done",
    "when it completes",
    "when this completes",
    "when that completes",
    "when this finishes",
    "when that finishes",
    "when codex finishes",
    "once it exits",
    "once it finishes",
    "once that's done",
    "after it's done",
    "after this completes",
    "after the review is done",
    "upon completion",
    "waiting for a result",
    "when the output arrives",
    "when the command completes",
    "when the background task completes",
    "when the background command completes",
    "i'll act when",
    "i'll handle this when",
    "i'll know when",
    "resuming once",
    "pick this up after",
    "process will notify",
    "notify on eof",
    "harness will re-invoke",
    "completion notification",
    "harness notification",
]


RESPONSE_GUARD_AUTONOMOUS_YIELD_MARKERS = [
    "schedulewakeup armed",
    "schedule wakeup armed",
    "schedulewakeup scheduled",
    "schedule wakeup scheduled",
    "next heartbeat",
    "next tick",
    "heartbeat at",
    "heartbeat due",
    "recheck in",
    "backing off",
    "autonomous loop",
    "operator-blocked",
    "operator blocked",
    "quiet.",
    "standing by",
    "yielding.",
]


RESPONSE_GUARD_MONITOR_ALIVE_CLAIM_MARKERS = [
    "verified alive",
    "confirmed alive",
    "verified running",
    "confirmed running",
    "monitor is alive",
    "monitor still alive",
    "still alive",
    "process is alive",
    "process still alive",
    "pid is alive",
    "pid is live",
    "process exists",
    "process is live",
    "pgrep",
]


RESPONSE_GUARD_MONITOR_FRESHNESS_EVIDENCE_MARKERS = [
    "monitor-status",
    "monitor_status",
    "log grew",
    "log growth",
    "log-size",
    "log size",
    "grew by",
    "bytes since",
    "lines since",
    "new lines",
    "since prior poll",
    "since the prior poll",
    "since last poll",
    "since the last poll",
    "mtime",
    "last modified",
    "modified at",
    "modified ago",
    "seconds ago",
    "minutes ago",
    "freshness",
    "timestamp",
    "artifact growth",
]


RESPONSE_GUARD_FORWARD_MOTION_MARKERS = [
    "next poll due",
    "next poll",
    "will poll",
    "poll again",
    "next work already underway",
    "continuing with",
    "working on",
    "active poll",
    "parallel-safe",
    "non-conflicting work",
    "artifact written",
    "wrote ",
    "created ",
    "drafted ",
    "opened ",
    "committed ",
    "queued ",
    "pushed ",
    "synced ",
    "branch created",
    "source-of-truth plan",
    "plan-finalization-precheck",
]


# Item 82 / RCA 20260616T005348Z -- announce-and-stop. A final turn that ASSERTS an in-progress or
# next action instead of taking it. At the Stop seam the turn is ending by definition, so the
# announced action provably did not happen in this turn.
#
# The leading negative lookbehinds carry the "I'm not proceeding until <named blocker>" carve-out;
# a declared blocker is a legal exit, an announcement is not.
RESPONSE_GUARD_ANNOUNCE_AND_STOP_RE = re.compile(
    r"(?<!not )(?<!n't )\b(?:"
    r"i(?:'m| am)\s+(?:proceeding|starting|beginning|moving)\s+(?:now|next|on(?:to)?)"
    r"|proceeding\s+now"
    r"|next[,]?\s+i(?:'ll| will)"
    r"|i(?:'ll| will)\s+(?:now\s+)?(?:bring|start|begin|draft|write|implement|open|push|run"
    r"|kick off"
    r"|pick up|circle back|follow up|move on|come back)"
    r"|about\s+to\s+(?:start|begin|run|open|push)"
    r")\b"
)


RESPONSE_GUARD_STANDING_AUTH_OBJECTS = [
    "break-glass",
    "break glass",
    "admin merge",
    "--admin",
    "--no-verify",
    "force push",
    "bypass the gate",
    "standing approval",
]


RESPONSE_GUARD_STANDING_AUTH_ASK_RE = re.compile(
    r"\b(?:authorize|approve|green-?light|sign(?: |-)?off on|want me to|should i|shall i|"
    r"do you want|your call|need your (?:approval|authorization|sign-?off))\b"
)


RESPONSE_GUARD_NAMED_DEFAULT_NEGATION_RE = re.compile(
    r"\b(?:no|not|isn't|is not|without|lacks?|there is no)\s*$"
)


RESPONSE_GUARD_NAMED_DEFAULT_MARKERS = [
    "safe default",
    "defensible default",
    "the default is",
    "my recommendation is",
    "i recommend",
    "recommended path",
    "the safe path is",
]


# Item 82 / RCA 20260701T115759Z -- the objects a continue-vs-stop direction menu is built from.
# Tuple-free on purpose: this is a compiled regex, not a policy-phrase list, so it stays out of the
# policy-phrases SSOT without needing a tuple.
# TWO classes, not one list, and the split is what makes this usable at a blocking seam.
#
# Codex R2 P1: counting DISTINCT matched words across the flattened payload was wrong in both
# directions at once. "Continue now" / "Continue later" yields the single token `continue` and was
# MISSED -- a real direction menu. "proceed with staging" / "continue with production" yields two
# tokens and was BLOCKED -- a legitimate credential question. The number of distinct direction words
# is simply not the property that separates them.
#
# What does: a continue-vs-stop menu offers a way to CONTINUE and a way to STOP or DEFER. A domain
# choice offers two ways to do the same thing, differing by a domain noun. So the options must SPAN
# both classes.
QUESTION_GUARD_CONTINUE_OBJECT_RE = re.compile(
    r"\b(?:keep (?:going|grinding|working)|continue|resume|proceed|carry on|press on)\b"
)

QUESTION_GUARD_STOP_OBJECT_RE = re.compile(
    r"\b(?:next session|fresh session|new session|stop(?: here)?|pause|hold off|"
    r"wrap(?:ping)? up|call it (?:here|a day|a night)|pick (?:this |it )?up later|later|"
    r"defer|park (?:it|this)|merge (?:it |#?\d+ )?first|come back to it)\b"
)

QUESTION_GUARD_PROCEED_PHRASING_RE = re.compile(
    r"how (?:do|would) you want to proceed|what(?:'s| is) next|which (?:path|option)|"
    r"how should (?:i|we) proceed|where (?:do|should) (?:we|i) go from here"
)


RESPONSE_GUARD_STATUS_REPORT_NEXT_ACTION_MARKERS = [
    "needs drafting",
    "needs to be drafted",
    "needs planning",
    "needs to be planned",
    "needs a plan",
    "needs a spec",
    "needs an execution spec",
    "needs a source-of-truth",
    "missing plan",
    "missing spec",
    "per-pr spec missing",
    "requires planning",
    "requires a plan",
    "requires a spec",
    "ready for planning",
    "should be drafted",
    "should be planned",
]


RESPONSE_GUARD_TERMINAL_STOP_MARKERS = [
    "merged",
    "merge confirmed",
    "no open prs",
    "no open pr",
    "no work in flight",
    "no work-in-flight",
    "session summary",
    "final state",
    "closing state",
    "cleanup complete",
    "branch deleted",
    "worktree clean",
    "no in-flight work",
]


RESPONSE_GUARD_CONTINUITY_EVIDENCE_MARKERS = [
    ".ai-continuity/",
    "next_session.md",
    "prepare-continuity",
    "continuity handoff",
    "handoff file",
    "handoff path",
    "wrote continuity",
    "refreshed continuity",
]


RESPONSE_GUARD_SESSION_JOURNAL_EVIDENCE_MARKERS = [
    "prepare-session-journal",
    "publish-session-journal",
    "session journal",
    ".ai-runs/session-journals/",
    "journal pending",
    "journal published",
    "pending session journal",
]


RESPONSE_GUARD_OPT_IN_DIRECT_PHRASES = [
    "want me to",
    "do you want me to",
    "would you like me to",
    "deploy is yours to run",
    "production deploy is yours",
    "alpha deploy is yours",
    "i don't push to production",
    "i do not push to production",
    "deserves fresh context",
    "teed it up as the next action",
    "tee it up as the next action",
    "three forward paths",
    "forward paths:",
    "where would you like to go",
    "what would you like",
    "how do you want to proceed",
    "no work-in-flight",
    "awaiting direction",
    "good stopping point",
    "clean checkpoint",
    "obvious continuation path",
    "pausing here",
    "pause here",
    "stop here",
    "pick up next session",
    "pending your call",
    "pending your decision",
    "waiting on your call",
    "awaiting your call",
    "pick path",
    "choose path",
    "let me know if you want me to proceed",
    "if you'd like me to continue",
    "begin planning, or pause",
    "session has reached its productive limit",
    "productive limit",
    "end session / i'll /compact",
]


RESPONSE_GUARD_ANTHROPOMORPHIC_DEFERRAL_MARKERS = [
    "stop",
    "stopping",
    "pause",
    "pausing",
    "defer",
    "deferred",
    "resume",
    "continue later",
    "pick up",
    "next session",
    "fresh session",
    "new session",
    "later",
    "better to",
    "rather than",
    "not going to",
]


RESPONSE_GUARD_ANTHROPOMORPHIC_CAPACITY_RE = re.compile(
    r"(?<![\w-])(?:half[- ]asleep|too tired|i'?m tired|i am tired|fatigued|fatigue|fresh[- ]eyes|fresh in the morning|sleep(?:ing)? on it|tomorrow morning|it'?s late|it is late)(?![\w-])",
    re.I,
)


RESPONSE_GUARD_DECISION_MENU_CONTEXT_MARKERS = [
    "codex",
    "critical",
    "p1",
    "important finding",
    "review",
    "finding",
    "blocker",
    "blocked",
    "scope decision",
    "credential",
    "credentials",
    "served origin",
    "served-origin",
    "live crawl",
    "login crawl",
    "compact",
    "productive limit",
    "unverified",
    "push",
    "merge",
    "gate",
    "preflight",
]


RESPONSE_GUARD_PLAN_CAP_CONTEXT_MARKERS = [
    "2-round cap",
    "round cap",
    "round 2",
    "r2",
    "r3",
    "convergence",
    "non-converging",
    "plan-finalization gate",
    "source-of-truth plans",
    "split the work into smaller",
    "split into smaller",
    "unresolved critical",
    "unresolved p1",
]


RESPONSE_GUARD_WRONG_MERGE_QUEUE_SIGNAL_MARKERS = [
    "estimatedtimetomerge",
    "mergequeueentry",
    "awaiting_checks",
]


RESPONSE_GUARD_WRONG_MERGE_QUEUE_CONTEXT_MARKERS = [
    "still reports",
    "reports awaiting_checks",
    "wakeup",
    "wake up",
    "wait",
    "waiting",
    "poll",
    "polling",
    "reschedule",
    "rescheduling",
    "eta",
    "estimated time",
    "progress",
]


RESPONSE_GUARD_WRONG_MERGE_QUEUE_ACTIVE_CONTEXT_MARKERS = [
    "still reports",
    "reports awaiting_checks",
    "wakeup",
    "wake up",
    "wait",
    "waiting",
    "poll",
    "polling",
    "reschedule",
    "rescheduling",
]


RESPONSE_GUARD_WRONG_MERGE_QUEUE_POLICY_MARKERS = [
    "do not use",
    "never treat",
    "wrong merge-queue signal",
    "forbidden",
]


RESPONSE_GUARD_OPT_IN_ACTION_VERBS = [
    "start",
    "begin",
    "run",
    "execute",
    "implement",
    "proceed",
    "continue",
    "kill",
    "retry",
    "wait",
    "pause",
    "stop",
    "open",
    "commit",
    "push",
    "merge",
    "review",
    "write",
    "create",
    "draft",
    "plan",
    "prepare",
    "queue",
    "fix",
    "publish",
    "deploy",
    "release",
    "submit",
    "switch",
    "move",
    "trigger",
    "go",
    "get",
    "do",
]


RESPONSE_GUARD_DISCUSSION_FORBIDDEN_ACTION_VERBS = [
    "start",
    "begin",
    "run",
    "execute",
    "implement",
    "proceed",
    "continue",
    "kill",
    "retry",
    "wait",
    "pause",
    "stop",
    "open",
    "commit",
    "push",
    "merge",
    "review",
    "write",
    "create",
    "draft",
    "plan",
    "prepare",
    "queue",
    "fix",
    "publish",
    "deploy",
    "release",
    "submit",
    "switch",
    "move",
    "trigger",
    "build",
    "scaffold",
]


RESPONSE_GUARD_LIVE_GOAL_SESSION_MARKERS = [
    "goal not yet met",
    "goal met",
    "goal achieved",
    "goal complete",
    "goal still in progress",
    "goal evaluator",
    "claude /goal condition is active",
]


RESPONSE_GUARD_ASSISTANT_DISCUSSION_FRAMING_MARKERS = [
    "the user wants to clarify",
    "the user wants to chat",
    "the user wants to discuss",
    "the user wants to talk",
    "the user wants to think",
    "you want to clarify",
    "you want to chat",
    "you want to discuss",
    "you want to talk",
]


RESPONSE_GUARD_DISCUSSION_YIELD_MARKERS = [
    "what would you like to clarify",
    "what would you like to add",
    "tell me what's on your mind",
    "tell me what is on your mind",
    "i'm listening",
    "i am listening",
    "once i understand your thinking",
    "raise something the questions missed",
]


RESPONSE_GUARD_CONTEXT_PRESSURE_MARKERS = [
    "context exhaustion",
    "context ceiling",
    "context window",
    "context limit",
    "context pressure",
    "conversation limit",
    "conversation length",
    "conversation window",
    "working memory",
    "low-context",
    "low context",
    "remaining context",
    "fresh context",
    "compact/restart",
    "compaction",
    "compact",
    "out of room",
    "out of space",
    "rotate-mandatory",
    "context-rotation-check",
    "rotate-now",
    "95%",
]


RESPONSE_GUARD_CONTEXT_STOP_MARKERS = [
    "cannot continue",
    "can't continue",
    "cannot complete in this session",
    "can't complete in this session",
    "cannot finish",
    "can't finish",
    "not going to start",
    "required to continue",
    "requires a fresh context",
    "requires fresh context",
    "deserves fresh context",
    "compact/restart is required",
    "restart is required",
    "compact is required",
    "fresh session",
    "new session",
    "resume from",
    "resume after",
    "next session",
    "handing off",
    "teed it up as the next action",
    "tee it up as the next action",
    "cannot keep enough state",
    "can't keep enough state",
    "stopping point",
    "stop here",
    "i'm going to stop here",
    "i am going to stop here",
    "i'll stop here",
    "i will stop here",
    "stopping here",
    "stopping now",
    "stopping work",
    "pausing here",
    "wrapping up here",
    "next-poll: none",
    "next poll: none",
    "no background process running",
    "productive limit",
    "reached its productive limit",
    "session has reached its productive limit",
]


RESPONSE_GUARD_CONTEXT_SOFT_THRESHOLD_PERCENT = 60


RESPONSE_GUARD_CONTEXT_PRESSURE_WORD_MARKERS = [
    marker for marker in RESPONSE_GUARD_CONTEXT_PRESSURE_MARKERS if not marker.rstrip("%").isdigit()
]


RESPONSE_GUARD_CONTEXT_PERCENT_ANCHORS = (
    "context",
    "conversation window",
    "conversation length",
    "working memory",
)


RESPONSE_GUARD_CONTEXT_DEFERRAL_MARKERS = [
    "defer",
    "deferring",
    "deferred",
    "postpone",
    "postponing",
    "postponed",
    "until later",
    "for later",
    "pick this up later",
    "pick it up later",
    "pick up later",
    "leave for later",
    "leave it for later",
    "follow-up later",
    "next pass",
    "set aside",
    "hand off",
    "handing off",
    "handoff",
]


RESPONSE_GUARD_CONTEXT_UNMEASURED_ESCAPE_MARKERS = [
    "does not expose",
    "doesn't expose",
    "not exposed",
    "percent not visible",
    "percentage not visible",
    "no visible context percent",
    "no visible context percentage",
    "context percent unavailable",
    "context percentage unavailable",
    "host does not show",
    "host doesn't show",
]


RESPONSE_GUARD_CONTEXT_PERCENT_ESTIMATE_MARKERS = [
    "roughly",
    "about",
    "around",
    "approximately",
    "~",
    "i estimate",
    "i'd estimate",
    "probably",
    "probably around",
    "i guess",
    "i'd guess",
    "my guess",
    "seems like",
    "feels like",
    "somewhere near",
    "close to",
    "ballpark",
    "maybe",
]


RESPONSE_GUARD_CONTEXT_PERCENT_HOST_SOURCE_MARKERS = [
    "host counter",
    "host reports",
    "host-reported",
    "host reported",
    "reported by the host",
    "host shows",
    "host context percent",
    "context meter",
    "context counter",
    "measured context",
    "context measured",
    "(measured)",
    "status line shows",
    "status line reports",
    "host status line",
]


RESPONSE_GUARD_CONTEXT_RESUME_MARKERS = [
    "resuming the goal",
    "resume the goal",
    "resuming the active goal",
    "resume the active goal",
    "resuming the same goal",
    "resume the same goal",
    "resume the same active goal",
    "and resuming",
    "then resuming",
    "then resume",
    "resume after compaction",
    "resuming after compaction",
    "continuing the goal",
    "continue the goal",
]


RESPONSE_GUARD_CONTEXT_DEFER_TO_LATER_MARKERS = [
    "until later",
    "for later",
    "pick this up later",
    "pick it up later",
    "pick up later",
    "leave for later",
    "leave it for later",
    "follow-up later",
    "next pass",
]


RESPONSE_GUARD_MEDIA_DEFERRAL_MARKERS = [
    "i don't do videos",
    "i do not do videos",
    "i can't do videos",
    "i cannot do videos",
    "we don't do videos",
    "we do not do videos",
    "doesn't do videos",
    "does not do videos",
    "don't do video",
    "do not do video",
    "can't do video",
    "cannot do video",
    "outward-facing media-production step",
    "outward-facing media production step",
    "media-production step",
    "media production step",
    "outward-facing artifacts",
]


RESPONSE_GUARD_ITERATION_REVIEW_MEDIA_CONTEXT_MARKERS = [
    "iteration review",
    "goal review",
    "recap video",
    "rendered video",
    "video",
    "poster",
    "s3",
    "cloudfront",
    "google chat",
]


RESPONSE_GUARD_CONTEXT_HUMAN_PROMPT_MARKERS = [
    "only you can trigger",
    "only you can run",
    "only you can invoke",
    "you can trigger",
    "you can run /compact",
    "you can invoke /compact",
    "compact me",
    "/compact me",
    "if you want /compact",
    "if you want, /compact",
    "if you want to compact",
    "next move is yours",
    "start a fresh/compacted session",
    "or /goal clear",
    "goal clear to pause",
    "what would you like",
    "how do you want to proceed",
    "tell me to keep going",
    "want me to keep going",
    "should i keep going",
    "keep going?",
]


RESPONSE_GUARD_CONTEXT_ROTATION_ACTION_MARKERS = [
    "running /compact",
    "running compact",
    "run /compact",
    "run compact",
    "issuing /compact",
    "issuing compact",
    "invoke /compact",
    "invoke compact",
    "invoking /compact",
    "invoking compact",
    "compact now",
    "compacting now",
    "context rotation underway",
    "rotation underway",
    "resume the active goal after compaction",
    "next work already underway",
]


RESPONSE_GUARD_CONTEXT_ROTATION_FALLBACK_MARKERS = [
    "mandatory context rotation boundary",
    "host cannot invoke /compact from this agent turn",
    "cannot invoke /compact from this agent turn",
    "cannot run /compact from this agent turn",
    "host slash command is unavailable from this agent turn",
    "exact fresh-session startup action",
    "exact next startup action",
    "resume the active goal after startup gates",
    "resume the same active goal after startup gates",
]


RESPONSE_GUARD_CONTEXT_NEGATIVE_ACTION_MARKERS = [
    "cannot invoke /compact",
    "cannot invoke `/compact`",
    "cannot compact from inside this turn",
    "cannot compact inside this turn",
    "cannot run /compact",
    "cannot run `/compact`",
    "can't invoke /compact",
    "can't invoke `/compact`",
    "can't compact from inside this turn",
    "can't compact inside this turn",
    "can't run /compact",
    "can't run `/compact`",
    "i can't compact",
    "i cannot compact",
    "unable to invoke /compact",
    "unable to invoke `/compact`",
    "unable to compact from inside this turn",
    "unable to compact inside this turn",
    "unable to run /compact",
    "unable to run `/compact`",
]


RESPONSE_GUARD_CONTEXT_ROTATION_ACTION_RE = re.compile(
    r"\b(?:run|running|invoke|invoking|issue|issuing|execute|executing|call|calling|start|starting)\s+`?/(?:compact|clear)`?\b",
    re.I,
)


def hook_decision(reason: str) -> None:
    print(json.dumps({"decision": "block", "reason": reason}, indent=2))


def hook_additional_context(event_name: str, context: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event_name,
                    "additionalContext": context,
                }
            },
            indent=2,
        )
    )


def response_is_rca_shaped(text: str) -> bool:
    lower = text.lower()
    if "# rca" in lower or "# methodology regression rca" in lower:
        return True
    if re.search(r"(^|\n)\s*(rca|root cause)\s*[:\-]", lower):
        return True
    if "rule violated" in lower and ("what i did wrong" in lower or "root cause" in lower or "why i" in lower):
        return True
    headings = ["## incident summary", "## root cause", "## violated rule", "## fix proposal"]
    return sum(1 for heading in headings if heading in lower) >= 2


def response_has_forbidden_opt_in(text: str, *, human_discussion_request: bool = False) -> bool:
    line_scan = re.sub(r"```.*?```", " ", text, flags=re.S)
    line_scan = re.sub(r"`[^`\n]*`", " ", line_scan).lower()
    for line in line_scan.splitlines():
        if line.lstrip().startswith(">"):
            continue
        if re.search(r"^\s*say\s+['\"]?keep going['\"]?\b", line):
            return True
    scan_text = response_guard_policy_scan_text(text)
    action_verbs = "|".join(re.escape(verb) for verb in RESPONSE_GUARD_OPT_IN_ACTION_VERBS)
    discussion_action_verbs = "|".join(re.escape(verb) for verb in RESPONSE_GUARD_DISCUSSION_FORBIDDEN_ACTION_VERBS)
    has_discussion_permission_menu = bool(
        re.search(r"\bpath\s*1\b", scan_text) and re.search(r"\bpath\s*[23]\b", scan_text)
        or re.search(r"\boption\s*1\b", scan_text) and re.search(r"\boption\s*[23]\b", scan_text)
        or re.search(r"\(\s*a\s*\)", scan_text) and re.search(r"\(\s*b\s*\)", scan_text)
        or text_contains_any(scan_text, ["which option", "which path", "which path should", "which option should"])
        or re.search(rf"\b(?:want|do you want|would you like)\s+me\s+to\s+(?:{discussion_action_verbs})\b", scan_text)
        or re.search(rf"\b(?:should|shall|can|may)\s+(?:i|we)\s+(?:{discussion_action_verbs})\b", scan_text)
    )
    has_numbered_menu = bool(
        re.search(r"(?m)^\s*1[.)]\s+\S", line_scan) and re.search(r"(?m)^\s*[23][.)]\s+\S", line_scan)
    )
    has_unverified_delivery_offer = bool(
        re.search(
            r"\b(?:ship|push|merge|deploy|release|write|implement)\b.{0,120}\bunverified(?:-locally)?\b",
            scan_text,
        )
        or re.search(
            r"\bunverified(?:-locally)?\b.{0,120}\b(?:ship|push|merge|deploy|release|write|implement)\b",
            scan_text,
        )
    )
    if has_unverified_delivery_offer:
        return True
    if has_numbered_menu and text_contains_any(
        scan_text,
        RESPONSE_GUARD_DECISION_MENU_CONTEXT_MARKERS
        + RESPONSE_GUARD_PLAN_CAP_CONTEXT_MARKERS
        + RESPONSE_GUARD_CONTEXT_PRESSURE_MARKERS
        + RESPONSE_GUARD_CONTEXT_STOP_MARKERS,
    ):
        return True
    if text_contains_any(scan_text, RESPONSE_GUARD_OPT_IN_DIRECT_PHRASES):
        if human_discussion_request:
            discussion_safe = (
                text_contains_any(scan_text, RESPONSE_GUARD_DISCUSSION_YIELD_MARKERS)
                and not has_discussion_permission_menu
                and not has_numbered_menu
            )
            if discussion_safe:
                return False
        return True
    if re.search(r"\bpath\s*1\b", scan_text) and re.search(r"\bpath\s*[23]\b", scan_text):
        if text_contains_any(scan_text, RESPONSE_GUARD_DECISION_MENU_CONTEXT_MARKERS):
            return True
    if re.search(r"\boption\s*1\b", scan_text) and re.search(r"\boption\s*[23]\b", scan_text):
        if text_contains_any(scan_text, RESPONSE_GUARD_DECISION_MENU_CONTEXT_MARKERS + RESPONSE_GUARD_PLAN_CAP_CONTEXT_MARKERS):
            return True
    if text_contains_any(scan_text, ["which option", "which path"]):
        if text_contains_any(scan_text, RESPONSE_GUARD_DECISION_MENU_CONTEXT_MARKERS + RESPONSE_GUARD_PLAN_CAP_CONTEXT_MARKERS):
            return True
    if re.search(r"\(\s*a\s*\)", scan_text) and re.search(r"\(\s*b\s*\)", scan_text):
        if text_contains_any(scan_text, RESPONSE_GUARD_DECISION_MENU_CONTEXT_MARKERS + RESPONSE_GUARD_PLAN_CAP_CONTEXT_MARKERS):
            return True
    if re.search(r"\bwhich\?\s*$", scan_text.strip()) and text_contains_any(scan_text, RESPONSE_GUARD_PLAN_CAP_CONTEXT_MARKERS):
        return True
    if re.search(rf"\b(?:should|shall)\s+i\s+(?:{action_verbs})\b", scan_text):
        return True
    return False


def response_has_anthropomorphic_capacity_deferral(text: str) -> bool:
    scan_text = response_guard_policy_scan_text(text)
    if not RESPONSE_GUARD_ANTHROPOMORPHIC_CAPACITY_RE.search(scan_text):
        return False
    if text_contains_any(scan_text, RESPONSE_GUARD_ANTHROPOMORPHIC_DEFERRAL_MARKERS):
        return True
    return bool(
        re.search(
            r"\b(?:i'?m|i am|i was|we are|we're|this session is|the session is)\s+(?:too\s+)?(?:tired|fatigued|half[- ]asleep)\b",
            scan_text,
        )
    )


def response_looks_like_human_discussion_framing(text: str) -> bool:
    scan_text = response_guard_policy_scan_text(text)
    return (
        text_contains_any(scan_text, RESPONSE_GUARD_ASSISTANT_DISCUSSION_FRAMING_MARKERS)
        and text_contains_any(scan_text, RESPONSE_GUARD_DISCUSSION_YIELD_MARKERS)
    )


def response_has_status_report_as_stop(text: str) -> bool:
    scan_text = response_guard_policy_scan_text(text)
    has_next_action_gap = text_contains_any(scan_text, RESPONSE_GUARD_STATUS_REPORT_NEXT_ACTION_MARKERS) or bool(
        re.search(r"\bneeds\b.{0,100}\b(?:draft|drafting|plan|planning|spec|source-of-truth)\b", scan_text)
        or re.search(r"\b(?:missing|lacks?)\b.{0,100}\b(?:plan|planning|spec|execution spec|source-of-truth)\b", scan_text)
    )
    if not has_next_action_gap:
        return False
    if text_contains_any(scan_text, RESPONSE_GUARD_FORWARD_MOTION_MARKERS):
        return False
    return True


def response_has_announce_and_stop(text: str) -> bool:
    """Final text asserting an in-progress or next action. At the Stop seam this is structurally
    announce-and-stop: the turn is ending, so by definition no tool call toward the announced
    action follows (RCA 20260616T005348Z).

    Carve-outs: (1) forward-motion evidence AFTER the last announcement, and (2) a well-formed
    autonomous yield, which names its own next retry/action by contract.

    The position gate is load-bearing. The incident shape is a summary of COMPLETED prior work
    followed by an unexecuted announcement, and such summaries are full of forward-motion markers
    (`committed `, `pushed `, `wrote `). A whole-response marker scan would silence the detector on
    the exact class it exists to catch. Evidence of prior work is not evidence of motion toward the
    announced action, so only text after the final announce match counts.

    Residual gap, documented and not hidden: the detector cannot verify that the trailing evidence
    corresponds to the ANNOUNCED object, so "I'm proceeding now -- committed abc123" passes even
    when `abc123` predates the turn. Correlating them needs tool-call provenance the Stop hook does
    not have. This is a deliberate false-negative floor, chosen over false positives at a
    default-blocking tier.
    """
    policy_scan = response_guard_policy_scan_text(text)
    if not RESPONSE_GUARD_ANNOUNCE_AND_STOP_RE.search(policy_scan):
        return False
    if response_looks_like_autonomous_yield(text):
        return False
    # Detection AND location must come from ONE string, and it must be the QUOTE-STRIPPED one.
    #
    # Codex R2 P2: an earlier version detected on the policy scan but located the last match on the
    # monitor scan, which keeps blockquotes. So "I'm proceeding now. I wrote the plan.\n> Next I'll
    # run tests." chose the QUOTED announcement as the final match, and the tail after it held no
    # evidence -- so the check fired on a turn that had actually done the work. Quoting a guard
    # refusal or a peer's message is routine in these lanes, and the wave-3 switch would have turned
    # that into a blocked stop.
    matches = list(RESPONSE_GUARD_ANNOUNCE_AND_STOP_RE.finditer(policy_scan))
    if not matches:
        return True  # detected above but unlocatable: no addressable evidence tail
    tail = policy_scan[matches[-1].end() :]
    return not text_contains_any(tail, RESPONSE_GUARD_FORWARD_MOTION_MARKERS)


def response_asks_standing_authorization(text: str) -> bool:
    """An ask-shaped sentence whose object is a break-glass / admin-merge class action.

    Canonical rule: standing approval recorded in a source-of-truth artifact counts once conditions
    match; do not re-ask because the action is break-glass or admin merge.

    Mechanism is `phrase` and the tier is the STANDARD (advisory) one, deliberately: this predicate
    cannot see whether a standing approval actually exists, so a hard block would deny a legitimate
    FIRST-TIME break-glass blocker question. The proximity window (ask verb -> object within 160
    characters) is the false-positive control.
    """
    scan = response_guard_policy_scan_text(text)
    if not text_contains_any(scan, RESPONSE_GUARD_STANDING_AUTH_OBJECTS):
        return False
    for match in RESPONSE_GUARD_STANDING_AUTH_ASK_RE.finditer(scan):
        window = scan[match.start() : match.start() + 160]
        if text_contains_any(window, RESPONSE_GUARD_STANDING_AUTH_OBJECTS):
            return True
    return False


def response_has_self_contradicting_question(turn_text: str, question_text: str) -> bool:
    """The turn's own prose names a safe/defensible default or a recommendation, and the same turn
    asks the operator anyway (RCA 20260616T132017Z: "the trivial-fix exemption is the defensible
    safe default" followed by a three-option AskUserQuestion menu). Recovery: take the named
    default.

    ADVISORY wherever it is wired. The markers are loose by construction -- "i recommend" matches
    "I recommend Redis for the cache." next to a genuine credential question -- which is exactly
    why this predicate never reaches a hard-block seam.
    """
    if not question_text.strip():
        return False
    scan = response_guard_policy_scan_text(turn_text)
    for marker in RESPONSE_GUARD_NAMED_DEFAULT_MARKERS:
        start = scan.find(marker)
        while start != -1:
            # "No safe default exists -- every path changes approved scope" is the HONEST turn: it
            # says a default could not be named, which is the opposite of naming one and then asking
            # anyway. A bare substring test fires on it and would flag exactly the turn that got the
            # judgement right. The window is short on purpose -- a negation further away is usually
            # about something else.
            preceding = scan[max(0, start - 14) : start]
            if not RESPONSE_GUARD_NAMED_DEFAULT_NEGATION_RE.search(preceding):
                return True
            start = scan.find(marker, start + 1)
    return False


def question_is_continue_vs_stop_menu(question_text: str) -> bool:
    """True when the text spans BOTH a continue object and a stop/defer object.

    Kept as a text-level predicate for the Stop-seam defence-in-depth path, where only flattened
    text is available. The PreToolUse hook uses `question_payload_is_direction_menu` instead, which
    reads the structured options and is strictly more precise -- option boundaries are exactly what
    flattening destroys.
    """
    scan = question_text.lower()
    has_continue = bool(QUESTION_GUARD_CONTINUE_OBJECT_RE.search(scan))
    has_stop = bool(QUESTION_GUARD_STOP_OBJECT_RE.search(scan))
    if has_continue and has_stop:
        return True
    return (has_continue or has_stop) and bool(QUESTION_GUARD_PROCEED_PHRASING_RE.search(scan))


def question_payload_option_texts(value: object) -> list[str]:
    """Every option's own text, kept SEPARATE -- one string per option.

    Flattening the payload into one blob is precisely what destroyed the option boundaries the menu
    rule needs.
    """
    texts: list[str] = []

    def walk_question(question: object) -> None:
        if not isinstance(question, dict):
            return
        for option in question.get("options") or []:
            if isinstance(option, str):
                texts.append(option)
            elif isinstance(option, dict):
                parts = [str(option.get(key) or "") for key in ("label", "description")]
                joined = " ".join(part for part in parts if part)
                if joined:
                    texts.append(joined)

    if isinstance(value, dict):
        questions = value.get("questions")
        if isinstance(questions, list):
            for question in questions:
                walk_question(question)
        else:
            walk_question(value)
    elif isinstance(value, list):
        for question in value:
            walk_question(question)
    return texts


def question_payload_question_texts(value: object) -> list[str]:
    """The question/header text, separate from the options."""
    texts: list[str] = []
    if isinstance(value, dict):
        questions = value.get("questions")
        candidates = questions if isinstance(questions, list) else [value]
    elif isinstance(value, list):
        candidates = value
    else:
        return texts
    for question in candidates:
        if isinstance(question, dict):
            for key in ("question", "header"):
                text = str(question.get(key) or "")
                if text:
                    texts.append(text)
    return texts


def question_payload_is_direction_menu(tool_input: object) -> bool:
    """True when the structured OPTIONS form a continue-vs-stop menu.

    The rule: the option set must SPAN both classes -- somewhere to continue and somewhere to stop
    or defer. Two options that both continue, differing only by a domain noun ("proceed with
    staging" / "continue with production"), are a domain choice, and denying that shape denies the
    exact true-blocker question the canonical rules tell an agent to ask.

    One direction option plus explicit how-do-you-want-to-proceed phrasing also counts: a lone
    "keep going" option under that question is the same menu with its alternative left implicit.
    """
    options = question_payload_option_texts(tool_input)
    if not options:
        return False
    continues = sum(1 for text in options if QUESTION_GUARD_CONTINUE_OBJECT_RE.search(text.lower()))
    stops = sum(1 for text in options if QUESTION_GUARD_STOP_OBJECT_RE.search(text.lower()))
    if continues and stops:
        return True
    if not (continues or stops):
        return False
    prompt = " ".join(question_payload_question_texts(tool_input)).lower()
    return bool(QUESTION_GUARD_PROCEED_PHRASING_RE.search(prompt))


def response_is_terminal_stop_context(text: str) -> bool:
    scan_text = response_guard_policy_scan_text(text)
    marker_count = sum(1 for marker in RESPONSE_GUARD_TERMINAL_STOP_MARKERS if marker in scan_text)
    return marker_count >= 2


def response_has_terminal_continuity_omission(text: str) -> bool:
    scan_text = response_guard_policy_scan_text(text)
    if not response_is_terminal_stop_context(text):
        return False
    has_continuity = text_contains_any(scan_text, RESPONSE_GUARD_CONTINUITY_EVIDENCE_MARKERS)
    has_journal = text_contains_any(scan_text, RESPONSE_GUARD_SESSION_JOURNAL_EVIDENCE_MARKERS)
    return not (has_continuity and has_journal)


def response_has_wrong_merge_queue_signal(text: str) -> bool:
    scan_text = response_guard_policy_scan_text(text)
    raw_text = text.lower()
    if not text_contains_any(scan_text, RESPONSE_GUARD_WRONG_MERGE_QUEUE_SIGNAL_MARKERS):
        return False
    if not text_contains_any(scan_text, ["merge", "queue", "pr "]):
        return False
    if text_contains_any(raw_text, ["gh pr view", "--json state", " pr state", "pullrequest.state", "pull request state"]):
        return False
    if text_contains_any(raw_text, RESPONSE_GUARD_WRONG_MERGE_QUEUE_POLICY_MARKERS) and not text_contains_any(
        scan_text, RESPONSE_GUARD_WRONG_MERGE_QUEUE_ACTIVE_CONTEXT_MARKERS
    ):
        return False
    if not text_contains_any(scan_text, RESPONSE_GUARD_WRONG_MERGE_QUEUE_CONTEXT_MARKERS):
        return False
    return True


def response_has_unverified_monitor_alive_claim(scan_text: str) -> bool:
    """A 'monitor/process is alive' assertion with no freshness evidence. Process liveness
    (pgrep/PID exists) does not prove progress: a wedged process is still alive. The claim
    must cite monitor-status output, a log-size delta/growth since the prior poll, or a
    freshness timestamp comparison."""
    if not text_contains_any(scan_text, RESPONSE_GUARD_MONITOR_ALIVE_CLAIM_MARKERS):
        return False
    return not text_contains_any(scan_text, RESPONSE_GUARD_MONITOR_FRESHNESS_EVIDENCE_MARKERS)


def response_has_rotation_action_or_fallback(scan_text: str) -> bool:
    """True when the response is actually rotating: an un-negated /compact-style rotation action,
    or the host-fallback path (continuity + journal + exact fresh-session startup action). A
    response that is rotating is not deferring, so the deferral checks must not flag it."""
    has_negative_compaction = text_contains_any(scan_text, RESPONSE_GUARD_CONTEXT_NEGATIVE_ACTION_MARKERS)
    # A negated rotation claim ("cannot run /compact") must NOT count as rotating. The negation
    # guard applies to the marker list too, not only the regex, because "cannot run /compact"
    # contains the positive "run /compact" marker as a substring (Codex P1).
    has_rotation_action = (
        text_contains_any(scan_text, RESPONSE_GUARD_CONTEXT_ROTATION_ACTION_MARKERS)
        or bool(RESPONSE_GUARD_CONTEXT_ROTATION_ACTION_RE.search(scan_text))
    ) and not has_negative_compaction
    has_continuity = text_contains_any(scan_text, RESPONSE_GUARD_CONTINUITY_EVIDENCE_MARKERS)
    has_journal = text_contains_any(scan_text, RESPONSE_GUARD_SESSION_JOURNAL_EVIDENCE_MARKERS)
    has_host_fallback = (
        has_continuity
        and has_journal
        and text_contains_any(scan_text, RESPONSE_GUARD_CONTEXT_ROTATION_FALLBACK_MARKERS)
    )
    return has_rotation_action or has_host_fallback


def response_has_host_fallback_rotation(scan_text: str) -> bool:
    """The host-fallback rotation path: continuity + session-journal evidence + a fresh-session
    fallback marker. This path inherently resumes (it states the exact fresh-session startup
    action), so it counts as a genuine rotation+resume even without a /compact action."""
    return (
        text_contains_any(scan_text, RESPONSE_GUARD_CONTINUITY_EVIDENCE_MARKERS)
        and text_contains_any(scan_text, RESPONSE_GUARD_SESSION_JOURNAL_EVIDENCE_MARKERS)
        and text_contains_any(scan_text, RESPONSE_GUARD_CONTEXT_ROTATION_FALLBACK_MARKERS)
    )


def response_has_context_rotation_stop(text: str) -> bool:
    scan_text = response_guard_context_scan_text(text)
    has_pressure = text_contains_any(scan_text, RESPONSE_GUARD_CONTEXT_PRESSURE_MARKERS) or bool(
        re.search(r"\b(?:[6-9]\d|100)\s*%(?!\w).{0,120}\bcontext\b", scan_text)
        or re.search(r"\bcontext\b.{0,120}\b(?:[6-9]\d|100)\s*%(?!\w)", scan_text)
    )
    if not has_pressure:
        return False
    if text_contains_any(scan_text, RESPONSE_GUARD_CONTEXT_HUMAN_PROMPT_MARKERS):
        return True
    has_stop = text_contains_any(scan_text, RESPONSE_GUARD_CONTEXT_STOP_MARKERS) or bool(
        re.search(r"\b(?:hard|physical|true)\s+blocker\b.{0,160}\bcontext\b", scan_text)
        or re.search(r"\bcontext\b.{0,160}\b(?:hard|physical|true)\s+blocker\b", scan_text)
    )
    if not has_stop:
        return False
    has_continuity = text_contains_any(scan_text, RESPONSE_GUARD_CONTINUITY_EVIDENCE_MARKERS)
    has_journal = text_contains_any(scan_text, RESPONSE_GUARD_SESSION_JOURNAL_EVIDENCE_MARKERS)
    has_host_fallback = (
        has_continuity
        and has_journal
        and text_contains_any(scan_text, RESPONSE_GUARD_CONTEXT_ROTATION_FALLBACK_MARKERS)
    )
    has_negative_compaction = text_contains_any(scan_text, RESPONSE_GUARD_CONTEXT_NEGATIVE_ACTION_MARKERS)
    has_rotation_action = text_contains_any(scan_text, RESPONSE_GUARD_CONTEXT_ROTATION_ACTION_MARKERS) or (
        bool(RESPONSE_GUARD_CONTEXT_ROTATION_ACTION_RE.search(scan_text)) and not has_negative_compaction
    )
    if has_negative_compaction and not has_host_fallback:
        return True
    return not (has_rotation_action or has_host_fallback)


def response_percent_is_progress(scan_text: str, match: re.Match[str]) -> bool:
    """True when the percentage is TIGHTLY bound to a progress quantity ('80% complete',
    '80% of the goal', 'goal at 80%'), not the context level. Tight binding to the number
    keeps stop/deferral words elsewhere in the clause ('cannot complete', 'defer the task')
    from misclassifying a genuine context percentage."""
    after = scan_text[match.end() : match.end() + 30]
    before = scan_text[max(0, match.start() - 25) : match.start()]
    if re.match(r"\s*(?:complete|completed|done|finished|coverage|covered)\b", after):
        return True
    # "80% goal complete", "80% milestone done", "40% test coverage" — progress noun between
    # the number and the verb.
    if re.match(
        r"\s*(?:goal|milestone|tasks?|tests?|coverage|progress|backlog|build|review|features?)\b",
        after,
    ):
        return True
    if re.match(
        r"\s*of\s+(?:the\s+|my\s+|our\s+)?(?:goal|milestone|backlog|tests?|work|plan|tasks?|features?)\b",
        after,
    ):
        return True
    if re.search(
        r"\b(?:goal|milestone|tasks?|tests?|coverage|progress|backlog|build|review|features?)"
        r"\s+(?:is\s+|at\s+|now\s+|sits\s+at\s+)?$",
        before,
    ):
        return True
    return False


def response_context_percent_values(scan_text: str) -> list[int]:
    """Percentages that describe the CONTEXT level. A percentage counts only when a context
    word/alias is adjacent (either side) and it is not tightly bound to a progress quantity.
    So 'context at 28%', 'context window at 72%', '28% of the context', and 'conversation
    window at 78%' count; 'context exhaustion, 80% complete' and 'goal 80%' do not."""
    values: list[int] = []
    for match in re.finditer(r"(\d{1,3})\s*%", scan_text):
        if response_percent_is_progress(scan_text, match):
            continue
        before = scan_text[max(0, match.start() - 30) : match.start()]
        after = scan_text[match.end() : match.end() + 30]
        if any(anchor in before for anchor in RESPONSE_GUARD_CONTEXT_PERCENT_ANCHORS) or any(
            anchor in after for anchor in RESPONSE_GUARD_CONTEXT_PERCENT_ANCHORS
        ):
            values.append(int(match.group(1)))
    return values


def response_context_percent_is_estimated(scan_text: str, match: re.Match[str]) -> bool:
    """True when the percentage is a self-estimate, not a host measurement: a hedge marker
    ('roughly', 'about', '~', 'i estimate', ...) within the same ±30 window
    response_context_percent_values uses, OR a trailing '+'/'ish' hedge on the number itself
    ('88%+', '80%ish')."""
    before = scan_text[max(0, match.start() - 30) : match.start()]
    after = scan_text[match.end() : match.end() + 30]
    if any(marker in before or marker in after for marker in RESPONSE_GUARD_CONTEXT_PERCENT_ESTIMATE_MARKERS):
        return True
    # Trailing "+" or "ish"/"-ish" directly on the number is a hedge ("88%+", "80%-ish").
    return bool(re.match(r"\s*(?:\+|-?ish)", scan_text[match.end() : match.end() + 4]))


def response_context_percent_is_host_sourced(scan_text: str, match: re.Match[str]) -> bool:
    """True when an UN-NEGATED host-counter provenance marker ('host counter', 'context meter',
    '(measured)', ...) sits within ±40 chars of the percentage. This is the ONLY way a percent
    earns 'host-measured' status for the unprovenanced-stop gate; the window keeps provenance
    bound to the specific number, so far-away boilerplate cannot launder a fabricated figure.

    Negation-aware: a host marker immediately preceded (same clause) by a negator -- "no host
    counter is visible; 88%" -- does NOT count, so denying the host has a reading cannot read as
    host-sourced. At least one un-negated host-marker occurrence in the window is required.

    The window stays at ±40 (not widened): widening re-opens the decoy-laundering bypass where a
    parenthetical "(... host counter showed 20%)" launders an adjacent fabricated 88%. The
    hedge-override (host AND-NOT-estimated) is the real laundering defense, not the window size."""
    lo = max(0, match.start() - 40)
    hi = min(len(scan_text), match.end() + 40)
    for marker in RESPONSE_GUARD_CONTEXT_PERCENT_HOST_SOURCE_MARKERS:
        idx = scan_text.find(marker, lo, hi)
        while idx != -1:
            # Negation lookbehind reads from the full text at the marker's absolute position, NOT
            # the ±40 provenance window, so a negator is not truncated when a long anchor pushes
            # the marker to the window edge ("no actual host counter; context window at 88%").
            preceding = scan_text[max(0, idx - 24) : idx]
            negated = bool(
                RESPONSE_GUARD_AFFIRMATIVE_IMMEDIATE_NEGATOR_RE.search(preceding)
                or RESPONSE_GUARD_AFFIRMATIVE_PHRASE_NEGATOR_RE.search(preceding)
                or RESPONSE_GUARD_CONTEXT_HOST_NEGATOR_RE.search(preceding)
            )
            if not negated:
                return True
            idx = scan_text.find(marker, idx + 1, hi)
    return False


RESPONSE_GUARD_AFFIRMATIVE_IMMEDIATE_NEGATOR_RE = re.compile(
    r"\b(?:not|no|never|without|isn't|won't|aren't|will not|don't|am not|are not)\s*$"
)


RESPONSE_GUARD_CONTEXT_HOST_NEGATOR_RE = re.compile(
    r"\b(?:no|not|never|without|cannot|can't|isn't|aren't|won't|don't|doesn't|didn't|"
    r"lacks?|lacking|missing|absent|n't)\b[^.!?;]{0,24}$"
)


RESPONSE_GUARD_AFFIRMATIVE_PHRASE_NEGATOR_RE = re.compile(
    r"\b(?:not|never|don't|won't|isn't|aren't|am not|are not|will not|no)\s+"
    r"(?:going|planning|plan|gonna|about|intend|intending|meaning|trying|attempting|"
    r"starting|aiming)\b[^.!?;]*$"
)


def response_has_affirmative_stop_or_defer(scan_text: str) -> bool:
    """True when a stop/deferral marker appears UN-negated. Catches both immediate
    negators ('I am not deferring', 'no handoff; continuing now') and phrase-scoped ones
    ('not going to start a fresh session', 'not planning to hand off')."""
    for marker in RESPONSE_GUARD_CONTEXT_STOP_MARKERS + RESPONSE_GUARD_CONTEXT_DEFERRAL_MARKERS:
        idx = scan_text.find(marker)
        while idx != -1:
            preceding = scan_text[max(0, idx - 48) : idx]
            negated = bool(
                RESPONSE_GUARD_AFFIRMATIVE_IMMEDIATE_NEGATOR_RE.search(preceding)
                or RESPONSE_GUARD_AFFIRMATIVE_PHRASE_NEGATOR_RE.search(preceding)
            )
            if not negated:
                return True
            idx = scan_text.find(marker, idx + 1)
    return False


def response_has_unmeasured_context_deferral(text: str) -> bool:
    """A context-based stop/deferral of authorized work must cite a measured visible context
    percentage at or above the soft threshold. Fires when the response carries a context
    signal (a context-word pressure marker OR a percentage bound to the context level) AND
    frames an un-negated stop OR deferral, yet cites no context percentage, or any cited
    context percentage is below the soft threshold (so a high unrelated progress percentage
    cannot mask a low context claim, and a bare sub-threshold context percentage cannot slip
    through without pressure wording)."""
    scan_text = response_guard_context_scan_text(text)
    percents = response_context_percent_values(scan_text)
    has_context_signal = bool(percents) or text_contains_any(
        scan_text, RESPONSE_GUARD_CONTEXT_PRESSURE_WORD_MARKERS
    )
    if not has_context_signal:
        return False
    if not response_has_affirmative_stop_or_defer(scan_text):
        return False
    # A response that is actually rotating (running /compact or the host-fallback path) is not
    # deferring, even if its rotation language matches a stop marker ("resume after compaction").
    if response_has_rotation_action_or_fallback(scan_text):
        return False
    # Explicitly noting the host does not expose a percentage is an accepted escape.
    if text_contains_any(scan_text, RESPONSE_GUARD_CONTEXT_UNMEASURED_ESCAPE_MARKERS):
        return False
    if not percents:
        return True
    return any(percent < RESPONSE_GUARD_CONTEXT_SOFT_THRESHOLD_PERCENT for percent in percents)


def response_has_defer_mandatory_work_without_rotation(text: str) -> bool:
    """Even with a valid measured context percentage at or above the soft threshold,
    deferring or stopping authorized work WITHOUT executing a rotation+resume (or the
    host-fallback path) is handoff theater. Complements
    response_has_unmeasured_context_deferral (sub-threshold / no-number claims) and
    response_has_context_rotation_stop (stop markers plus pressure wording): this fires on
    a high, valid measurement paired with an un-negated stop/deferral and no rotation
    action."""
    scan_text = response_guard_context_scan_text(text)
    percents = response_context_percent_values(scan_text)
    if not any(percent >= RESPONSE_GUARD_CONTEXT_SOFT_THRESHOLD_PERCENT for percent in percents):
        return False
    if not response_has_affirmative_stop_or_defer(scan_text):
        return False
    return not response_has_rotation_action_or_fallback(scan_text)


RESPONSE_GUARD_ASKS_TO_KEEP_GOING_RE = re.compile(
    r"(?:tell me|let me know|your call|up to you|you decide|whether|"
    r"would you (?:like|prefer)|how (?:would|do) you)"
    r"\b[^.!?;]{0,40}\b"
    r"(?:keep going|keep working|continue|carry on|proceed|compact|rotate|stop|pause|wait)"
)


def response_asks_to_keep_going(scan_text: str) -> bool:
    """True when the response asks the operator whether to keep working on authorized work -- the
    headline RCA vector has no stop marker, only a permission ask. Matches any remaining precise
    HUMAN_PROMPT marker OR the open-class operator-asks-whether-to-keep-working regex, which
    REQUIRES a continuation/rotation object so a benign "let me know if you want to adjust scope"
    (no keep-going object) does not match."""
    if text_contains_any(scan_text, RESPONSE_GUARD_CONTEXT_HUMAN_PROMPT_MARKERS):
        return True
    return bool(RESPONSE_GUARD_ASKS_TO_KEEP_GOING_RE.search(scan_text))


def _response_context_stop_anchor_positions(scan_text: str) -> list[int]:
    """Character positions of un-negated stop/defer markers plus permission/keep-going-ask anchors
    -- the markers that signal authorized work is being stopped/handed off/deferred or that the
    operator is being asked whether to keep going. Provenance is bound to the percent nearest one
    of these, not globally, so a decoy host-sourced number elsewhere cannot launder a fabricated
    stop figure (RCA decoy bypass)."""
    positions: list[int] = []
    for marker in (
        RESPONSE_GUARD_CONTEXT_STOP_MARKERS
        + RESPONSE_GUARD_CONTEXT_DEFERRAL_MARKERS
    ):
        idx = scan_text.find(marker)
        while idx != -1:
            preceding = scan_text[max(0, idx - 48) : idx]
            negated = bool(
                RESPONSE_GUARD_AFFIRMATIVE_IMMEDIATE_NEGATOR_RE.search(preceding)
                or RESPONSE_GUARD_AFFIRMATIVE_PHRASE_NEGATOR_RE.search(preceding)
            )
            if not negated:
                positions.append(idx)
            idx = scan_text.find(marker, idx + 1)
    for asks in RESPONSE_GUARD_ASKS_TO_KEEP_GOING_RE.finditer(scan_text):
        positions.append(asks.start())
    for marker in RESPONSE_GUARD_CONTEXT_HUMAN_PROMPT_MARKERS:
        idx = scan_text.find(marker)
        while idx != -1:
            positions.append(idx)
            idx = scan_text.find(marker, idx + 1)
    return positions


def response_has_unprovenanced_context_stop(text: str) -> bool:
    """Block a stop/handoff/defer of authorized work whose only justification is a NON-host-sourced
    (estimated or bare) context percentage -- even if the response mentions /compact.

    RCA 20260615T181937Z: an agent fabricated "context at 88%+", paired it with a token /compact
    mention and a permission prompt ("tell me to keep going"), and stopped authorized work. The
    discriminator is PROVENANCE, not adjacency: an int next to "context" is not automatically a
    host measurement.

    Fires when, with a context signal present:
      1. authorized work is being stopped/deferred (un-negated stop/defer) OR the operator is being
         asked whether to keep going (a permission/human-prompt marker -- the headline vector has
         no stop marker); AND
      2. a context percent that is ESTIMATED-OR-BARE sits adjacent to one of those stop/permission
         markers (provenance is bound to the stop-adjacent percent, so a decoy host-sourced number
         elsewhere does not exonerate); AND
      3. the unmeasured-escape ("host does not expose a percent") is NOT present.

    Resume carve-out: a genuine in-turn rotation+resume (response_has_rotation_action_or_fallback)
    that does NOT ask permission and does NOT defer to LATER passes -- this keeps the bare
    /compact-resume fixture (503bf34) and the host-fallback handoff fixture green. The carve-out's
    deferral check is scoped to DEFER-TO-LATER temporal markers only, so the housekeeping word
    "handoff" does not defeat it."""
    scan_text = response_guard_context_scan_text(text)
    # Trigger: an un-negated stop/defer OR a permission/keep-going ask (open-class detector).
    has_stop_or_defer = response_has_affirmative_stop_or_defer(scan_text)
    has_human_prompt = response_asks_to_keep_going(scan_text)
    if not (has_stop_or_defer or has_human_prompt):
        return False
    # NOTE: a generic "host does not expose a percent" escape is NOT honored here -- a fabricated,
    # stop-adjacent percent must still block even when the response also claims the host has no
    # reading (Codex RCA). Genuine "no percent, continuing" cases pass because they carry no
    # stop-adjacent context percent and therefore never reach the block below.
    anchors = _response_context_stop_anchor_positions(scan_text)
    if not anchors:
        return False
    # Classify each context percent and check whether an estimated-or-bare one is stop-adjacent.
    stop_adjacent_unprovenanced = False
    for match in re.finditer(r"(\d{1,3})\s*%", scan_text):
        if response_percent_is_progress(scan_text, match):
            continue
        before = scan_text[max(0, match.start() - 30) : match.start()]
        after = scan_text[match.end() : match.end() + 30]
        # A percent is a context reading if it sits next to a context anchor OR next to a
        # host-source marker -- a "host counter shows ~88%" reading IS a context reading even when
        # the word "context" is absent, so a fabricated host claim cannot dodge the gate by
        # omitting "context".
        is_context = (
            any(anchor in before for anchor in RESPONSE_GUARD_CONTEXT_PERCENT_ANCHORS)
            or any(anchor in after for anchor in RESPONSE_GUARD_CONTEXT_PERCENT_ANCHORS)
            or response_context_percent_is_host_sourced(scan_text, match)
        )
        if not is_context:
            continue
        # A percent earns the host-sourced skip ONLY when it is host-sourced AND NOT hedged: an
        # estimate marker ("~88%", "roughly 88%") next to a host word is still a self-estimate, so
        # "host counter shows ~88%" cannot launder a fabricated number.
        if response_context_percent_is_host_sourced(scan_text, match) and not (
            response_context_percent_is_estimated(scan_text, match)
        ):
            continue
        # estimated OR bare (neither hedge nor host marker == bare, still unprovenanced)
        near_anchor = any(abs(match.start() - pos) <= 120 for pos in anchors)
        if near_anchor:
            stop_adjacent_unprovenanced = True
            break
    if not stop_adjacent_unprovenanced:
        return False
    # Resume carve-out: a genuine in-turn rotation+resume that does not ask permission and does not
    # defer to LATER passes. A genuine rotation is the host-fallback path (which inherently resumes)
    # OR a /compact-style action paired with an explicit resume signal -- a bare "/compact and
    # handing off" with no resume does NOT qualify. Scoped to DEFER-TO-LATER markers only so the
    # housekeeping word "handoff" does not defeat a real host-fallback handoff.
    has_genuine_resume = response_has_host_fallback_rotation(scan_text) or (
        response_has_rotation_action_or_fallback(scan_text)
        and text_contains_any(scan_text, RESPONSE_GUARD_CONTEXT_RESUME_MARKERS)
    )
    if (
        has_genuine_resume
        and not has_human_prompt
        and not text_contains_any(scan_text, RESPONSE_GUARD_CONTEXT_DEFER_TO_LATER_MARKERS)
    ):
        return False
    return True


def response_has_iteration_review_media_deferral(text: str) -> bool:
    scan_text = response_guard_policy_scan_text(text)
    if not text_contains_any(scan_text, RESPONSE_GUARD_MEDIA_DEFERRAL_MARKERS):
        return False
    return text_contains_any(scan_text, RESPONSE_GUARD_ITERATION_REVIEW_MEDIA_CONTEXT_MARKERS)


BOUNDARY_SUMMARY_RECOGNIZED_HEADINGS = [
    "## Plain English",
    "## Progress",
    "## Next",
    "## Technical Details",
]


RESPONSE_GUARD_BOUNDARY_EVENT_MARKERS = [
    "delivery summary",
    "session summary",
    "milestone summary",
    "goal summary",
    "handoff for review",
    "handoff-for-review",
    "queued for merge",
    "merge queued",
    "pr queued",
    "pr merged",
    "merged to main",
    "landed on main",
    "release published",
    "deployment completed",
    "deploy completed",
    "session complete",
    "milestone complete",
    "goal complete",
    "work delivered",
]


def response_has_boundary_summary_marker(text: str) -> bool:
    return any(re.search(rf"(?m)^{re.escape(heading)}\s*$", text) for heading in BOUNDARY_SUMMARY_RECOGNIZED_HEADINGS)


def response_looks_like_boundary_event(text: str) -> bool:
    scan_text = response_guard_policy_scan_text(text)
    if response_has_boundary_summary_marker(text):
        return True
    if text_contains_any(scan_text, RESPONSE_GUARD_BOUNDARY_EVENT_MARKERS):
        return True
    if re.search(r"\bpr\s*#\d+\b", scan_text) and text_contains_any(
        scan_text,
        [
            "merged",
            "queued",
            "landed",
            "pushed",
            "opened",
            "created",
            "closed",
            "ready to push",
            "ready for review",
            "auto-merge enabled",
        ],
    ):
        return True
    return False


def response_boundary_summary_errors(text: str) -> list[str]:
    errors: list[str] = []
    raw_scan = text.lower()
    if "/goal" in raw_scan and not text_contains_any(raw_scan, ["proof", "evidence", "validation"]):
        errors.append("boundary summary that names Claude /goal must surface proof, evidence, or validation")
    return errors


def response_non_whitespace_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def response_is_terse_no_information(text: str) -> bool:
    stripped = re.sub(r"\s+", " ", (text or "").strip()).lower()
    if response_non_whitespace_len(stripped) > 50:
        return False
    return text_contains_any(
        stripped,
        [
            "quiet",
            "standing by",
            "yielding",
            "waiting",
            "holding",
            "pending",
            "awaiting feedback",
            "backing off",
            "idle",
            "paused",
            "no change",
            "unchanged",
            "same",
            "blocked",
            # Item 83 PR2 T2.6. The null-turn RCA's own examples: a turn that reports nothing and
            # ends. This is the CHEAP phrase backstop the proposal asked for -- the real closure is
            # the state arming above, which does not care what the turn said.
            "no response requested",
            "nothing to do",
            "done for now",
        ],
    )


def response_looks_like_autonomous_yield(text: str) -> bool:
    if response_has_boundary_summary_marker(text):
        return False
    scan_text = response_guard_monitor_scan_text(text)
    policy_text = response_guard_policy_scan_text(text)
    has_forward_motion = text_contains_any(scan_text, RESPONSE_GUARD_FORWARD_MOTION_MARKERS)
    passive_without_forward_motion = text_contains_any(
        scan_text, RESPONSE_GUARD_PASSIVE_MONITOR_PHRASES
    ) and not has_forward_motion
    return (
        response_is_terse_no_information(text)
        or passive_without_forward_motion
        or (text_contains_any(scan_text, RESPONSE_GUARD_AUTONOMOUS_YIELD_MARKERS) and not has_forward_motion)
        or ("monitor" in scan_text and ("yield" in scan_text or "until then" in scan_text) and not has_forward_motion)
        or (
            "pr #" in policy_text
            and text_contains_any(
                policy_text,
                [
                    "unchanged",
                    "blocked",
                    "waiting",
                    "hold",
                    "failing",
                    "failed",
                    "needs",
                    "awaits",
                    "awaiting",
                    "sign-off",
                    "recheck",
                    "backing off",
                ],
            )
            and not has_forward_motion
        )
    )


def response_autonomous_yield_fields(text: str) -> dict[str, str]:
    field_pattern = re.compile(
        r"^\s*(?:[-*]\s*)?(?:#+\s*)?(plain\s+english|progress|next[-\s]poll|next|technical\s+details|state|did\s+not\s+advance|blocker)\s*:?\s*(.*)$",
        re.I,
    )
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("```") or line.startswith(">"):
            continue
        match = field_pattern.match(raw_line)
        if match:
            key = re.sub(r"\s+", " ", match.group(1).lower()).replace("next poll", "next-poll")
            current = key
            fields.setdefault(key, [])
            if match.group(2).strip():
                fields[key].append(match.group(2).strip())
            continue
        if current and line:
            fields[current].append(line)
    return {key: " ".join(value).strip().lower() for key, value in fields.items()}


RESPONSE_GUARD_TRANSIENT_EXTERNAL_MARKERS = [
    "anthropic",
    "claude api",
    "anthropic api",
    "api error",
    "apierror",
    "api_error",
    "api overload",
    "overloaded",
    "overloaded_error",
    "server issue",
    "server issues",
    "server error",
    "internal server error",
    "bad gateway",
    "gateway timeout",
    "provider outage",
    "provider unavailable",
    "service degraded",
    "too many requests",
    "rate limit",
    "rate-limit",
    "rate limited",
    "rate-limited",
    "exceeded retry limit",
    "service unavailable",
    "temporarily unavailable",
    "transient",
    "timeout",
    "timed out",
    "websocket",
    "connection reset",
    "network error",
    "try again",
]


RESPONSE_GUARD_TRANSIENT_EXTERNAL_STATUS_RE = re.compile(
    r"\b(?:http|api|status|error|response|returned|returns|codex|anthropic|claude|github|provider|service|server|rate[- ]limit|too many requests|overload(?:ed)?)\b.{0,40}\b(?:429|500|502|503|504|529)\b"
    r"|\b(?:429|500|502|503|504|529)\b.{0,40}\b(?:http|api|status|error|too many requests|rate[- ]limit|overload(?:ed)?|service unavailable|server|provider)\b",
    re.I | re.S,
)


RESPONSE_GUARD_PROVIDER_OUTAGE_STOP_MARKERS = [
    "can't continue",
    "cannot continue",
    "unable to continue",
    "can't proceed",
    "cannot proceed",
    "blocked until",
    "blocked by",
    "stopping",
    "stop here",
    "stopped",
    "try later",
    "try again later",
    "when it recovers",
    "when the service recovers",
    "when anthropic recovers",
    "when claude recovers",
    "when api recovers",
]


RESPONSE_GUARD_ARMED_RETRY_MARKERS = [
    "schedulewakeup armed",
    "schedule wakeup armed",
    "schedulewakeup scheduled",
    "schedule wakeup scheduled",
    "self-wakeup armed",
    "self wakeup armed",
    "wakeup armed",
    "heartbeat armed",
    "timer armed",
    "cron scheduled",
    "automation created",
    "retry already running",
    "retry is running",
    "retry loop armed",
    "provider recovery loop",
    "provider recovery armed",
    "recovery loop armed",
    "next retry",
    "retry at",
    "retrying at",
    "next check due",
    "next provider check",
    "poll cadence",
    "active poll already underway",
    "rerun already started",
]


RESPONSE_GUARD_RECOVERY_CANCELLATION_MARKERS = [
    "canceling the scheduled auto-retry",
    "cancelling the scheduled auto-retry",
    "cancelled the scheduled auto-retry",
    "canceled the scheduled auto-retry",
    "canceling scheduled auto-retry",
    "cancelling scheduled auto-retry",
    "cancelled scheduled auto-retry",
    "canceled scheduled auto-retry",
    "canceling the auto-retry",
    "cancelling the auto-retry",
    "cancelled the auto-retry",
    "canceled the auto-retry",
    "canceling auto-retry",
    "cancelling auto-retry",
    "cancelled auto-retry",
    "canceled auto-retry",
    "canceling the retry",
    "cancelling the retry",
    "cancelled the retry",
    "canceled the retry",
    "canceling scheduled wakeup",
    "cancelling scheduled wakeup",
    "cancelled scheduled wakeup",
    "canceled scheduled wakeup",
    "canceling the scheduled wakeup",
    "cancelling the scheduled wakeup",
    "cancelled the scheduled wakeup",
    "canceled the scheduled wakeup",
    "canceling the recovery loop",
    "cancelling the recovery loop",
    "cancelled the recovery loop",
    "canceled the recovery loop",
    "canceling provider recovery",
    "cancelling provider recovery",
    "cancelled provider recovery",
    "canceled provider recovery",
    "stopping the autonomous loop",
    "stopped the autonomous loop",
    "no autonomous loop",
    "no scheduled wakeups",
    "nothing will re-trigger",
    "nothing will retrigger",
]


def response_has_transient_external_marker(text: str) -> bool:
    scan_text = response_guard_policy_scan_text(text)
    return text_contains_any(scan_text, RESPONSE_GUARD_TRANSIENT_EXTERNAL_MARKERS) or bool(
        RESPONSE_GUARD_TRANSIENT_EXTERNAL_STATUS_RE.search(scan_text)
    )


def response_has_transient_external_yield_without_armed_retry(text: str) -> bool:
    fields = response_autonomous_yield_fields(text)
    if not fields:
        return False
    relevant = " ".join(
        fields.get(field, "")
        for field in ["plain english", "progress", "next", "technical details", "state", "blocker", "next-poll"]
    )
    if not response_has_transient_external_marker(relevant):
        return False
    if not text_contains_any(response_guard_policy_scan_text(text), RESPONSE_GUARD_ARMED_RETRY_MARKERS):
        return True
    return False


def response_has_provider_outage_stop_without_recovery(text: str) -> bool:
    scan_text = response_guard_policy_scan_text(text)
    if not response_has_transient_external_marker(scan_text):
        return False
    if text_contains_any(scan_text, RESPONSE_GUARD_ARMED_RETRY_MARKERS):
        return False
    return text_contains_any(scan_text, RESPONSE_GUARD_PROVIDER_OUTAGE_STOP_MARKERS) or response_looks_like_autonomous_yield(text)


RESPONSE_GUARD_FLAKY_DISMISSAL_MARKERS = [
    "just flaky", "just a flaky test", "probably flaky", "must be flaky", "it's flaky", "its flaky",
    "likely flaky", "seems flaky", "that's just a flaky", "flaky, moving on", "flaky so moving on",
    "flaky and moved on", "flaky and moving on", "skip the flaky", "skipping the flaky",
    "skipped the flaky", "skip that flaky", "ignore the flaky", "ignoring the flaky",
    "ignored the flaky", "re-ran until it passed", "re-ran until green", "reran until green",
    "reran until it passed", "ran it again and it passed", "passed on retry", "passed on re-run",
    "passed on rerun", "green on retry", "retried until green", "retried and it passed",
    "rerun to green", "re-run to green", "re-running until green",
]


RESPONSE_GUARD_FLAKE_HANDLING_MARKERS = [
    "quarantine", "quarantined", "root cause", "root-cause", "root caused", "root-caused",
    "regression test",
]


def response_has_flaky_rationalization_stop(text: str) -> bool:
    """A failing test dismissed as 'flaky' (re-ran until green / skipped / ignored) is a bug, not a
    completion. Block ending the turn on that rationalization UNLESS the response shows real handling:
    a root-cause fix, a regression test, or a quarantine with a tracked owner+due issue."""
    scan_text = response_guard_policy_scan_text(text)
    if not text_contains_any(scan_text, RESPONSE_GUARD_FLAKY_DISMISSAL_MARKERS):
        return False
    if text_contains_any(scan_text, RESPONSE_GUARD_FLAKE_HANDLING_MARKERS):
        return False
    if re.search(r"#\d+\b", scan_text):  # a tracked issue/PR reference = real handling
        return False
    if "owner" in scan_text and "due" in scan_text:  # an owner+due quarantine entry
        return False
    return True


def response_has_recovery_cancellation(text: str) -> bool:
    return text_contains_any(response_guard_policy_scan_text(text), RESPONSE_GUARD_RECOVERY_CANCELLATION_MARKERS)


def response_has_specific_anchor(text: str) -> bool:
    return bool(
        re.search(r"#\d+\b", text)
        or re.search(r"\bpid\s+\d+\b", text)
        or re.search(r"\b20\d{2}-\d{2}-\d{2}(?:t|\b)", text)
        or re.search(r"(?:^|\s)[./]?[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+", text)
        or re.search(r"\b[A-Za-z0-9_.-]+\.(?:md|log|json|txt|yaml|yml)\b", text)
    )


def response_autonomous_yield_schema_errors(text: str) -> list[str]:
    errors: list[str] = []
    return errors


def response_has_blocked_pr_yield_without_context(text: str) -> bool:
    if response_autonomous_yield_fields(text):
        return False
    policy_text = response_guard_policy_scan_text(text)
    if "pr #" not in policy_text:
        return False
    if text_contains_any(response_guard_monitor_scan_text(text), RESPONSE_GUARD_FORWARD_MOTION_MARKERS):
        return False
    return text_contains_any(
        policy_text,
        [
            "unchanged",
            "blocked",
            "waiting",
            "hold",
            "failing",
            "failed",
            "needs",
            "awaits",
            "awaiting",
            "sign-off",
            "recheck",
            "heartbeat",
            "standing by",
        ],
    )


# Tuples, not lists, ON PURPOSE: an UPPER_CASE list-of-str constant auto-enters the policy-phrases
# SSOT. These are structural keys and tool names, not policy phrases, so they stay out of it.
ASK_USER_QUESTION_TOOL_NAMES = ("askuserquestion", "ask_user_question")

ASK_USER_QUESTION_INPUT_KEYS = (
    "question",
    "questions",
    "header",
    "options",
    "label",
    "description",
)


def flatten_question_tool_input(value: object) -> str:
    """Flatten an AskUserQuestion-class tool input (the questions/options tree) to scannable text.

    RCA 20260701T115759Z: the forbidden continue-vs-stop menu lived under
    `input` -> `questions[]` -> `question`/`header`/`options[]` -> `label`/`description`, none of
    which `flatten_hook_text` ever walked, so the exact pattern the free-text detector would have
    caught was invisible to every guard.
    """
    parts: list[str] = []

    def walk(item: object) -> None:
        if isinstance(item, str):
            parts.append(item)
            return
        if isinstance(item, list):
            for child in item:
                walk(child)
            return
        if isinstance(item, dict):
            for key in ASK_USER_QUESTION_INPUT_KEYS:
                if key in item:
                    walk(item[key])

    walk(value)
    return "\n".join(part for part in parts if part)


def flatten_hook_text(value: object) -> str:
    parts: list[str] = []

    def walk(item: object) -> None:
        if item is None:
            return
        if isinstance(item, str):
            parts.append(item)
            return
        if isinstance(item, (int, float, bool)):
            parts.append(str(item))
            return
        if isinstance(item, list):
            for child in item:
                walk(child)
            return
        if isinstance(item, dict):
            # Targeted, never generic. Adding a plain "input" key to the walk below would pour
            # every `Write` tool's file body into every Stop-guard scan ("content" is already in
            # the key list), so the extension is scoped to tool_use blocks named AskUserQuestion.
            if (
                str(item.get("type") or "") == "tool_use"
                and str(item.get("name") or "").lower() in ASK_USER_QUESTION_TOOL_NAMES
            ):
                parts.append(flatten_question_tool_input(item.get("input")))
            for key in ["text", "content", "message", "result", "error", "stdout", "stderr"]:
                if key in item:
                    walk(item[key])

    walk(value)
    return "\n".join(part for part in parts if part)


def response_guard_has_live_goal_session(payload: dict, recent_text: str, last_assistant: str) -> bool:
    for key in ("minervit_active_goal", "active_goal", "goal_active"):
        value = payload.get(key)
        if value is True or str(value).lower() in {"1", "true", "yes", "active"}:
            return True
    scan_text = response_guard_context_scan_text(recent_text + "\n" + last_assistant)
    return text_contains_any(scan_text, RESPONSE_GUARD_LIVE_GOAL_SESSION_MARKERS)


def response_guard_should_evaluate_stop(payload: dict, recent_text: str, last_assistant: str) -> bool:
    if response_guard_has_live_goal_session(payload, recent_text, last_assistant):
        return True
    # Long Claude /goal sessions sometimes drop the transcript breadcrumb that says
    # "Goal not yet met" before the Stop hook fires. If an active ledger exists and
    # the assistant's own response is a context-rotation stop, enforce the guard
    # instead of letting the lane ask the human to compact/restart.
    return response_has_context_rotation_stop(last_assistant)


def response_guard_has_documented_rotation_exit(text: str) -> bool:
    scan = response_guard_context_scan_text(text)
    has_pressure = text_contains_any(scan, RESPONSE_GUARD_CONTEXT_PRESSURE_MARKERS) or bool(
        re.search(r"\b(?:[6-9]\d|100)\s*%(?!\w).{0,120}\bcontext\b", scan)
        or re.search(r"\bcontext\b.{0,120}\b(?:[6-9]\d|100)\s*%(?!\w)", scan)
    )
    if not has_pressure:
        return False
    return text_contains_any(
        scan,
        [
            "fresh-session startup",
            "fresh session startup",
            "exact fresh-session startup action",
            "exact next startup action",
            "resume the active goal after startup gates",
            "resume the same active goal after startup gates",
        ],
    )


def guard_check_call(label: str, func, args: argparse.Namespace) -> int:
    print(f"guard_check_running: {label}")
    result = func(args)
    rc = int(result or 0)
    if rc:
        print(f"guard_check_failed: {label}", file=sys.stderr)
    return rc
