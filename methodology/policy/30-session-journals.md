## Session Journals

- Session journals are compact LOCAL evidence for methodology improvement, not process authority, product docs, continuity handoffs, or normal startup context.
- Local-only as of 0.9.0: journals narrate adopter product work and can never be proven safe to publish, so remote publication is disabled and `publish-session-journal`/`publish-pending-session-journals` refuse in every mode (deprecated, removal >=1.0.0).
- The sanitized instrumentation record is the only session evidence that can ever be published (zero product-information capacity): opt in via `instrumentation.enabled` and `publish-instrumentation-record`.
- Journals stay disabled unless the source adapter enables them; previews must never be written into a git worktree that could stage them to a remote, and startup must not fetch any remote archive.
