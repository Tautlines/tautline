# Current MakerKit Lessons

This is the living evidence-backed reference for MakerKit work. Keep it concise and update it when future MakerKit projects teach a reusable lesson. The snapshots below are anonymized worked examples (an "Example SaaS" app and an "Example Engine" SaaS port), not customer-specific records.

## Evidence Snapshot

- Example SaaS adapter: a MakerKit dev target ran on a managed container service, a container registry, a private managed Postgres database, a VPC connector, a secrets manager, `linux/amd64` images, and build identity through image tags.
- Example SaaS kit: MakerKit `next-drizzle-saas-kit-turbo` v1.6.0, pnpm 11, Turbo, Next.js standalone app at `kit/apps/web`, Drizzle/Postgres in `packages/database`, Better Auth, next-intl, next-runtime-env, shadcn/MakerKit UI packages.
- Example SaaS Dockerfile: Node 22 was required for pnpm 11.4.0; the container service needed x86_64; a registry base image avoided public-registry anonymous 429s; migrations were intentionally excluded from the slim runtime image.
- Example SaaS planning/review: broad MakerKit foundation plans repeatedly found new P1s until split by concern: infra/schema, seed/auth, app mount/access-control, scheduler/identity/harness.
- Example Engine SaaS port: MakerKit `next-drizzle-saas-kit-turbo` v1.7.1, Next.js 16, React 19, TypeScript, Better Auth 1.6.x, Drizzle/Postgres, Tailwind CSS 4, Base UI, Lucide, pnpm 11.5.0, Turborepo, with the MakerKit workspace under `saas/`.
- Example Engine SaaS port: repeated plan reviews converted a broad legacy-to-SaaS roadmap into phase plans for foundation, schema, data access, pure logic, routes, readers, workflow UI, billing, conversion/subscription UI, trust hardening, and polish.
- Example Engine evidence: a Next.js + Prisma/SQLite app taught a transferable workflow rule: the application enforces stages, gates, calculations, and QA; the LLM assists but does not own correctness.

For deeper Example Engine conventions and phase lessons, read `example-engine-g10-makerkit.md`.

## Kit Orientation

- Treat MakerKit as a monorepo, not a single Next app. Make changes at the package boundary that owns the behavior.
- Use the kit's local docs first: project structure, installation, configuration, database, Better Auth, security, production, billing, and testing.
- Read package-local `AGENTS.md` / `CLAUDE.md` nearest the files being touched. In observed kits, database, UI, and web app packages each carried important local rules.
- Catalog/workspace dependencies are intentional. Avoid ad hoc package version edits that break pnpm catalogs or manypkg expectations.
- `pnpm healthcheck` in one observed kit ran typecheck/lint/format-style tasks but did not run unit tests. Treat healthcheck scripts as project-specific and inspect before relying on them.

## Architecture And Porting Lessons

- Do not let an LLM be the workflow engine. The Example Engine's useful pattern is "AI-assisted front half, deterministic back half": code enforces required fields, state transitions, calculations, QA checks, persistence, and report generation.
- Use structured extraction or explicit schemas for AI-assisted intake. Avoid prose parsing as a correctness boundary.
- Keep math, retrieval, report assembly, and data provenance deterministic and auditable.
- Put product-specific domain logic in a feature package under `packages/<feature>` and import it by package name.
- Keep direct provider SDK calls, route handlers, and UI integration in `apps/web` unless the installed kit has a different public abstraction.
- For long MakerKit foundation goals, split early by risk domain. Access-control, owner/tenant isolation, schema, data access, route exposure, billing, and deployment deserve focused plans and review loops.
- Porting phase boundaries that worked: schema vs data access, pure logic vs routes, routes vs server-rendered readers, one-off billing core vs conversion/subscription/UI.
- When a plan contains corrected conventions, add stale-token checks for known wrong words so old assumptions cannot quietly return.

## Package Boundary Lessons

- `apps/web` owns route handlers, loaders, server actions, env handling, middleware/proxy, shell, product UX, direct provider SDK usage, and runtime integration.
- `packages/database` owns Drizzle schema, migrations, DB utilities, and database exports. Do not place Drizzle schema/migrations in a feature package when the kit centralizes them in `@kit/database`.
- `packages/better-auth` owns Better Auth configuration. Do not edit generated or kit-owned core auth tables for app-specific fields.
- `packages/action-middleware` owns server-action auth middleware. Do not use server-action clients in HTTP route handlers.
- `packages/ui` owns shared primitives and public UI exports. Keep upstream shadcn primitives replaceable and put project-specific wrappers in exported project UI modules.
- `packages/<feature>` owns pure domain logic, data-access wrappers, entitlement checks, support modules, and feature exports. Avoid importing `@kit/auth`, direct Stripe SDKs, or app route modules into feature packages when that would create cycles.

## Auth, Ownership, And Isolation Lessons

- Root tenant tables may be the only domain tables without tenant or owner keys; every other domain table should carry a key and enforce it in repository/query paths.
- For personal/guest-first SaaS flows, prefer a required `owner_user_id text REFERENCES "user"(id)` owner model over nullable mixed owner models unless the plan explicitly chooses organizations or shared accounts.
- Better Auth anonymous users are real `user` rows with `isAnonymous: true`. Guest-to-permanent conversion is an owner re-key, not a move from a separate guest table.
- If Better Auth link-account hooks run after sign-up/sign-in transactions, make anonymous-to-permanent re-key idempotent and reconciled. Preserve anonymous rows until the re-key is proven complete.
- Cross-tenant and cross-owner tests need positive fixture reads first, then negative read/write attempts with baseline plus post-call no-side-effect checks. Empty-tenant denials are weak evidence.
- Test both directions when a privileged pilot actor and an isolation actor exist.
- A kit super-admin grant can hide an incorrect domain-role gate. Add a test or helper-contract proof for a synthetic principal that has kit super-admin but lacks the domain role.
- Public/signup/account/org/billing/payment lockdown must cover unauthenticated users and signed-in roles, direct POST/server-action endpoints, redirect terminal destinations, and side effects.
- Enumerate admin/super-admin capability candidates globally before classifying scan roots. A hidden handler outside the expected folder is itself a coverage finding.

## Drizzle And Migration Lessons

- Use migrations only. Generate with the kit command, review generated SQL, and apply with the kit migrate command.
- Do not use `drizzle-kit push` or ad hoc schema mutation for reviewed product work.
- Use MakerKit/Better Auth compatible text IDs unless local code or the source-of-truth plan proves otherwise.
- For Postgres 16, `gen_random_uuid()` is built in; do not add `CREATE EXTENSION pgcrypto` solely for UUID generation.
- Add indexes for every foreign key and common owner/tenant/query path.
- Metadata-parity tests can prove scalar columns, defaults, nullability, FKs, unique constraints, and indexes. Live migration smoke tests are still needed for SQL runtime behavior.
- Drizzle runtime metadata may include behavior, such as update timestamps, that pure migration introspection does not prove.
- Destructive migration tests need a dedicated test database URL, strict URL guards, anchored test database name regex, serial execution, and migration journal reset when replaying from scratch.
- Preview database patterns require runtime proof, not only build proof. A PR build may migrate one schema while the deployed runtime reads another if env routing is wrong.

## Billing Lessons

- Use MakerKit billing abstractions for subscriptions, portals, plan limits, and provider-neutral recurring billing.
- Direct Stripe SDK use is acceptable for one-off payment flows only when MakerKit abstractions do not cover the required flow. Keep direct Stripe usage in app routes or route-adjacent services.
- One-off checkout should require an owned, report-ready case before any Stripe call.
- Existing active entitlement should short-circuit checkout creation; existing pending reservation should return the same session URL when appropriate.
- Webhooks must be signed and idempotent. Grant durable entitlement by stable payment key, not raw event id only.
- Entitlement access checks should owner-scope first, then check entitlement or subscription.
- Return 404 for foreign-owned case access when existence should not be disclosed.
- Duplicate paid sessions should produce one entitlement plus remediation or refund.
- Full refund or explicit dispute revokes; partial refund does not normally revoke.
- Mocked webhook tests do not prove a real `cs_test_*` checkout completed.

## Branding Lessons

- Treat old MakerKit branding as a release-visible leak unless it is an internal, non-rendered import path or source comment.
- Use source-side and deployed-surface scans. One Example SaaS deployment used both a reachable-source zero-MakerKit gate and a deployed body/asset scan with multiple clean sweeps to tolerate container-service rollover.
- Do not dump rendered response bodies into logs when scanning auth or rate-limit surfaces; record route labels, byte counts, and hit counts.

## Deployment Lessons

- For App Runner, build `linux/amd64`; App Runner is x86_64-only. Apple Silicon local builds can produce the wrong architecture if not pinned.
- Prefer `public.ecr.aws/docker/library/node` as the base image when shared CI egress may hit Docker Hub anonymous pull limits.
- Match Node to the kit's package manager and runtime requirements. In one observed kit, Node 22 was needed because pnpm 11 used Node features unavailable in Node 20.
- Set `output: 'standalone'` for the web app before building a slim container image.
- Use `turbo prune web --docker` or equivalent pruning to reduce build context while preserving workspace packages needed by `apps/web`.
- Force `HOSTNAME=0.0.0.0` at runtime for Next standalone when the platform injects a container hostname.
- BusyBox tools in Alpine images differ from GNU tools; healthchecks should use flags supported by the base image.
- A liveness endpoint such as `/api/healthcheck` only proves the app process is up unless it intentionally queries the database. Verify DB connectivity separately through an authenticated path or VPC-attached smoke.
- Keep the existing preview/wireframe deployment untouched when standing up a separate MakerKit dev site. Record baseline deploy settings and route table before provisioning a sibling target.

## Environment Lessons

- `NEXT_PUBLIC_SITE_URL` and other `NEXT_PUBLIC_*` values can be inlined by Next.js at build time. Passing them only at runtime may leave stale client URLs.
- `next-runtime-env` helps only for code paths that actually read through it. Direct readers such as billing return URLs, invitations, auth redirects, or static config may still need a build-time value.
- Use non-secret build placeholders for env values that are parsed at build but never connected to, then inject real secrets at runtime through Secrets Manager or the platform secret mechanism.
- Do not set `NEXT_PUBLIC_CI=true` in production images. In the observed kit it disabled rate limiting and dev storage behavior.
- Use unique auth secrets per environment and keep real provider secrets disabled or no-op in dev environments unless the milestone explicitly configures them.

## Validation Lessons

- Behavior specs should be authored before app-surface or access-control implementation when routes become public.
- Direct endpoint probes must be valid requests with the right method, payload, CSRF/server-action headers, and session state. Malformed-request failures do not prove the boundary.
- For denied mutation probes, verify no rows or auth artifacts were created or changed.
- Capture build identity in smoke evidence. A green check against an old deployment is a failed deploy signal, not success.
- Local gates for MakerKit should include typecheck, lint/format as configured, unit tests, database tests, and build. Do not assume a single kit healthcheck command covers all of them.
- For UI work, verify with the app/browser. For route, data, migration, auth, and billing work, include tests that exercise unauthenticated, owner, foreign-owner, and relevant role-gated cases.
