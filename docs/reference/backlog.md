# Backlog

One verb, three boards: `tautline backlog list|add|take|done` works the same whether your backlog is
a file in the repository, GitHub issues, or a Jira project.

**The configured provider is the source of truth. There is no local mirror and no sync.** Nothing
runs in the background, on a hook or on a timer; the queue moves only when one of the four commands
above is typed. When a project configures a backlog, that provider is the project's *exclusive*
backlog surface: no `BACKLOG.md`, no `TODO.md`, no deferred-items notes scattered through the repo.
File follow-ups and deferred work with `tautline backlog add`; the generated adapter says so in one
line so an agent reads it every session.

**No fallback, either.** If credentials are missing or the network is down, these commands fail with
a message naming the environment variable to set. They never quietly write a local file instead. A
silent local fallback would create a second backlog, and the thing people build to reconcile two
backlogs is a sync engine — which is exactly what this seam exists to keep out.

**And no unverified success.** A write is not reported as done because the API returned 2xx. Every
mutation is read back and has to *say* it landed — the label is present, the transition ended in the
status category it was supposed to. Partial success on these boards looks exactly like the whole
thing (an issue created without the label the queue filters on, a transition that fired on the wrong
workflow entry), so the status code is not treated as evidence.

## Configuration

The `backlog` block in `.tautline.json` (the `lean-1` contract). It is optional: a project with no
block gets the local provider with `QUEUE.md`.

```json
{ "backlog": { "provider": "local", "path": "QUEUE.md" } }
```

```json
{ "backlog": { "provider": "github", "repo": "acme/demo", "label": "backlog" } }
```

```json
{ "backlog": { "provider": "jira", "site": "https://your-team.atlassian.net",
               "project": "PROJ", "board": "12" } }
```

| key | providers | meaning |
|---|---|---|
| `provider` | all | `local`, `github` or `jira`. Required. |
| `path` | local | The queue file, relative to the repository root. Default `QUEUE.md`. |
| `repo` | github | `owner/name` of the repository whose issues are the backlog. Required. |
| `label` | github | The issue label that marks a backlog item. Default `backlog`. |
| `site` | jira | Your Jira **Cloud** site, `https://<your-team>.atlassian.net`. Required. |
| `project` | jira | The project key, e.g. `PROJ`. Required. |
| `board` | jira | A board id. Optional; it narrows the list and selects rank ordering. |

Run `tautline validate-adapter --project .tautline.json` after editing. Every value is checked before it is used:
a `site` that is not a Jira Cloud host, a `project` that is not a Jira project key, a non-numeric
`board`, a `repo` that is not `owner/name` are all refused at configuration time rather than
surfacing later as an unexplained 404. The block takes no other keys — a `token` here is refused,
not quietly accepted into a file you commit.

## Credentials

**Credentials never go in the config.** `.tautline.json` is committed to a repository; a token in it
is a token in your git history. They are read from the environment, and nowhere else.

| provider | what it needs |
|---|---|
| local | nothing |
| github | `GITHUB_TOKEN` or `GH_TOKEN`, with `issues: read/write` on the repo. If neither is set, the token from `gh auth login` is used. |
| jira | `JIRA_EMAIL` (the Atlassian account email) and `JIRA_API_TOKEN` (create one at <https://id.atlassian.com/manage-profile/security/api-tokens>). |

A missing credential is reported before any network call, and names the variable to set.

## The four commands

```bash
tautline backlog list                    # the open queue, top first
tautline backlog add "Collapse the legacy validator" --body "one page of what and why"
tautline backlog take                    # take the top item; or: take <id>
tautline backlog done <id>
```

All four accept `--target <path>` (default `.`).

`list` prints one line per open item: id, state (`ready` / `in-progress`), title. The id is what
`take` and `done` accept — a slug for local, an issue number for GitHub, an issue key for Jira.
`add`, `take` and `done` print the item's id and, where the provider has one, its URL.

`list` is the **queue**, not the archive: finished items are not in it. They are still in the
`done/` directory, the closed issue, or the Done column. It follows the provider's pagination to the
end, so a backlog longer than one page is fully counted.

## PR reference stamp

The configured provider is the source of truth for what is in progress; git history is a separate
record of what actually shipped. Nothing joins the two automatically — a PR can merge without ever
saying which backlog item it was for. `Backlog: <id>` is that join: one line, in the PR title or
body, that traces the PR back to the item it implements.

`take` prints it, filled in and ready to paste:

```
$ tautline backlog take
take: 2026-08-31-tighten-validation  Tighten input validation
Backlog: 2026-08-31-tighten-validation
Put that line in your PR's title or body -- it is how the PR is traced back to this item.
```

The generic form works for every provider. Each provider also accepts its own native form, so the
stamp can read like the reference you would write anyway:

| provider | native form (beyond the generic `Backlog: <id>`) |
|---|---|
| local | none — there is no other convention for a local slug |
| github | a GitHub closing keyword: `Closes #42`, `Fixes #42`, `Resolves #42` (bare `#42`, cross-repo `owner/repo#42`, or the full issue URL) |
| jira | a bare issue key: `PROJ-12` |

When a project's `.tautline.json` names a `backlog` provider, `scripts/check_pr_backlog_ref.py`
runs as a step in the PR workflow and fails the check when neither the PR title nor its body
carries a reference in that provider's grammar — showing that provider's forms only, never a
cross-provider list. It is deterministic and instant: one field, no network call, and no attempt
to confirm the id is real (that would need a live board). A project with no `backlog` key at all is
untouched; the check exits 0 having done nothing.

The check verifies that a reference is **present**, not that it is load-bearing: it has no
code-span awareness, so a `Backlog: <id>` sitting inside a quoted example or a code fence still
satisfies it. This is deliberate — it is a traceability reminder for an honest PR, not a
fraud-resistant gate against a dishonest one.

## What each provider does

**local** — `QUEUE.md` plus `ready/`, `building/` and `done/` directories beside it. The table row
order is the priority order and the top of the list is next; the row's link says which directory the
item's one-page spec is in, so its location and its state cannot disagree. `add` writes
`ready/<date>-<slug>.md` and appends a row; `take` moves the file to `building/`; `done` moves it to
`done/` and leaves the row as history. Rows are renumbered on every write.

**github** — open issues carrying `label`, oldest first, over the plain REST API, following the
`Link` header across every page. `add` creates a labelled issue and *checks the label came back* —
GitHub silently drops labels when the token cannot write to the repository's issues, and an item
without the label is one `list` will never show. `take` adds an `in-progress` label and assigns you;
the assignment is best-effort and reports itself when skipped, because `GET /user` is not available
to a GitHub Actions installation token. `done` closes the issue. Pull requests are never listed even
though GitHub returns them from the issues endpoint.

> The GitHub **Projects** GraphQL API is deliberately not used. Measured on 2026-08-16: one
> `gh project item-list` call cost 102 points against a 5,000-point hourly GraphQL budget, where the
> equivalent REST reads cost 1. A backlog an agent reads several times an hour must not be able to
> exhaust an adopter's quota.

**jira** — issues in `project` whose status category is not Done, ordered by rank when a `board` is
configured and by creation date otherwise. `add` resolves the project's own issue types and creates
one by id rather than guessing a name. `take` and `done` resolve a workflow transition **by name**
(`In Progress`, `Done`) down to exactly one id. Jira workflows are project-specific, so if your
project calls it `Start Progress`, the command refuses and lists the transitions that do exist — and
if two transitions share the name (a global `Done` and a status-specific one is common) it refuses
rather than firing whichever the API listed first.

> **Jira Cloud only, and not yet validated against a live site.** Jira Server and Data Center differ
> in authentication and endpoints and are refused at configuration. The Jira client was written
> against Atlassian's documentation; nothing in this repository has spoken to a real Jira instance.
> Treat it as ready to try, not as proven.

## In lane-status

When a project configures a backlog, `tautline lane-status` prints one advisory line:

```
backlog: github (acme/demo) - 4 open, top: Collapse the legacy validator
```

It is a live read on a short timeout. If the board cannot be reached it says so and why — it never
prints a count it did not measure, and it never omits itself silently:

```
backlog: jira (PROJ) unreachable (Jira credentials: environment variable JIRA_EMAIL is not set. ...)
```

The line is advisory. `lane-status` never blocks.
