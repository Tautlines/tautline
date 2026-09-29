# Privacy

Tautline has no analytics endpoint and sends no background usage telemetry. It stores local
project and workflow records so agents can coordinate and resume work. Your agent host and any
services you connect have their own data handling policies.

## Local records

Project configuration and generated agent instructions live in your checkout. Optional
handoffs contain session context. Shared work manifests contain goals, paths, dependencies,
blockers, and agent/worktree identity. Evidence receipts describe a command, its result, and
code identity. Decisions and inbox answers can include operator-provided text.

Treat these records as project data. Access is governed by the filesystem and repository
permissions where they reside. Same-machine coordination is not a hosted service; independent
clones and other machines do not automatically receive the records. No automatic token/cost
collection or sanitized-instrumentation publisher is part of the current product.

## Network operations

| Integration | Data flow |
| --- | --- |
| GitHub / Git | Repository and PR/check reads; configured backlog, issue, board, or stakeholder-question operations; App authentication; explicit release publishing. Repository and item references and requested content reach GitHub. |
| Jira | Configured backlog queries and updates reach your Jira Cloud site. |
| Checkout updates | Git fetch/update operations contact the configured framework remote; trust policy controls which code can become active. |
| Registry and release checks | Package/version requests contact PyPI, npm, or GitHub. |
| Commands you run | A test or proof command may contact services or print data according to that command's behavior; Tautline does not sandbox it. |

Local work status, evidence status, and local health do not need network access. Remote health
facts are explicitly requested with `--remote`. There is no current automated Google Chat,
S3 recap, session-journal, or instrumentation publishing workflow.

Credentials come from local environment/configuration or your authentication tooling. Never
commit tokens, private keys, or customer data. Review command arguments and logs before
sharing them; record paths and goals can also reveal confidential information.

## Retention and removal

Local records remain until you remove them or use their applicable lifecycle/rotation commands.
Uninstalling the CLI does not erase all project state. Consult
[removal instructions](docs/product/support-sla-model.md) and the relevant command's `--help`.
Data you explicitly write to a remote service follows that service's retention rules; removing
a local record does not delete remote issues, comments, releases, or Git history.

For privacy questions contact `hello@minervit.ai`. For credential exposure or a vulnerability,
use [private security reporting](SECURITY.md).
