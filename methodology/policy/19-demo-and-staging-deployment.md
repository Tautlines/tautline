## Demo And Staging Deployment

- Deployment behavior is adapter-owned. Canonical methodology only requires that adapter-declared deployment targets be honored; it does not invent deploy commands, hosts, migrations, restart steps, or health checks for a project.
- If the adapter declares a demo, staging, or production target and says milestone close includes deployment, deploy the just-merged `main` HEAD with the adapter procedure after source-of-truth work is Done, `main` is merged, the delivery summary is prepared, and continuity is refreshed.
- The adapter owns target URL/host, deploy commands, rollback, credentials, and health checks. Follow it verbatim; do not invent shorter sequences.
- A health check whose `sha`, version, build identity, or equivalent field still shows the pre-deploy commit is a failed deploy, not a success, when the adapter requires build-identity verification.
- A failed deploy or stuck pre-deploy build identity interrupts as P0. Roll back per the adapter's rollback procedure when rollback is configured, then investigate before more feature work.
- A clean adapter-declared milestone deployment is part of the milestone delivery summary, not a separate report. The executive summary names the deployed commit SHA, target, and health-check result.
- If the adapter does not declare deployment as milestone-close work, milestone close stops at push/merge, delivery summary, and handoff refresh.
