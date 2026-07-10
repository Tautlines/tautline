---
name: stakeholder-questions
description: Use when adapter-enabled stakeholder questions need to be asked, synced, answered, or checked through GitHub issue comments.
---

# Stakeholder Questions

Use when the adapter enables stakeholder questions, an active issue needs
operator/stakeholder clarification, or startup/boundary work must check whether
previous questions were answered.

Read `references/stakeholder-questions-policy.md` before asking questions,
syncing answers, interpreting issue comments, or deciding whether a question is
a true blocker.

## Fast Path

1. Check status with `minervit-methodology stakeholder-question-status --target
   . --sync`.
2. Ask only concrete product/stakeholder questions with
   `stakeholder-question-ask --target .`.
3. Link questions to the active issue/work item when available.
4. Treat answered comments as product evidence after sync.
5. Continue safe parallel work unless the missing answer changes approved
   scope, risk, data, security, cost, or product behavior.

## Non-Negotiables

- Do not ask broad preference or permission questions through this channel.
- Do not treat chat-only answers as synced issue evidence when the adapter
  requires GitHub comments.
- Do not block unrelated safe work while waiting for an answer.

## Required Follow-Through

Use the reference for question shape, sync rules, blocker criteria, issue
comment handling, and closeout behavior.
