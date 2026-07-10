# Human Instructions Policy Reference

Use this reference with the `human-instructions` skill before asking the human
operator to take action in an external system.

## Scope

External systems include GitHub, cloud consoles, identity providers, billing
portals, production services, third-party dashboards, and vendor-controlled
installation/setup flows. This policy applies especially to security, admin,
GitHub, cloud, identity, billing, production, or third-party setup changes.

## Verification Requirement

Verify the current process in the same turn before giving steps. Acceptable
sources are official vendor documentation, official CLI or API help/output, or
live product UI evidence when available.

For GitHub, prefer `docs.github.com`, `gh` help/API output, or GitHub UI
evidence over memory, blog posts, or old examples.

Do not invent UI labels, menu paths, setting names, screenshots, or links from
memory. If current authoritative verification is unavailable, say the
instructions are unverified, give only safe high-level guidance, and name the
exact source needed before asking the human operator to act.

## Required Output

Human-action instructions must include:

- direct links to the specific authoritative source pages used
- prerequisites that affect the steps, such as required role, plan, ownership,
  feature availability, repository scope, or account level
- exact scope of the setting: personal, organization, enterprise, repository,
  environment, project, or team
- verified steps using current labels and paths
- branch-specific instructions when the workflow differs by UI version, role,
  plan, or account type

Do not link only to a generic documentation home page when a specific source
exists. Links must point to the specific relevant instructions.

## Completion Check

Before sending, check whether a careful human operator could complete the change
the first time using the steps and links. If not, verify further or narrow the
instruction.
