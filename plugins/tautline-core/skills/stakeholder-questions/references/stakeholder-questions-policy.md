# Stakeholder Questions Policy Reference

This reference keeps detailed stakeholder clarification policy behind the
concise `stakeholder-questions` skill entrypoint.

## Purpose

Use this policy when a project adapter enables `stakeholderQuestions`, when an
agent needs stakeholder clarification on an active GitHub issue, when GitHub
issue comments are used for product-owner answers, or when a lane must check
whether previously asked stakeholder questions have been answered.

Stakeholder clarifications happen on the active GitHub issue, not in private
chat or memory. The question, answer, marker, labels, and optional Project item
status movement must be durable for the lane, other agents, and stakeholders.

## Ask

Use:

```bash
tautline stakeholder-question-ask --target . \
  --issue <issue-number-or-url> \
  --question "<one clear question>" \
  --why "<why the answer changes the build>" \
  --needed-for "<goal/milestone/PR scope>"
```

Ask one clear question at a time. The question must name the decision needed,
why the answer changes the build, and the goal, milestone, or PR scope that is
blocked or at risk.

The command uses `stakeholderQuestions.defaultMention` unless
`--stakeholder @handle` is supplied. If no stakeholder is configured, ask the
human operator one exact blocker question naming the missing stakeholder, then
persist the answer in the project adapter so future questions do not ask again.

Do not hand-write marker comments. The CLI writes the `minervit-question`
marker, labels the issue, and, when the issue is linked to an enabled backlog
provider, moves the Project item to the adapter-approved blocked status.

## Sync

At startup, PR boundaries, milestone boundaries, and blocked-work checks, run:

```bash
tautline stakeholder-question-status --target . --sync
```

The sync command scans open stakeholder-question issues, detects a later comment
from the tagged stakeholder, records an answered marker, updates labels, and
restores the Project item status when configured.

An unanswered stakeholder question is a real blocker only for the work whose
decision depends on that answer. Continue unrelated authorized work only when it
does not rely on the missing answer and does not obscure the open question.

## Authority

GitHub issue answers are stakeholder input evidence. They are not execution
authority by themselves. After an answer is recorded, update the repo
source-of-truth goal, milestone, or PR plan with the decision before
implementing the decision.

If the answer is ambiguous, post one follow-up question through
`stakeholder-question-ask`; do not guess.

Do not treat private chat, memory notes, or local scratch files as a substitute
for the GitHub issue answer when the adapter enables stakeholder questions. If
the human answers outside the issue, move the answer back through the configured
issue workflow so the durable source remains current.

## Boundaries

Use stakeholder questions for product or stakeholder clarification, not for
changing board schema, bypassing review gates, requesting permission to skip
tests, or asking the operator to choose between methodology-required actions.

Stakeholder-authored issue substance remains stakeholder-owned by default. If an
agent believes the issue title, summary, acceptance criteria, labels, priority,
or milestone should change, it should comment and ask through this flow rather
than editing those fields directly unless the adapter explicitly allows that
write.
