# MakerKit Implementation Policy Reference

This reference keeps the detailed MakerKit-specific implementation playbook behind the concise `makerkit-implementation` entrypoint. Read it in full before any MakerKit implementation, port, package/import/export decision, auth/session/ownership/tenant/billing/data/migration/deployment/verification/healthcheck/smoke change, or skill refresh.

This is generalized public-stack guidance for an example/community stack pack. Do not add proprietary MakerKit code, customer names, account IDs, live hosts, private adapter paths, or project-specific infrastructure details.

## Core Posture

Treat MakerKit as the owned SaaS platform, not a blank Next.js app.

- Start with the product boundary: decide which stock SaaS features stay enabled, which are disabled, and which are replaced by domain-specific flows.
- Configure or extend MakerKit-provided auth, accounts, organizations, billing, admin, database, UI, and navigation before rebuilding them.
- Keep route, UI, database, auth, billing, and feature-package boundaries explicit so packages do not grow cycles.
- Preserve the existing production or legacy app until the source-of-truth plan explicitly authorizes cutover.
- Write executable behavior, route-contract, owner/tenant-isolation, or billing tests before exposing customer, operator, auth, billing, account, or tenant behavior.
- Implement narrow, reviewed increments. Split plans when review repeatedly finds new cross-cutting security, tenancy, billing, or deployment findings.

## Package And File Boundaries

Use the installed kit's monorepo shape unless local source proves otherwise:

- `apps/web`: main Next.js app, routes, loaders, server actions, env handling, middleware/proxy, shell, product UX, direct provider SDK calls needed by routes.
- `apps/e2e`: Playwright/browser-level tests.
- `packages/database`: Drizzle schema, migrations, DB utilities, database exports, data test utilities.
- `packages/better-auth`: Better Auth server/client configuration.
- `packages/action-middleware`: `next-safe-action` auth and authorization middleware.
- `packages/rbac`, `packages/auth`, `packages/organization/*`, `packages/admin`: role policy, admin gates, account/org behavior.
- `packages/billing`: MakerKit billing abstractions, subscription and portal integration.
- `packages/ui` and `@kit/ui`: shared UI primitives and public UI exports.
- `packages/<feature>`: project domain logic, pure modules, data-access wrappers, entitlement checks, and feature exports.

Schema usually belongs in `packages/database/src/schema/schema.ts`. Better Auth core tables may live in `packages/database/src/schema/core.ts`; do not edit generated or kit-owned core tables for app-specific behavior. Extend or override in app schema files and re-declare relations there when needed.

Drizzle config usually lives at `packages/database/drizzle.config.mjs`, with schema and migration output under `packages/database/src/schema/`. Verify this in the installed kit.

In `packages/ui`, keep upstream shadcn primitives replaceable. Put project-specific wrappers, variants, or extras in the local public UI layer, update `packages/ui/package.json` exports, and import public APIs as `@kit/ui/<name>`.

## Auth And Ownership

Use the correct auth surface for the file type:

- Server components and app loaders may use `getSession()` from `@kit/better-auth/context` when the installed kit provides it.
- HTTP route handlers use Better Auth route-handler session APIs, commonly `auth.api.getSession({ headers: requestHeaders })`, where `requestHeaders` comes from `await headers()` or request headers.
- Server actions use `authenticatedActionClient` from `@kit/action-middleware`.
- Organization-scoped actions use `organizationActionClient` or the kit's organization helpers.
- Admin gates use kit admin helpers or the local server-side admin-role export, not client-side checks.

Choose ownership deliberately:

- For personal/guest-first SaaS flows, do not invent a separate guest table unless the plan explicitly decides that.
- Better Auth anonymous users are real `user` rows with `isAnonymous: true`; a personal account is still a `user`.
- For launch-owned personal flows, prefer a required `owner_user_id text REFERENCES "user"(id)` style owner key over nullable mixed-owner models.
- Add organization ownership later only when the source-of-truth plan requires shared org/team behavior.
- A kit super-admin grant can hide an incorrect domain-role gate. Include a synthetic principal with kit super-admin but without the domain role when proving domain access gates.
- Public/signup/account/org/billing/payment lockdown must cover unauthenticated users, signed-in roles, direct POST/server-action endpoints, redirect destinations, and side effects.

When linking anonymous users to permanent accounts, verify the installed Better Auth version/source. If the anonymous-user cleanup hook can run after sign-up or sign-in, make the re-key idempotent, preserve rows until re-key succeeds, reconcile old-owner rows, and return structured completion status for callers that need proof.

## Data And Migrations

Use migrations only for reviewed product work.

- Generate with the installed kit command, commonly `pnpm --filter @kit/database drizzle:generate`.
- Review generated SQL before applying.
- Apply with the installed kit migrate command, commonly `pnpm --filter @kit/database drizzle:migrate`.
- Do not use `drizzle-kit push` or ad hoc schema mutation for reviewed product work.
- Use text IDs for MakerKit/Better Auth compatibility unless local source or the plan proves otherwise.
- Add indexes for foreign keys and common owner/tenant/query paths.
- Keep every domain row tenant-owned or owner-owned unless the table is explicitly global, public, or root tenant/account metadata.

Cross-tenant and cross-owner tests need positive fixture reads first, then negative read/write attempts with baseline plus post-call no-side-effect checks. Empty-tenant denials are weak evidence.

Separate destructive migration tests from normal unit tests:

- Use a dedicated test database URL.
- Reject unset, malformed, fallback, or production-equivalent test URLs before SQL executes.
- Require a narrow test database name regex.
- Run destructive tests serially.
- Reset migration journal state when replaying migrations from scratch.

## Porting Legacy Apps

Port by phase, not by enthusiasm.

1. Foundation and findings ledger.
2. Schema and migration parity.
3. Owner-scoped or tenant-scoped data-access layer.
4. Pure logic and support-library port.
5. API routes and route-backed integration tests.
6. Server-rendered readers/loaders.
7. Workflow UI.
8. Billing core.
9. Conversion, subscription, and billing UI.
10. Security, trust, hardening, and launch.
11. Product polish and deferred feature backlog.

When porting working logic, keep pure modules byte-identical where practical. Allow only import-path rewrites or known type-system boundary rewrites, prove behavior with existing unit suites, use a gold-copy or known-output oracle for calculation/report workflows, and run an import-graph completeness check so no live in-scope support module is silently omitted.

## Billing

Use MakerKit billing abstractions for subscriptions, portals, plan limits, and provider-neutral recurring billing.

Use direct Stripe SDK only when a required one-off payment flow is not covered by MakerKit's billing abstraction, and keep direct Stripe usage in the app/route layer. Do not import Stripe or billing provider packages from the feature/domain package if that would create a package cycle.

For one-off guest checkout:

- Require an owned, report-ready case before creating checkout.
- Create or reuse a pending reservation so retries return the same session when appropriate.
- Verify signed webhooks.
- Grant durable entitlement idempotently by stable payment key, not raw event id only.
- Make owner-first access checks before entitlement/subscription checks.
- Return 404 for foreign-owned case access when existence should not be disclosed.
- Revoke on full refund or explicit dispute, not on partial refund.

## Cloud Deployment Defaults

Use the active adapter's cloud policy. Pick a concrete provider only when the adapter declares one; the defaults below describe a common container-service + registry + managed-database shape (one example MakerKit deployment uses a managed container service, a container registry, and a private managed Postgres database).

- Prefer private Postgres reachable only from the app runtime path or a VPC-attached migration job.
- Treat a static/SSR preview host as good only when its network model fits. Do not assume a managed SSR host can reach a private managed database.
- For a managed container service, pin images to `linux/amd64`, use a registry base image (or a registry mirror) when public-registry rate limits are likely, and verify service health plus app-level smoke.
- Keep build-time placeholders separate from runtime secrets. Never bake real DB credentials or auth secrets into a public image.
- Surface build identity through a health endpoint, footer, startup log, or image tag so feedback and smoke evidence tie to a concrete version.
- Do not assume a slim standalone runtime image includes pnpm, Drizzle config, or migration files. Run migrations through an explicit deploy step, VPC-attached job, or intentionally designed entrypoint.

## Plans, Findings, And Deferrals

For recurring MakerKit ports, maintain one conventions section in the goal plan and make phase plans reference it. Do not let each phase invent paths, auth models, schema layout, ID types, or gate commands.

A foundation findings ledger should record installed kit name/version, package manager, workspace shape, app/package/schema/migration paths, public package exports, auth/session patterns by surface, owner or tenant model, DB env var names and redacted shapes, test DB safety regex, exact gate commands, and known deferrals with destinations.

Deferrals need a named destination. Product-scope deferrals belong in the product backlog. Accepted review findings belong in a review-finding backlog with file/line, observed risk, recommended fix, why deferral is acceptable, and discovery tag.

## Verification

Use the exact scripts recorded by the project. Do not assume `pnpm healthcheck` covers tests; in observed kits it ran typecheck/lint/format-style tasks but did not run unit tests, and some healthcheck scripts can mutate generated files.

For MakerKit work, verification usually includes typecheck, lint/format as configured, unit tests, database or migration tests, build, and app/browser verification for UI work. For route, data, migration, auth, and billing work, include tests that exercise unauthenticated, owner, foreign-owner, and relevant role-gated cases.

Validate both local behavior and the deployed shape when deployment or route exposure changes. Capture build identity in smoke evidence; a green check against an old deployment is a failed deploy signal, not success.

## Common Wrong Turns To Avoid

- Do not assume docs from another MakerKit edition apply to the installed kit.
- Do not put Drizzle schema or migrations in a feature package when the kit puts them in `@kit/database`.
- Do not edit Better Auth core generated tables for app-specific fields.
- Do not use server-action clients in HTTP route handlers.
- Do not use organization helpers for personal/guest ownership unless the feature is actually org-scoped.
- Do not deep-import package internals from consumers.
- Do not customize replaceable shadcn primitives for project behavior.
- Do not treat mocked Stripe webhook tests as proof that a real checkout completed.
- Do not dump rendered response bodies into logs when scanning auth or rate-limit surfaces; record route labels, byte counts, and hit counts.
- Do not let a clean review manifest hide superseded convention text; add stale-token checks after major convention corrections.

## Updating This Skill

When the user asks to fold in new MakerKit learnings:

1. Gather evidence from the named repos, adapters, plans, run logs, Dockerfiles, workflows, tests, docs, and review findings. Do not mutate product repos unless the user explicitly asks.
2. Collate overlapping local and external-lane material; keep the instruction that is more reusable, more concrete, better verified, and less project-specific.
3. Add only transferable lessons to `current-lessons.md`. Use a separate reference for project-specific deep context that future agents should load conditionally.
4. Revise `SKILL.md` only when the core workflow changes.
5. Validate the skill with the skill validator and run the methodology validation required by the adapter before handing off.
