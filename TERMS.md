# Terms of Use

This methodology is provided under the **MIT License** (`LICENSE`), **"as is" and without
warranty of any kind**, express or implied. To the extent permitted by law, the authors and
copyright holders are not liable for any claim, damage, or other liability arising from your
use of the software. Nothing here adds a warranty or support obligation the license does not
grant.

These terms are not boilerplate: this tool **executes code on your machine** and **drives AI
coding agents**. The sections below state what you are responsible for when you adopt it. The
running example throughout is the fictional `example-saas` adapter. The CLI is invoked as
`minervit-methodology`.

## 1. Your responsibility for agent actions and spend

- **You are responsible for what the agent does.** The framework orchestrates an AI agent
  (e.g. Claude, Codex) that reads, writes, and executes code in your repositories, installs a
  launcher and git hooks, and can push branches and update boards. You own the outcomes of
  those actions — review them as you would any change to your systems.
- **You are responsible for model spend.** The tool calls whatever agent and model runtime
  *you* configure under *your* account and API keys. It does not cap or meter usage; token and
  compute costs are billed to you by your provider. Enforcement rigor is intended to be
  adapter-tunable so you can trade strictness against spend.
- **You configure all outbound endpoints.** Git remotes, GitHub, and any chat/notify webhook
  are taken from your adapter and environment. The framework only contacts what your adapter
  declares (see `PRIVACY.md`).

## 2. `--dangerously-skip-permissions` is an expert opt-in

The generated launcher can be installed to pass `--dangerously-skip-permissions` to the agent,
which **disables the agent's interactive permission prompts**. This is **not the default** and
is **not** the recommended mode.

- Enable it only on a machine and against a checkout you fully trust, with deliberate intent
  (`install-claude-launcher --dangerously-skip-permissions`).
- Combined with auto-update (below), skipping permissions widens the blast radius of any
  upstream compromise. The intended hardening refuses to skip permissions when the upstream is
  unverified. See `SECURITY.md` for the full risk model.

## 3. Auto-update trust model

On lane start the CLI can pull from your configured methodology upstream and **re-execute the
updated code in place**. Adopting auto-update means **granting that upstream the ability to run
code as your user**.

- Today, consumption is the live git working tree of a checkout you control; verify-before-exec
  signing/pinning is in progress, so **only enable auto-update against an upstream you fully
  control**. You can pin or skip the update path operationally.
- The target trust model — required before any public release — is to run the updated code only
  when it is a **signed and/or pinned upstream** (a signed commit from an allowlisted key, a
  signed release tag, or a config-pinned hash), and to **fail closed** otherwise.

See `SECURITY.md` ("Auto-Update Safety") for the authoritative statement.

## 4. Trademark and name

**The MIT License covers the copyright in the code. It does not license the "Minervit" name.**
MIT grants broad rights to use, copy, modify, and redistribute the *code*; it grants **no
rights** to the Minervit name, any product name or logo, or any implication of endorsement.
Minervit remains the vendor and steward of the name. A fork distributed as its own product must
use its own distinct name. For trademark usage questions, contact the maintainers.

## 5. Third-party services and further reading

Use of external tools and services — your AI agent runtime (Claude, Codex), GitHub, git
hosting, chat webhooks, and any other endpoint you configure — is governed by **those
services' own terms and pricing**, separately from these terms.

- **`PRIVACY.md`** — the outbound data-flow statement (what the CLI sends, where, and when; no
  telemetry).
- **`SECURITY.md`** — the trust boundary, hook-execution model, auto-update safety, and
  vulnerability reporting.

Documentation hardening across these files is part of the public-release readiness work.
