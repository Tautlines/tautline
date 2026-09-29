# Share work manifests across clones through an optional Git branch

Add an opt-in project adapter mode for shared manifests on a dedicated Git branch. Preserve local defaults and speed: cached bounded synchronization at work boundaries, offline advisory status, no checkout/stash, no forced pushes, and no new plans/reviews/gates. Prove two-clone and concurrent publication behavior, owner identity separation, privacy of local filesystem paths, completion and offline recovery.

Completed 2026-09-29: [Tautline 0.149.0](https://github.com/Tautlines/tautline/releases/tag/v0.149.0) is published on GitHub, PyPI and npm, with the ordinary registry drift check aligned. Public source CI passed 2,727 tests; the actual published wheel passed 68 workflow commands across independent clones, including offline recovery and source/index preservation. Tautline's development adapter and runtime use shared Git coordination.

Installed-package verification also caught an unnecessary legacy render command in the work reference. The corrected instructions enable Git mode directly from `.tautline.json` and use `work sync`; refreshing generated guidance is optional. This is a documentation correction, with no runtime version change or retagging.
