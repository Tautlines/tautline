## Verified Human Instructions

- When giving the human operator instructions for an external system, verify the current process from authoritative sources in the same turn before giving steps.
- Use official vendor documentation, official CLI/API help, or the live product UI when available. For GitHub, prefer `docs.github.com`, `gh` help/API output, or GitHub UI evidence over memory, blog posts, or stale examples.
- Include direct links to the authoritative source pages used. Links must point to the specific relevant instructions, not a generic documentation home page.
- State prerequisites that affect the instructions: role, plan, ownership, feature availability, scope, and whether the setting is personal, organization, enterprise, or repository-level. If instructions vary by UI version, plan, role, or account type, name the branch or selecting fact.
- Do not invent UI labels, menu paths, setting names, screenshots, or links from memory. If current authoritative verification is unavailable, say the instructions are unverified, give only safe high-level guidance, and name the exact source needed before asking the human operator to act.
- Before sending human-action instructions, run this check: would a careful human operator be able to complete the change the first time using these steps and links? If not, verify further or narrow the instruction.
- The rule binds in both directions. When the human operator reports observed UI state — a screenshot, a live page — that contradicts the agent's API or CLI query results, the operator's observation is ground truth. Acknowledge the contradiction, then debug the query (identity, field-name semantics, pagination/truncation) instead of re-asserting the query result. Arguing with operator evidence is a stop-the-line defect.
