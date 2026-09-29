# The pre-demolition generated adapter

`CLAUDE.md` and `AGENTS.md` here are the real output of Tautline 0.143.0's renderer for
`adapters/projects/example-saas.json` — ~16KB each, naming the process verbs that release had.

They exist so `tests/test_upgrade_path_e2e.py` can build the state a real adopter is actually in
when they run `tautline slim`: a project whose adapter was written by an OLDER release. The current
renderer emits the lean adapter, so asking it to produce the "before" state would make the fixture
drift forward with every change to the renderer — which is exactly the drift the migration exists
to survive.

Regenerate only if the migration needs to be proven against a different historical shape, and say
which release it came from when you do.
