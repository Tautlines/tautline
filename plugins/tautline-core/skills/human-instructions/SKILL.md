---
name: human-instructions
description: Use for verified security/admin/GitHub/cloud/identity/billing/production/third-party external-system instructions.
---

# Human Instructions

Use this skill before asking the human operator to take action in an external system.
Read `references/human-instructions-policy.md` in full before giving steps.

## Verification

Verify the current process in the same turn before giving steps.
Use official vendor docs, official CLI/API help, or live UI evidence. For GitHub, prefer `docs.github.com`, `gh` help/API output, or GitHub UI evidence over memory, blog posts, or old examples.

## Output

Instructions must include:

- direct links to the specific authoritative source pages used
- prerequisites that affect the steps, such as required role, plan, ownership, feature availability, repository scope, or account level
- exact scope of the setting: personal, organization, enterprise, repository, environment, project, or team
- verified steps using current labels and paths
- branch-specific instructions when UI version, role, plan, or account type changes the workflow

## Guardrails

- Do not invent UI labels, menu paths, setting names, screenshots, or links from memory.
- Do not link only to a generic documentation home page when a specific source exists.
- If current authoritative verification is unavailable, say the instructions are unverified, give only safe high-level guidance, and name the exact source needed before asking the human operator to act.
- Before sending, check whether a careful human operator could complete the change the first time using the steps and links; otherwise verify further or narrow the instruction.
