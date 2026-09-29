# Builder lanes

A **builder lane** is an autonomous build agent working in a worktree. This page is the whole
model on one page: what a builder may do on GitHub, who counts as one, and how its identity is
configured so that the limits hold at the token level rather than on trust.

Humans are never builders. Nothing on this page changes anything for a person working in the
product repo.

## The verb list

A builder lane's entire GitHub surface is these commands. There is no other approved path to the
board or to issues:

Every command takes `--target <dir>`. `board` and `issue` take `--json` for a stable envelope and
`--fresh` to bypass the five-minute board cache; `debt file` takes `--json`.

| Command | What it does | Its own flags |
| --- | --- | --- |
| `tautline board list` | The board in its own position order | `--status NAME` (repeatable; naming a hidden status also unhides it), `--type NAME`, `--label NAME`, `--text SUBSTR`, `--all` |
| `tautline board show <n>` | One card plus its issue body | the same filters, though only `--fresh` changes anything |
| `tautline board fields` | The LIVE Status / Item Type option names, so nothing has to guess a column | — |
| `tautline issue show <n>` | Body, state, labels, assignees and board status | — |
| `tautline issue comments <n>` | The thread, oldest first | `--last K` |
| `tautline issue find` | Issues by label and text | `--label L` (repeatable, filtered server-side), `--text Q` (substring over title and body, applied after the fetch), `--state open\|closed\|all` |
| `tautline issue comment <n>` | Post one stamped comment | `--body BODY` or `--body-file FILE` |
| `tautline debt file` | Create one debt issue | `--title TITLE`, `--body BODY` or `--body-file FILE`, `--refs N` (repeatable; rendered as `Refs #N`) |

Notice what is absent: **nothing here writes to the board.** A builder reads the board and writes
to issues. Moving a card, changing a status field, or editing a project is a human decision.

Two layers hold that line, and they are independent on purpose:

1. **`tautline builder-guard`** — a Claude `PreToolUse` Bash hook, plus a `gh` PATH shim for lanes
   that are not running under Claude. It refuses a builder lane's `gh` invocations that are not on
   the list above. This is the layer that gives a *useful error message*.
2. **The identity** — the subject of this page. A builder lane authenticates as a GitHub App
   installation whose permissions grant **Projects: Read-only**. A board write is refused by
   GitHub, not by us.

The second layer is the one that actually holds. A guard is a program, and a program can be
bypassed by a harness nobody anticipated; a permission cannot be talked around by anything running
on this machine. The guard exists so a lane learns *why* quickly, not so the boundary depends on it.

### What the guard allows

An **allow-list**, never a deny-list: an unknown `gh` verb is denied, so a verb GitHub ships next
year is denied without anyone having to notice it exists. The predecessor guard was a deny-list and
`gh project` walked straight through it.

| `gh` subcommand | Allowed for a builder |
| --- | --- |
| `status` | the whole subcommand |
| `pr` | every action, *minus* `--add-project` / `--remove-project` / `--project`, `--milestone`, `--add-label` / `--remove-label` / `--label` (and `-p` / `-m` / `-l` on `create` and `edit`) — a pull request is a board item, so those flags are board and label writes by another door |
| `run` | `list`, `view`, `watch`, `download` only — `delete` takes the logs a human was about to read, and `cancel` / `rerun` act on CI somebody is waiting on |
| `workflow` | `view`, `list` only |
| `auth` | `status` only — `gh auth token` prints the operator's credential, `gh auth refresh -s project` re-scopes it to *write the board* (the App is not in that path; `gh` is authenticated as a person), and `gh auth logout` destroys it |
| `search` | `prs` only — `gh search issues` reaches issues |
| `repo` | `view`, `clone` only |
| `api` | `GET` only, and only `rate_limit` and `user` *exactly* (no sub-path — `user/issues` is the issue list wearing an identity root), plus the `pulls` / `commits` / `actions` / `check-runs` / `branches` / `contents` sections of a repo. A `.` or `..` path segment is refused before the list is consulted, in any encoding, because the list is positional. `graphql` never, in any spelling |
| `release` | nothing — builders do not cut releases |
| `issue`, `project`, `label`, `milestone`, `gist`, anything unknown | nothing |

`gh repo` is split because the subcommand is too coarse to be the unit of the decision. `delete`,
`rename`, `archive` and `transfer` do not come back, and `gh repo edit` reaches **branch
protection** — which is the control fencing the App's Contents permission (see *Residual gaps*
below), so a lane able to edit it could unfence itself.

Direct HTTP is caught **by the text of the command**, and only by that: a `curl`, `wget`, `python`,
`node` (and friends) invocation whose command line contains `api.github.com` or
`github.com/graphql` is denied. That is a *string match*, not an understanding of what the program
does — a `python -c` that builds the host out of two variables reaches GitHub untouched, and so
does any client of the lane's own. It is sized for the habit (typing a `curl` at the API), not for
evasion; the App's Projects-read permission is the layer that holds against evasion.

The same reading happens **inside** a payload rather than only at the top level. A denied command
is found in `bash -c '…'`, a herestring (`bash <<< '…'`), `env -S '…'`, `find … -exec … \;`, a
`printf`/`echo` literal piped into `sh`, a `for` loop body, a command substitution, behind a
leading redirection (`2>/dev/null gh …`), and behind `xargs`/`command`/`timeout`/`env`. A payload
this guard cannot see as literal text — `python gen.py | sh`, a script written to a file and then
run — is **not** caught, and that is the boundary rather than an omission.

**The guard fails open, deliberately, on two paths.** A `PreToolUse` exit 2 is a *deny*, so a
guard that errors is a guard that blocks every Bash call in the session — for the product director
and the operator as much as for a lane. So the shipped hook command exits 0 when `tautline` is not
on PATH at all, **and** when the installed `tautline` predates the `builder-guard` verb: an older
CLI answers argparse's "invalid choice" with exit 2, which is indistinguishable from a deny unless
something asks. The hook asks — it probes `builder-guard --help` after a 2, and only after a 2, so
the allow path still costs exactly one process. A rollback or a staged upgrade therefore leaves
every human's session working, with the guard simply absent until the CLI catches up.

The hook also **captures both of the guard's streams** and replays them only once the probe has
confirmed a real deny. Passing them straight through would put an old CLI's `invalid choice`
argparse noise on every Bash call a human makes — silent about the exit code, loud about
everything else, which is the same friction wearing a different hat. On a confirmed deny the JSON
object goes to stdout and the reason to stderr, exactly as the guard wrote them.

**The `gh` PATH shim asks the same question, for the same reason.** An operator is told to leave
the shim directory on PATH, so a shim that read every exit 2 as a deny would *brick `gh`* on a
machine whose CLI predates the verb — every invocation exit 2, with argparse noise on stderr, for
the people this guard is built never to touch. The shim captures the guard's stderr rather than
passing it through, probes `builder-guard --help` after a 2, and only then prints the reason and
exits 2; on any other failure it prints nothing and execs the real `gh`.

| Surface | On `builder-guard` exit 2 | On a CLI that predates the verb |
| --- | --- | --- |
| `PreToolUse` hook | probes `--help`; a deny only if it answers | exit 0, silent — Bash keeps working |
| `gh` PATH shim | probes `--help`; a deny only if it answers | execs the real `gh`, silent |

### Residual gaps

Two things this design does **not** close, named here so nobody discovers them by accident.
**Contents: Read and write** is real write access to the repository: a builder lane's token can
push to any branch that is not protected, which is more than the verb list above suggests and more
than a lane needs for its own worktree. The control for that is **branch protection on the
integration branch** — set it there, and confirm it, because nothing in this framework enforces it
and no permission on the App can substitute for it. **Workflows: Read and write** is optional and
should be left unset unless your lanes genuinely push changes under `.github/workflows/`; granted
unnecessarily, it lets a lane edit the CI that checks its own work, which is the one permission
whose misuse is hardest to see from the outside.

## Who is a builder

`builder_role_active()` is the one answer, and it has exactly three inputs. Any of the first two
makes this lane a builder; anything else is a human.

1. **The environment variable** `TAUTLINE_ROLE=builder`.
   - Set per lane by `eval "$(tautline builder-env)"`.
   - Set machine-wide on a builder-only machine by uncommenting the example line in
     `~/.config/minervit/methodology.env`:
     ```sh
     export TAUTLINE_ROLE=builder
     ```
     `tautline install-cli` writes that line **commented out**. Uncommenting it is the operator's
     act, because it converts every lane on the machine.
   - Exported by an orchestrator. A lane orchestrator exports the same variable; there is no second mechanism
     for a launcher to learn about.
2. **The file** `.ai-work/lane-role` under the target, containing the single word `builder`.
   Written by `tautline lane-role builder`, which also makes sure `.ai-work/` is gitignored — a
   committed role marker would make every clone of that branch a builder lane, including a
   human's.
3. **Nothing**, which is a human. This is the default, and it is the default on every machine.

The environment variable **outranks the file**. `tautline lane-role human` removes the marker and
tells you so if `TAUTLINE_ROLE` is still set, because at that point the lane is still a builder and
the fix is in the shell, not in the checkout.

`tautline lane-role status` prints the role and which of the three inputs decided it. When a lane
behaves unexpectedly, that is the first thing to run.

## The GitHub App

Builder lanes share one GitHub identity per installation: `<app-slug>[bot]`. Every builder write is
attributed to it, so reading the repository tells you which writes came from a lane and which came
from a person. Which *lane* made a given write is carried separately, in the attribution trailer
each builder write appends.

### Creating it

Do this once, in the organization that owns the product repo. The examples use `example-org` and
`example-org/example-product`.

1. **Organization Settings → Developer settings → GitHub Apps → New GitHub App.**
2. **Name** it for what it is, e.g. `example-org builder`. The name becomes the slug, and the slug
   becomes the bot login `example-org-builder[bot]` that will appear on every builder comment.
3. **Homepage URL**: anything; it is required and unused.
4. **Webhook**: **uncheck "Active"**. This App is never called by GitHub — lanes call GitHub. An
   enabled webhook with no receiver is a stream of delivery failures nobody reads.
5. **Permissions** — this is the part that matters, and it is the whole security argument:

   **Repository permissions**
   - Issues: Read and write
   - Pull requests: Read and write
   - Contents: Read and write
   - Metadata: Read-only *(mandatory; GitHub selects it for you)*
   - Workflows: Read and write *(only if your lanes push changes to files under
     `.github/workflows/`; leave it unset otherwise — see* Residual gaps *above)*

   **Organization permissions**
   - Projects: Read-only

   Set nothing else. `Projects: Read-only` is what makes a board write impossible rather than
   merely discouraged. `Contents: Read and write` is the one permission on this list that is
   broader than the verb list needs; *Residual gaps* above says what fences it.
6. **Where can this GitHub App be installed?** → **Only on this account.**
7. **Create GitHub App**, then scroll to **Private keys** → **Generate a private key**. A `.pem`
   downloads. This is the credential.
8. **Install App** → your organization → **Only select repositories** → the product repo only.
   After installing, the browser URL ends in the installation id:
   `https://github.com/organizations/example-org/settings/installations/12345678` → `12345678`.
9. Note the **App ID** from the App's General settings page. It is not the installation id; both
   are needed and they are different numbers.

### Storing the key

The PEM is a credential that can mint tokens for the whole installation. Keep it **outside every
repository**, readable only by you:

```sh
mkdir -p ~/.config/minervit/keys && chmod 0700 ~/.config/minervit/keys
mv ~/Downloads/example-org-builder.*.private-key.pem ~/.config/minervit/keys/builder-app.pem
chmod 0600 ~/.config/minervit/keys/builder-app.pem
```

Never commit it, never paste it into a config file that a repo tracks, and never put the key
*material* in an environment variable — only its path.

### The three environment variables

| Variable | Value | Required |
| --- | --- | --- |
| `TAUTLINE_GITHUB_APP_ID` | The App ID from the App's settings page | yes |
| `TAUTLINE_GITHUB_APP_KEY` | Path to the PEM, mode 0600, outside any repo | yes |
| `TAUTLINE_GITHUB_APP_INSTALLATION_ID` | The installation id from the install URL | no |

They are read from the environment only, never from the committed adapter.

Leaving `TAUTLINE_GITHUB_APP_INSTALLATION_ID` unset is fine: the installation is discovered by
matching the owner half of the adapter's `project.repo` against the App's installations. Discovery
**refuses rather than guesses** when no installation matches or when more than one does, and names
the candidates it saw — minting against the wrong installation produces a perfectly valid token
with access to the wrong repositories, and that surfaces much later as a 404 on an endpoint that
looks entirely correct.

On a builder-only machine, put all three in `~/.config/minervit/methodology.env` (mode 0600) next
to the commented `TAUTLINE_ROLE` line.

### Proving the scope

This is the command that turns the security argument into evidence:

```sh
tautline builder-token --status
```

```
builder_token_source: app
builder_token_app_id: 1234567
builder_token_installation_id: 12345678
builder_token_bot_login: example-org-builder[bot]
builder_token_expires_at: 2026-09-05T13:41:22Z
builder_token_permissions: contents=write, issues=write, metadata=read, organization_projects=read, pull_requests=write
```

`organization_projects=read` is read off GitHub's own response to the token exchange, not restated
from this page. If it ever says `write`, the App's permissions were widened and builder lanes can
move the board — fix it on the App's settings page, not here.

`--status` never prints the token. `tautline builder-token --print` prints the token and nothing
else, which is what makes `GH_TOKEN="$(tautline builder-token --print)"` work.

**One of the two flags is required.** A bare `tautline builder-token` exits 2 and names them; it
does not print a token. Printing a live credential is a decision, and the shape somebody types
while exploring a new verb must not be the shape that makes it.

The token is cached at `~/.config/minervit/builder-token.json`, mode 0600, and reused until it has
less than five minutes left. Deleting that file is always safe; the next call mints a new one.

## What humans do

Nothing changes. A human working in the product repo:

- has no `TAUTLINE_ROLE` set and no `.ai-work/lane-role` file, so `builder_role_active()` is false;
- is not bound by `tautline builder-guard`, which stands down entirely for a human lane;
- keeps using their own `gh auth login` credentials, because `tautline builder-token --print`
  falls back to empty when no App is configured and the callers then fall back to `gh auth
  token`. The verbs
  resolve their credential in that order too — an exported `GH_TOKEN`/`GITHUB_TOKEN` first, then
  the App, then `gh auth token` — so an operator who exported a token on purpose is never
  second-guessed by an App;
- can move the board, edit fields, and use `gh` however they like.

A human must **never** `eval "$(tautline builder-env)"`. That command is how a lane *becomes* a
builder: it would take on the bot identity, lose the ability to write to the board, and put the
guard's `gh` shim in front of the real `gh` for the rest of that shell. It prints rather than
refuses precisely because it must work in a lane that is not a builder yet, so nothing stops a
human running it — this paragraph is what stops a human running it. If you did it by accident,
close the shell.

## Launching a builder lane

### By hand, in a worktree (Claude Code or Codex)

```sh
cd ~/worktrees/my-lane
eval "$(tautline builder-env)"
```

That snippet sets three things, and it does not change any state on disk:

```sh
export TAUTLINE_ROLE=builder
if _tautline_token="$(tautline builder-token --print)"; then
    export GH_TOKEN="$_tautline_token"
else
    echo "builder-env: no builder token; refusing to start a builder lane" >&2
fi
unset _tautline_token
_tautline_shim="$(tautline builder-guard --shim-dir 2>/dev/null)"
if [ -n "$_tautline_shim" ]; then
    export PATH="$_tautline_shim:$PATH"
fi
unset _tautline_shim
```

**Both halves are conditional because both of the obvious one-liners fail badly.**
`export GH_TOKEN="$(tautline builder-token --print)"` exports an *empty* `GH_TOKEN` if the mint
fails when the snippet runs, and an exported-but-empty `GH_TOKEN` stops `gh` falling back to your
own login — a mint failure surfacing minutes later as an opaque 401.
`export PATH="$(tautline builder-guard --shim-dir):$PATH"` puts an *empty entry* at the front of
`PATH` if that substitution fails, and an empty `PATH` entry means **the current directory**: every
command the lane runs afterwards resolves against `.` first.

When no App is configured and no `GH_TOKEN` is exported, the token block is replaced at generation
time by a comment saying so, for the same reason.

The PATH entry puts the guard's `gh` shim ahead of the real `gh`. This is what binds a **Codex**
lane, or any lane in a plain shell: Codex runs commands through the shell, so the shim is in front
of every `gh` call it makes, exactly as the `PreToolUse` hook is in front of every Bash tool call
under Claude. Same rules, two enforcement points, because the two harnesses expose different seams.

To mark the checkout instead of the shell — so the role survives a new terminal in that worktree:

```sh
tautline lane-role builder
```

Check either way with `tautline lane-role status`.

### Machine-wide

On a machine that only ever runs builder lanes, uncomment the `TAUTLINE_ROLE` line in
`~/.config/minervit/methodology.env` and put the three App variables beside it. Every lane on the
machine is then a builder, with no per-lane step at all.

### From an orchestrator

A lane orchestrator exports `TAUTLINE_ROLE=builder` and the App variables into each lane it starts. There is
nothing orchestrator-specific in this design: any launcher that exports the same variables produces
the same lane.

## Troubleshooting

| Symptom | What it means |
| --- | --- |
| `builder_token_source: none` | No `GH_TOKEN` and no App configured. Set the three variables. |
| `builder_token_source: env` | An operator token is exported and wins over the App. Unset `GH_TOKEN`/`GITHUB_TOKEN` to use the App identity. |
| `openssl is not on PATH` | Signing the App JWT needs `openssl`. Install it, or export a token instead. |
| GitHub rejected the App JWT (401) | Wrong `TAUTLINE_GITHUB_APP_ID` for that key, a revoked key, or a machine clock more than a minute fast. |
| 404 on the installation | The App is not installed there, or the installation id belongs to a different App. |
| A board write "unexpectedly" succeeds | The App's Projects permission is not Read-only. Check `--status`, then fix the App. |
| `builder_error: The builder GitHub App is configured but could not mint a token` | Exactly what it says, and the verbs refuse rather than falling back to your own `gh` credentials — a silent fallback would write to the board under *your* name. Fix the App, or unset the three variables to work as yourself. |
| Every Bash call is denied, for humans too | An installed `tautline` older than the `builder-guard` verb, on a release before the hook learned to probe for it. Upgrade, or remove the plugin's `PreToolUse` entry. |
| `builder_note: acting with a personal token, not the builder App` | This lane is a **builder** and is authenticated as a *person*, so nothing about Projects-read is being enforced by GitHub — only whatever that token happens to be scoped to. Configure the App, or accept that this lane's board limits rest on the guard alone. |

Every refusal goes to **stderr**; stdout stays the data channel, so `tautline board list > board.txt`
puts the board in the file and the failure in your terminal. Under `--json`, stdout carries a
parseable `{"error": "…"}` and the prose still goes to stderr.
