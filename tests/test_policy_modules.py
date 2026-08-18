import re


def test_canonical_policy_matches_ordered_modules(cli):
    assembled = cli.canonical_policy_text_from_modules()

    assert assembled == cli.CANONICAL_RULES.read_text(encoding="utf-8")
    assert assembled.startswith("<!-- GENERATED COMPATIBILITY SOURCE:")


def test_policy_module_manifest_shape(cli):
    manifest = cli.load_policy_modules_manifest()
    modules = manifest["modules"]

    assert manifest["generatedArtifact"] == "methodology/canonical-rules.md"
    assert manifest["generator"] == "minervit-methodology canonical-policy --write"
    assert modules[0] == "00-introduction.md"
    assert modules[-1] == "31-automation.md"
    assert len(modules) == len(set(modules))
    assert all((cli.POLICY_MODULES_DIR / module).exists() for module in modules)
    assert {path.name for path in cli.POLICY_MODULES_DIR.glob("*.md")} == set(modules)


def test_canonical_policy_command_is_stable(cli):
    manifest = cli.public_contract_manifest_data()
    commands = {item["name"]: item for item in manifest["commands"]}

    assert commands["canonical-policy"]["status"] == "stable"


def test_canonical_policy_command_check(run_cli):
    result = run_cli("canonical-policy", "--check")

    assert result.returncode == 0
    assert "canonical_policy_check: ok" in result.stdout


def test_policy_module_index_lists_manifest_modules(cli):
    index = cli.REPO_ROOT / "docs" / "reference" / "policy-module-index.md"
    text = index.read_text(encoding="utf-8")
    modules = cli.load_policy_modules_manifest()["modules"]
    linked_modules = set(re.findall(r"\.\./\.\./methodology/policy/([^)\s]+\.md)\)", text))

    assert linked_modules == set(modules)
    for module in modules:
        assert module in text


def test_canonical_policy_requires_proof_of_done_without_pending_tests(cli):
    assembled = cli.canonical_policy_text_from_modules()
    normalized = " ".join(assembled.split())

    assert "proof-of-done standard" in assembled
    assert "would make completion believable" in assembled
    assert "`@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are not proof" in assembled
    assert "`@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are gaps, not proof" in assembled
    assert "`@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are not proof of completion" in normalized


def test_canonical_policy_size_ratchet(cli):
    assembled = cli.canonical_policy_text_from_modules()

    # Raised 60000 -> 60763 for the never-write-process-to-memory + intake-routing bullets in
    # 28-memory.md (2026-07-14 process-authority plan, Task 2), then 60763 -> 61093 for the
    # successor-plan sentence in 13-planning.md (same plan, Task 9), per the rough-edges
    # umbrella's shared-surface discipline: each lane raises the ratchet by its own measured
    # delta only. Raised 61093 -> 61900 for the three product-dev-mode standdown exception
    # bullets in 05-current-status-truth, 06a-stop-and-deferral-red-flags, and 20-background-work
    # (shepherding plan), then 61900 -> 62058 for the PM-surface VERSION-bump-exemption sentence
    # in 21-lane-lifecycle.md (classifier plan, T5), then 62058 -> 62626 for the PM-surface
    # pre-push review/CI exemption bullet in 17-review-before-push.md (this plan, T2). Raised
    # 62626 -> 63891 for the "## Unattended Operation" subsection in 03-autonomy.md (directive-core
    # plan, D4): the standing-autonomy-directive policy obligations (opt-out knob, durable record,
    # async operator-fork queue with hard-to-reverse fallback, guards-unchanged). Raised
    # 63891 -> 64262 for the plan-authoring standard bullet in 13-planning.md (2026-07-23
    # plan-authoring-standard plan, WS4): parallel-workstream shape, per-task model-tier tags,
    # embedded execution-autonomy contract, and the enforcement knob. Raised 64262 -> 64505
    # (Codex R1 P1): honest mechanical-enforcement scoping to the plan-review seam. Raised
    # 64505 -> 65077 (2026-07-23): the agent owns review AND merge -- deliver MERGED, never
    # hand a clean gate-green PR back for operator review/merge (Done = merged, not pushed).
    # Raised 65780 -> 66221 (2026-07-24, 0.20.0, item 26 key-with-title): the Delivery Summaries rule
    # requiring a bare item key (`FR-3`, `item 17`, a `METH-FU-...` slug) be followed by the
    # item's short title `KEY: <short title>` in human-facing output. Raised 66221 -> 66384
    # (2026-07-25, item 24 plan-review round advance gap): the convergence ladder now states that
    # the round-4 hard cap counts successful reviewer INVOCATIONS against one source plan rather
    # than `--round` labels. A lane that relabelled every round `R1` was getting unlimited rounds,
    # and a control nobody can read about is half a control -- the clause is the cheapest way to
    # say what the gate now enforces.
    # Raised 66384 -> 66843 (2026-07-26, item 27 session-start currency gate): the lane-currency
    # rule makes the agent, not the operator, responsible for lane freshness at session start --
    # attempt the printed remedy, and when it cannot complete, state the unresolved drift in your
    # own output rather than handing it back. Scoped to ownership plus disclosure and explicitly
    # NOT a precondition for responding, so it cannot become a session-start block.
    # Raised 66843 -> 67423 (2026-07-26, item 33 plain-language operator boundaries):
    # plain language at every human-facing boundary, and a real request when the agent
    # needs something from a human.
    # Raised 67423 -> 67592 (+169 bytes, the measured delta) for the machine-checkable-proof
    # sentence in 15-tdd-and-behavior-specs.md (item 37, test-execution proof, Release 1 / W4).
    # Raised 67592 -> 68084 (+492 bytes, the measured delta) for the implementation-review round
    # ladder in 17-review-before-push.md (item 48, 0.36.0): target vs hard cap, self-authorization
    # in between, confirming rounds free, and the invariant that no round decision on this surface
    # is ever an operator escalation. That last clause is the one worth the bytes -- the refusal it
    # replaces cost four lanes a night, and a control lanes cannot read about is half a control.
    # Raised 68631 -> 68868 (+237 bytes, the measured delta) for item 69 PR-B's review-entry
    # adapter-dirt refusal in 17-review-before-push.md (0.44.0). 68631 is PR-A's measured number,
    # not a guess: this lane re-measured on its own tip rather than carrying the +784 that the
    # combined branch produced before the split. A refusal a lane meets at REVIEW ENTRY and cannot
    # read about in the canonical rules is a dead end by another name.
    # Each lane raises this ratchet by its own measured delta only.
    # Raised 68868 -> 68945 (+77 bytes, this lane's own measured delta, re-measured against the
    # 0.46.0 tip and not carried forward from any predecessor) for item 72 Release A's canonical
    # `@pending @owner:<goal-or-lane> @unpend:<trigger>` form in 15-tdd-and-behavior-specs.md. The
    # rule already required owner + un-pend trigger; what it never did was SHOW the machine-
    # checkable shape, which is the RCA's "no documented tag spec" clause -- authors discovered the
    # format by trial against two duplicated inline string checks. The form carries a `@reason:`
    # slot because the bullet requires owner, REASON and un-pend trigger -- a form showing two of
    # the three would let an author follow it and still miss the written rule. 77 bytes buys it; no
    # rendered-adapter headroom is consumed, because policy 15's behavior-spec guidance is not part
    # of the rendered adapter surface that the six-claimant 320-byte pool covers.
    # Raised 68945 -> 69405 (+460 bytes, this lane's own measured delta, re-measured against the
    # 0.51.0 tip and carried forward from no predecessor) for item 73's AC-keyed routing rule in
    # 17-review-before-push.md. The rule it replaces made routing SEVERITY-scoped while the Done
    # gate is AC-scoped, so a Critical not open against the item's acceptance criteria was neither
    # blocking nor routable -- and the recorded cost of that gap was two review rounds, a module
    # built in flight and reverted, and two severity downgrades performed solely to make routing
    # legal. A rule whose enforcement ships in the same release but whose statement a lane cannot
    # read is half a control. No rendered-adapter headroom is consumed: the adapter's own routing
    # line is a measured 3-byte SAVING in the same change.
    # Raised 69405 -> 70225 (+820 bytes, this lane's own measured delta, re-measured on the
    # REBASED tip after 0.53.0 landed and carried forward from no predecessor -- 0.53.0 spent
    # zero canonical bytes, verified by rendering the base itself rather than by reading its
    # PR) for item 78 Release A's no-LLM graphify gate split in 25-graphify-navigation.md.
    # Three clauses buy it, and each closes a named clause of RCA 20260616T133743Z: the
    # blocking refresh is the dependency-free AST rebuild and is the ONLY invocation the gate
    # names; semantic enrichment is separate, non-blocking and backend-explicit; and -- the
    # generalizable one -- an invocation that auto-detects its backend is never a gate command
    # in ANY adapter, because a provider can retire the model auto-detect lands on and kill the
    # documented gate permanently. The third bullet is the prevention-gap rule: a finding that a
    # documented blocking gate command does not run is a source defect, never doc staleness.
    # That reclassification is what kept this RCA open for two months with zero shipped
    # controls, so the bytes are the control.
    # Raised 70225 -> 70414 (+189 bytes, this lane's own measured delta, RE-MEASURED on the
    # c86b59b1 tip after 0.53.0 and 0.54.0 both landed mid-flight -- never carried forward from
    # the 69405 base this branch was cut against) for item 72 Release B's
    # `behavior-spec-status --base` sentence in 15-tdd-and-behavior-specs.md. The bytes buy the
    # part a lane cannot infer from the flag name: that it REPORTS and never changes an exit
    # code, and that `behavior-spec-delta-check` is the enforcing counterpart. A reporting line
    # mistaken for a gate is how a real gate ends up treated as already covered.
    # Raised 70414 -> 70954 (+540 bytes, this lane's own measured delta, RE-MEASURED on the
    # 40b1b39a tip after this item's own 0.56.0, 0.57.0 and 0.58.0 all landed -- never carried
    # forward from the 68945 figure the batch packet quoted) for item 81's oracle-discipline
    # clause in 10b-board-currency.md. The enforcement shipped across three releases; this is
    # its statement. Three parts buy the bytes and none is inferable from the others: closure
    # evidence is measured against the item's WRITTEN acceptance criteria and carries one
    # PASS/FAIL row per criterion; an unmet criterion is a FAILED AC and never a deferral, which
    # is the exact substitution the RCA recorded; and verifying the implementation against
    # itself is forbidden, because a table built from the code cannot fail. A lane that meets
    # the strict refusal and cannot read why is a dead end -- the failure shape this whole item
    # exists to close.
    # Raised 70954 -> 71418 (+464 bytes, this PR's own measured delta, RE-MEASURED on the
    # f9cbb69c tip after 0.60.0 landed mid-flight -- 0.60.0 spent zero canonical bytes, verified
    # by rendering the new base rather than by reading its PR) for item 75 WS1's two bullets in
    # 17-review-before-push.md. The first states the empty-subject refusal, which is a gate that
    # now REFUSES: a lane that meets it and cannot read why is the dead end the rule exists to
    # close. The second is the verbatim doc-only P2-default rule both source RCAs asked for and
    # which grep confirmed existed nowhere.
    # Raised 71418 -> 71838 (+420 bytes, this PR's own measured delta on the e09ff7fa tip, its
    # own sibling's merge) for item 75 WS2's execution-counting bullet in
    # 17-review-before-push.md. It buys the part a lane cannot infer from a refusal string: the
    # label is not the count, the budget and the ceiling compare DIFFERENT currencies, and a base
    # change starts a fresh lineage. Six runs labelled R1 spent six rounds while every label said
    # one, and a lane reading the old bullet had no way to know that was possible.
    # Raised 71838 -> 72669 (+831 bytes, this lane's own measured delta on the 7896978c tip) for
    # item 71 WS2/WS3's two bullets: the adapter-declared board identity in 10a-backlog-provider.md
    # and the both-directions ground-truth rule in 08-verified-human-instructions.md. Both are RCA
    # controls with exact prescribed wording, so neither can be trimmed to fit. They buy the two
    # sentences a lane cannot infer from a refusal: that a queried project number differing from
    # the configured one is blocking drift rather than a fallback candidate, and that operator-
    # observed UI state beats an API result rather than losing to it. The recorded failures were
    # an agent resolving a board by display-name resemblance and then arguing with the operator's
    # screenshots -- neither is reachable from prose that does not exist.
    # Raised 72669 -> 73755 (+1086 bytes, this lane's own measured delta on the 112b4705 tip)
    # for batch 2026-08-11 item B7's TWO statements, both in 10-goal-orchestration.md. Raised
    # ONCE naming both, deliberately: two raises in one PR is how a ratchet number gets carried
    # forward wrong.
    #
    #   1. The definition of done. Its cost is mostly irreducible: it must NAME the seven
    #      condition ids (a lane cannot look up a set the rules do not list), and it must state
    #      the handoff bar in both directions -- that an unarmed open PR is not done, AND that a
    #      queued auto-merging one IS, so the rule cannot be read as a licence to sit on a merge
    #      monitor. It also states the `unknown`-never-blocks-never-zero semantics and the legal
    #      exits, because a gate that refuses without naming its exit is one an agent routes
    #      around.
    #   2. The goal-delivery rule: a goal handed to a human is the sole content of the response.
    #      This is the agent-facing half of a defect the operator found by trying to use a goal;
    #      `--out` is the tooling half and cannot enforce the response shape by itself.
    #
    # HONEST ACCOUNTING: the plan estimated 550-800 for the pair and the measured delta is
    # 1,086 -- a 36% overrun over the top of the range. Both statements were tightened once
    # after the first measurement (1,269 -> 1,086, -183) and what remains is content, not
    # wording. Recorded rather than absorbed silently, because an estimate quietly exceeded is
    # how the next lane inherits a ceiling nobody can account for.
    # Raised 73755 -> 73857 (+102, measured) to QUALIFY the refusal sentence: the shipped
    # default is `warn`, and a canonical rule stating a flat "refuses" while the code reports
    # would be the authority document lying about the behavior -- the same defect the schema
    # description had, in the one place a lane is most entitled to trust.
    # Raised 73857 -> 76395 (+2,538, measured on this branch's tip by regenerating from the
    # modules, not estimated) for item 101's PR-reference contract: three statements in
    # 10b-board-currency (+1,921), one cross-reference sentence in 18-merge-and-ci (+253), and
    # one delivery-summary linkage sentence in 09 (+364).
    #
    # The cost is mostly irreducible because each statement has to carry the thing that makes it
    # actionable rather than merely true:
    #
    #   1. The four rules must distinguish COMPLETING from ADVANCING and give the title-only
    #      form for the advancing case, because "reference the item precisely" without the two
    #      shapes is a rule every lane resolves differently -- and one of the resolutions
    #      auto-closes live unfinished work on a stakeholder board.
    #   2. The auto-close statement must name the DEFAULT-BRANCH condition. GitHub honours a
    #      body keyword only when the PR's base is the default branch, so on an
    #      integration-branch repo -- which is what this framework and its adopters run -- the
    #      unconditional promise is simply false, and a rule that promises a mechanism which
    #      silently does not fire is worse than no rule because the lane stops checking.
    #   3. The enforcement-gap statement exists because the gate contradicts rule 3 TODAY. An
    #      adopter can be refused for obeying the published rule, and the fabricated-reference
    #      workaround that invites is the exact harm rule 4 names. Naming the gap plus its
    #      forbidden workaround is what stops the rule teaching lanes to lie to the gate.
    #
    # Operational detail deliberately did NOT come here: the GitHub-honoured forms, the
    # one-keyword-per-issue rewrite, the advancing-vs-completing decision procedure and the
    # commit-message consequence all live in the `board-item-updates` skill, which costs no
    # ratchet and no rendered-adapter corridor.
    # 76395 -> 76666 (+271) at implementation review R1, for the cross-repo qualified-reference
    # clause: a bare `#N` resolves against the PR's own repository, so a provider-backed item
    # living in another repo needs `owner/repo#N` in both the title and the closing keyword.
    # 76666 -> 76921 (+256, THIS lane's own measured delta, re-measured on the 0.76.0 tip and not
    # carried from any predecessor) for item 82's two enforcement pointers: the encoding-independent
    # clause on the pick-path prohibition in 04-autonomy-and-status.md, and the
    # `stop.announce_and_stop` pointer in 09-delivery-summaries.md. Both are one sentence added
    # a rule that already existed -- this cluster is prose describing enforcement that never
    # existed,
    # and what the bytes buy is the pointer FROM the rule TO the check that now enforces it. A
    # control lanes cannot read about is half a control.
    #
    # Operational detail deliberately did NOT come here, per the close-out corridor decision: the
    # three check ids, their recovery actions, the advisory-vs-blocking split and the demotion knob
    # all live in the `stop-guard-evasion-shapes` reference under the risk-tier-autonomy skill,
    # which costs no ratchet and no rendered-adapter corridor.
    #
    # MEASURED rendered-adapter corridor for this release: CLAUDE.md 16,116 -> 16,116 and
    # AGENTS.md 16,057 -> 16,057, byte-identical, so this release spends ZERO of the 202 free bytes
    # and every later claimant still has all 202. Measured by rendering example-saas on this
    # branch's tip, never by reading a PR body.
    #
    # The first number written here was 76935, measured BEFORE policy 04's sentence was tightened
    # to fit a conciseness cap. Shipping it would have granted the next lane 14 bytes it never
    # earned -- the stale-carried-raise failure this program names explicitly, in the small. The
    # number below is re-measured on the final tree.
    # Raised 76921 -> 78377 (+1456, THIS lane's own measured delta on the rebased 0.79.0 tip) for
    # item 74 PR-C's policy module 16a-go-live-readiness.md. A whole section rather than a
    # sentence, and it earns that: both member RCAs' Fix Proposals ask for exactly a canonical
    # Go-Live section, and the gate this release ships REFUSES by naming a control -- a refusal a
    # lane meets and cannot read about is a dead end by another name.
    #
    # Re-measured after the module's gate wording was aligned to the GO_LIVE_GATES table; a first
    # reading of +1103 was taken before that alignment, and carrying it would have granted the next
    # lane 34 bytes it never earned.
    #
    # MEASURED rendered-adapter corridor: CLAUDE.md and AGENTS.md byte-identical, so ZERO of the
    # 202 free bytes -- the module renders into canonical-rules.md, which has no such cap.
    #
    # Raised 78377 -> 79339 (+962) for item 83 PR1's four monitor-lifecycle rules in policy 20 and
    # the goal-clear hand-back in policy 04. RE-MEASURED on this rebased 0.81.0 tip by regenerating
    # canonical-rules.md, not carried: the branch's own note called its earlier 77883 provisional
    # precisely because item 74 PR-C was ahead of it in the ratchet queue. The delta happens to be
    # the same 962 as on the old base, which is a fact to state rather than a reason to skip the
    # measurement -- an unchanged delta and a stale number look identical in a diff.
    #
    # The REASONING for those four rules lives in the background-monitoring skill reference, which
    # costs neither this ratchet nor the corridor. Only the rules themselves are here.
    # Raised 79339 -> 80074 (+735) for item 85 WS3: one bullet in policy 23 naming where operator
    # secrets persist and the probe that checks them, and one clause extending policy 03's
    # true-blocker sentence.
    #
    # RE-MEASURED on this rebased 0.82.0 tip by regenerating canonical-rules.md, not carried. The
    # earlier reading of +735 was taken on the 0.81.0 base while item 83 PR1 held the ratchet queue
    # ahead of this branch, and its own note called it provisional for exactly that reason. The
    # delta is unchanged, which is a fact to state rather than a licence to skip the measurement:
    # an unchanged delta and a stale number look identical in a diff.
    #
    # MEASURED rendered-adapter corridor: byte-identical, so ZERO of the 202 free bytes. The rule
    # lands in policy modules and a skill reference, both of which render into canonical-rules.md
    # rather than the generated adapter.
    # 80074 -> 80246 (+172) after Codex R1: policy 23 must distinguish `indeterminate` from
    # `absent`, because the rule names `absent` as the escalation predicate and the probe was
    # printing that exact marker for a result it had NOT measured. Re-measured, not adjusted by
    # the diff's line count.
    # Raised 80246 -> 80744 (+498) for item 83 PR2 WS4: the corrected guard-activation sentence in
    # policy 20 -- the shipped one asserted the guard is active only with a live goal ledger, which
    # is the hole this release closes -- plus the yield rule and the null-turn invariant.
    #
    # RE-MEASURED against the MERGED 0.83.0 base, and the number MOVED: the same three edits
    # measured +690 against 0.82.0. 0.83.0's own policy-23 additions changed what this text costs,
    # so carrying the earlier reading forward would have claimed 192 bytes this lane did not spend.
    # That is the whole reason the rule is re-measure-never-carry, and this is the first time in
    # this program the delta actually differed rather than merely being re-derived.
    assert len(assembled.encode("utf-8")) <= 80744


def test_canonical_policy_keeps_ops_provider_detail_out_of_core_modules(cli):
    assembled = cli.canonical_policy_text_from_modules()
    forbidden = ("Google Chat", "S3", "CloudFront", "Baretail", "Drizzle")
    offenders = [term for term in forbidden if term in assembled]

    assert offenders == []
