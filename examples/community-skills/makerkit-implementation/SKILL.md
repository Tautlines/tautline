---
name: makerkit-implementation
description: Apply MakerKit SaaS implementation, porting, auth, billing, deployment, and testing lessons from the example stack pack.
---

> EXAMPLE / STACK-SPECIFIC SKILL. MakerKit is a public third-party OSS SaaS
> starter; this worked example belongs in a community examples plugin
> rather than the portable methodology core.

# MakerKit Implementation

Use this skill for MakerKit implementation judgment. Read `references/makerkit-implementation-policy.md` in full before any MakerKit implementation, port, package/import/export decision, auth/session/ownership/tenant/billing/data/migration/deployment/verification/healthcheck/smoke change, or skill refresh. Do not proceed from this entrypoint alone for those tasks.

Keep this example generalized and customer-safe. Do not add proprietary MakerKit code, customer names, account IDs, live hosts, private adapter paths, or project-specific infrastructure details.

## First Moves

1. Run the active Minervit adapter startup/status gates before planning or implementation in adapter-backed repos.
2. Identify the installed kit shape first: inspect root/package rules, workspace config, `apps/web`, key packages, `apps/e2e`, and local kit docs.
3. Read `references/current-lessons.md` for architecture, auth, tenant/owner isolation, deployment, branding, testing, billing, porting, or skill refresh work.
4. Read `references/example-engine-makerkit.md` for the worked Example Engine SaaS-port case, personal/guest ownership, legacy logic ports, one-off guest checkout, or follow-on conventions.
5. Prefer installed kit source and local docs over memory. Use official external docs only for touched behavior, then reconcile with local source.
6. Apply the active adapter and Minervit gates. This skill adds MakerKit judgment; it does not replace project process.

## Core Posture

Treat MakerKit as the owned SaaS platform, not a blank Next.js app.

- Start from the product boundary: decide which stock SaaS features stay, change, or leave.
- Extend MakerKit auth, accounts, orgs, billing, admin, database, UI, and navigation before rebuilding them.
- Keep route, UI, database, auth, billing, and feature-package boundaries explicit.
- Preserve production/legacy apps until the source-of-truth plan authorizes cutover.
- Test behavior, routes, owner/tenant isolation, and billing before exposing customer, operator, auth, account, or tenant behavior.
- Ship narrow reviewed increments; split repeated security, tenancy, billing, or deployment findings.

## Non-Negotiables

- Use the installed kit's monorepo shape unless local source proves otherwise; verify schema, Drizzle, app, and package paths in the installed kit.
- Use the correct auth surface for the file type: `getSession()` for server loaders, Better Auth route APIs for HTTP routes, `authenticatedActionClient` for server actions, org helpers only for org scope, and server-side admin gates.
- Choose ownership deliberately. Better Auth anonymous users are real `user` rows with `isAnonymous: true`; personal flows prefer an explicit owner key, and org ownership waits for a reviewed requirement.
- Generate/apply migrations through installed kit commands, review SQL, and never use `drizzle-kit push` or ad hoc schema mutation.
- Cross-tenant and cross-owner tests are mandatory for tenant/owner behavior: positive reads, negative attempts, and no-side-effect checks.
- Use MakerKit billing abstractions for subscriptions, portals, plan limits, and provider-neutral recurring billing; direct Stripe SDK belongs only in required one-off route-layer flows.
- Use the active adapter's cloud policy; never bake real DB credentials or auth secrets into a public image, and tie smoke evidence to build identity.
- Verify with exact project scripts. Never assume `pnpm healthcheck` covers unit tests or that green smoke proves the current deployment.

## Common Wrong Turns

- Do not assume docs from another MakerKit edition apply to the installed kit.
- Do not put Drizzle schema/migrations in a feature package when the kit uses `@kit/database`.
- Do not edit Better Auth core generated tables for app-specific fields.
- Do not use server-action clients in HTTP route handlers, org helpers for personal/guest ownership, deep package-internal imports, or project behavior inside replaceable shadcn primitives.
- Do not treat mocked Stripe webhook tests as proof that real checkout completed.
- Do not log rendered response bodies during auth/rate-limit scans; record route labels, bytes, and hit counts.
- Do not let clean review manifests hide superseded convention text; add stale-token checks after major convention corrections.

## Updating This Skill

When asked to fold in MakerKit learnings, gather named repo, adapter, plan, run-log, Dockerfile, workflow, test, doc, and review evidence. Do not mutate product repos unless explicitly asked. Add transferable lessons to `references/current-lessons.md`, use conditional references for project-specific context, and revise this entrypoint only when the core workflow changes.
