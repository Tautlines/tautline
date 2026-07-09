# Privacy Policy

This methodology plugin stores no data of its own and sends **zero outbound telemetry**. It has no analytics, does not phone home, and collects no usage data in the background. The only usage ledger it keeps is **local** (JSONL plus a rollup under `$HOME/.local/state/minervit/usage`) and never leaves the machine. Any future telemetry will be **opt-in, default off**, with a published data-flow disclosure before it ships.

## Outbound data flows

Every network request the CLI makes is one **you explicitly trigger** against an endpoint **you configure** in your project adapter (e.g. the fictional `example-saas` adapter). The plugin initiates no network activity on its own and adds no tracking. Webhook URLs and credentials are read from your environment, never from committed files — adapters store env-var *names* (e.g. `"webhookEnv": "EXAMPLE_SAAS_ITERATION_REVIEW_WEBHOOK"`), not secret values.

| Destination | What is sent | Triggered by | Configured in adapter |
|---|---|---|---|
| **Google Chat webhooks** | The card content you generate — iteration-review, milestone-update, product-note, deploy-ready, and release-update cards | `publish-iteration-review`, `publish-milestone-update`, `publish-deploy-ready-update`, release-update delivery | `iterationReview.delivery.webhookEnv`, `milestoneUpdate.webhookEnv`, etc. (env-var name → URL) |
| **GitHub** | Reads/updates to issues, Projects (boards), and PR/check state | `backlog-provider`, `stakeholder-question`, `status`, board-sync commands (via the `gh` CLI and GitHub GraphQL API) | `backlogProvider` owner/project/fields |
| **Git remotes** | Your **session journals** and **RCA archive** copies, pushed to dedicated archive branches (default `methodology-rca-archive`; journals to their archive branch) | `publish-session-journal --commit --push`, `publish-pending-session-journals`, RCA publish (all require `--commit --push`) | archive branch/remote (today resolved from `remote.origin.url`) |
| **Amazon S3 / CloudFront** | The generated iteration-review page and JSON record | `publish-iteration-review` | `iterationReview.hosting.bucket` (`store: s3`, `cdn: cloudfront`) |
| **Upstream methodology repo (auto-update)** | An outbound `git pull --ff-only` fetch of the methodology checkout, followed by an in-place re-exec of the updated CLI | Lane start / `sync-methodology` | `MINERVIT_METHODOLOGY_REPO` / launcher config |

These requests carry only the content you produce and the references needed to deliver it. All other data access (local filesystem, Claude, Codex, Open Brain) comes from the host agent tools you explicitly enable; those tools are governed by their own configuration and policies.

> **Note on the auto-update fetch.** Auto-update pulls and re-executes upstream code on each lane start (`bin/minervit-methodology`, `os.execve` after `git pull --ff-only`). This is an inbound code fetch, not a data export, but operators pointed at a shared upstream should understand that running this tool means fetching and executing whatever that upstream serves. Pin or vendor your methodology checkout if you do not want unattended updates.

## Tenancy: isolation is the boundary, redaction is defense-in-depth

**Per-tenant isolation is the privacy boundary; publish-time redaction is defense-in-depth, not the boundary**.

The publish pipeline scrubs person/machine-specific tokens from session journals and RCAs before they leave the machine, but that redaction is derived from the **publishing machine's** `$USER` / `$LOGNAME` / home-dir name (`bin/minervit-methodology`, `rca_person_specific_tokens()`). A multi-account or CI publisher whose identity differs from the data's subject will under-redact, and project/lane names flow into shared archive paths and Chat cards unredacted. **Do not rely on redaction to keep one tenant's data out of another tenant's reach.**

The correct boundary is to publish each tenant's or project's journals, RCAs, and iteration-review artifacts to **that tenant's own repo/remote and S3 prefix** — not to a shared archive that co-mingles multiple tenants. Until per-tenant archive destinations are configured, treat all archived artifacts as visible to anyone with access to the shared remote and bucket.

## Retention and erasure (GDPR / CCPA)

Published journals, RCAs, and iteration-review records persist in git archive branches and in S3 until explicitly removed. To support data-subject erasure and retention obligations:

- **Purge path.** A `purge-archive` operation must be able to remove a given tenant's or project's published journals, RCAs, and usage artifacts and rewrite the corresponding `_index.md` so the removed entries no longer appear. Treat a verified purge — not redaction — as the response to an erasure request.
- **Git history.** Because archive copies live in branch history, true erasure of historical commits requires history rewrite (or, preferably, per-tenant branches/repos that can be deleted wholesale). Per-tenant isolation is what makes erasure tractable.
- **S3 lifecycle.** Configure an S3 **lifecycle policy** on the iteration-review bucket to expire or transition objects after your declared retention window, and enable versioning + a matching noncurrent-version expiration so deletions are not silently undone by retained versions. Document the retention window alongside the bucket configuration.
- **No silent secondary copies.** The tool keeps no hidden remote copy beyond the archive branches and S3 objects named above and the local-only usage ledger; purging those locations plus your own backups is sufficient.

When this tool is operated on behalf of more than one tenant, the operator is the data controller for the archived artifacts and is responsible for honoring access, retention, and erasure requests against the destinations configured in their adapter.

## Secrets

Credentials and webhook URLs are read from environment variables named by the adapter, never from committed files. Avoid passing secret webhook URLs on the command line; prefer the env-var-name indirection so secrets do not land in the process table, shell history, or logs.
