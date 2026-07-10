# Example Engine MakerKit Port Lessons

Use this reference when working on the Example Engine SaaS MakerKit port (an anonymized worked example) or when generalizing its lessons into the methodology.

## Evidence Classes

The lessons came from the Example Engine goal plan, strategic roadmap, Phase 0 findings ledger, MakerKit workspace guidance, database package guidance, UI package guidance, web app guidance, and reviewed phase plans for foundation, schema, data access, pure logic, routes, readers, workflow UI, guest billing, conversion/subscription UI, self-serve UX, security hardening, and polish.

Keep future updates evidence-backed, but do not copy machine-local checkout paths into this reusable skill.

## Installed Kit Snapshot

The Example Engine Phase 0 used `makerkit/next-drizzle-saas-kit-turbo`, version `1.7.1`.

Core stack:

- Next.js 16 App Router and RSC.
- React 19 and TypeScript.
- Better Auth for auth, sessions, anonymous users, accounts, subscriptions, and multi-tenancy.
- Drizzle ORM with PostgreSQL.
- Tailwind CSS 4, Base UI, Lucide React.
- pnpm 11.5.0 and Turborepo.

Workspace map:

```text
saas/
  apps/web
  apps/e2e
  apps/dev-tool
  packages/better-auth
  packages/auth
  packages/action-middleware
  packages/database
  packages/ui
  packages/rbac
  packages/admin
  packages/billing
  packages/example-engine
  tooling/*
  turbo/*
```

## Locked G10 Conventions

The goal plan's conventions became the cross-plan authority after multiple review/reconciliation rounds.

1. MakerKit workspace is in-repo at `saas/`.
2. Main app is `saas/apps/web`.
3. Ported engine feature package is `saas/packages/example-engine`, imported as `@kit/example-engine`.
4. SaaS docs/findings/manual-smoke evidence live under `docs/saas/`.
5. Drizzle schema and migrations live in `@kit/database`, under `saas/packages/database/src/schema/`, not in the engine feature package.
6. Better Auth core table source is `core.ts`; app schema and extensions are in `schema.ts`.
7. ID columns use Postgres `text`; primary key `id` columns may default to `gen_random_uuid()::text`; foreign keys and owner columns have no default.
8. Postgres 16 has `gen_random_uuid()` built in, so `CREATE EXTENSION pgcrypto` was a stale convention and must not return.
9. Personal/guest owner key is `owner_user_id text REFERENCES "user"(id)`.
10. Anonymous guest is a Better Auth `user` with `isAnonymous=true`.
11. Guest to permanent account conversion is a re-key from anonymous user id to permanent user id.
12. Organizations/per-seat/RBAC are deferred product scope, not launch-owner schema.

## Auth Surfaces

HTTP route handlers:

```typescript
import { auth } from '@kit/better-auth';
import { headers } from 'next/headers';

const requestHeaders = await headers();
const session = await auth.api.getSession({ headers: requestHeaders });
```

Return `401` if `!session?.user`. Owner-filter with `session.user.id`.

Server components/loaders can use:

```typescript
import { getSession } from '@kit/better-auth/context';
```

Server actions use:

```typescript
import { authenticatedActionClient } from '@kit/action-middleware';
```

Use `ctx.user` and `ctx.session` there. Do not use `authenticatedActionClient` for `app/api/**/route.ts` route handlers.

The installed Better Auth anonymous plugin required adding `isAnonymous` to the `user` table and adding `anonymousClient()` client-side. Source inspection showed `onLinkAccount` running from an after-hook outside the sign-up/sign-in transaction. Therefore the conversion contract is idempotent re-key plus reconciliation, with `disableDeleteAnonymousUser: true`.

## Database Layout

The Example Engine kit Drizzle config:

```text
saas/packages/database/drizzle.config.mjs
schema: ./src/schema/schema.ts
out: ./src/schema
dialect: postgresql
dbCredentials.url: DATABASE_URL or local 54333 default
```

Important package-local rules:

- Add app schema to `src/schema/schema.ts`.
- Do not modify Better Auth relations in `core.ts`.
- Add indexes for FKs and common query paths.
- Prefer explicit columns over broad selects.
- Verify ownership on reads and writes.
- Use transactions for multi-step writes.

Phase 0 extended `user` in `schema.ts` rather than modifying `core.ts`. Because both `core.ts` and `schema.ts` had `user` table objects, `schema.ts` re-declared relation exports so relations close over the extended `user`.

## Test And Gate Commands

Phase 0 findings recorded these exact MakerKit workspace gates:

```bash
pnpm install --frozen-lockfile
pnpm run lint
pnpm run typecheck
pnpm run test:unit
pnpm --filter web test:migration-smoke
pnpm run build
```

Lane-wrapped form:

```bash
minervit-methodology lane-run --target . -- cd saas && <command>
```

Legacy untouched gate:

```bash
minervit-methodology lane-run --target . -- cd phase3/eas-app && npm run lint && npx tsc --noEmit && npm test && npm run build
git diff --quiet -- phase3/eas-app
```

The default `test:unit` uses PGlite and excludes destructive `*.smoke.test.ts` files. Migration smoke uses a separate config and serial runner:

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54340/eas_test \
  pnpm --filter web test:migration-smoke
```

Guard destructive tests with:

- `TEST_DATABASE_URL` set and parseable.
- No fallback to `DATABASE_URL`.
- Raw test URL differs from raw dev/prod URL.
- Parsed test DB name differs from parsed dev/prod DB name.
- Parsed test DB name matches `^eas_test(_[a-z0-9]+)?$`.
- Zero SQL before guard failure.
- Drop the Drizzle journal schema before replaying migrations from scratch.

## Phase Breakdown That Worked

The original roadmap had seven phases. Review pressure expanded it into twelve reviewed phase plans plus the goal spine:

1. P0: MakerKit foundation and guest-checkout spike.
2. P1a-1: Engine Drizzle schema and baseline migration.
3. P1a-2: Owner-scoped data-access layer and test harness.
4. P1b-1a: Pure logic, support libs, package setup, pure gold-copy oracle.
5. P1b-1b: API routes, auth boundary, route-backed gold oracle.
6. P1b-2: Server-rendered engine readers/loaders.
7. P2: Workflow UI port.
8. P3a: Server-only guest billing core.
9. P3b: Guest conversion, subscription, and billing UI.
10. P4: Self-serve product UX.
11. P5: Security, trust, launch hardening.
12. P6: Polish and feature backlog port.

Plan-review cap lessons:

- Split schema from access.
- Split route/logic from server-rendered readers.
- Split pure logic from routes.
- Split one-off billing core from conversion/subscription/UI.
- When P0/P1 plans carry stale conventions, reconcile and re-review them, then add fail-closed stale-token gates.

## Porting Lessons

Pure logic:

- Keep pure modules byte-identical where practical.
- Normalize only intentional import-source tokens.
- Port the full transitive Prisma-free import closure, not only obvious files.
- Add a checksum or `git diff --no-index` gate for the byte-identical set.

Schema:

- Translate every scalar column, default, nullability, FK, unique constraint, index, and runtime `$onUpdate` semantics.
- Use one metadata-parity test over Drizzle table metadata.
- Use one migration-parity smoke test over a live Postgres DB.
- Do not expect migration introspection to prove Drizzle runtime metadata such as `$onUpdate`.

Data access:

- Make the owner-scoped module the one table-reaching entrypoint for owner data.
- Express access classes explicitly: owner-scoped authenticated data, role-gated moderation, deliberate public/global reads, and ops/test health.
- Type insert/update helpers so callers cannot supply `ownerUserId`, owner-defining parent FKs, `id`, or helper-assigned `seq`.
- Strip those keys at runtime too, for cast-in inputs.
- Seed foreign-owner tests and same-owner child-inheritance tests.

Routes:

- Use `auth.api.getSession({ headers })` for API route handlers.
- Return 404 for foreign-owned entities when existence should not be disclosed.
- Keep no-session 401 contracts explicit.
- Run cross-route suites and route-backed gold oracle after pure oracle.

Support modules:

- Classify source suites by import graph, not raw text.
- Port support modules needed by routes and their DB-free suites.
- Normalize import path rewrites only.
- Watch MakerKit web app aliases; the Example Engine had `@app/*`, not legacy `@/*`.

## Billing Lessons

P3a decided that MakerKit billing abstractions were right for subscriptions and portals, while the one-off pay-per-analysis flow needed direct Stripe SDK use.

Boundary:

- `@kit/example-engine` owns DB/data-access/pure entitlement logic.
- App routes own `@kit/billing-stripe/client` usage, webhook verification, checkout session creation, and refund calls.
- `@kit/example-engine` must not import `@kit/auth` or `@kit/billing-stripe`.

One-off checkout contract:

- Checkout-create requires an owned, report-ready case before any Stripe call.
- Existing active entitlement returns `409`.
- Existing pending reservation returns the same session URL.
- Webhook grants by stable payment key and raw event id.
- No-reservation paid events grant only after price/currency, report-ready, and owner metadata match checks.
- Duplicate paid sessions grant one entitlement and trigger remediation/refund.
- `POST /api/report` and download routes both check `hasReportAccess`.
- `hasReportAccess` first owner-scopes the case, then checks entitlement/subscription.
- Full refund or dispute revokes; partial refund does not.

## Deferral Routing

Use two buckets:

- Product deferrals: `G10-PL`.
- Accepted review findings: `P1-08`.

Accepted review finding entries need file path, line, observed risk, recommended fix, why deferral is acceptable, and discovery tag.

## Known Stale/Wrong Assumptions From Earlier Drafts

- `createOrgAuthContext()` was treated as an account-scoping default too early; the launch model became personal/guest owner scoping via `owner_user_id`.
- Drizzle schema/migrations were briefly described as living in `saas/packages/example-engine`; corrected to `saas/packages/database/src/schema/`.
- `CREATE EXTENSION pgcrypto` was carried forward after Postgres 16 made `gen_random_uuid()` available without it.
- Route handlers were briefly described as using `authenticatedActionClient`; corrected to direct `auth.api.getSession({ headers })`.
- The Phase 0 real Stripe checkout criterion was deferred, not proven by mocked webhook tests.
- A clean manifest does not prove convention freshness if the plan body itself contains stale conventions; add stale-token checks.

## Official Docs Checked During Extraction

Verify current docs again before acting, but these were the relevant doc families during extraction:

- MakerKit Next.js Drizzle project structure.
- MakerKit Drizzle config and schema docs.
- MakerKit authentication overview.
- MakerKit billing overview.
- Better Auth anonymous plugin docs.
