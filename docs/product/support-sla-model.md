# Support and removal

Tautline is an MIT-licensed, community-supported project. There is no support SLA or hosted
service guarantee. Report reproducible bugs through [GitHub issues](https://github.com/Tautlines/tautline/issues).
General questions can go to `hello@minervit.ai`. Report vulnerabilities privately through
`security@minervit.ai`; see [SECURITY.md](../../SECURITY.md).

Include `tautline version`, your platform, the failing command, and whether you installed from
PyPI or a checkout. Remove credentials and private project content before sharing output.

## Installation effects

`pipx install tautline` installs a release snapshot in pipx's environment. Update or remove it
with `pipx upgrade tautline` or `pipx uninstall tautline`.

Checkout installation has a wider local footprint. Preview it first:

```bash
bin/tautline install-cli --dry-run
```

The preview lists the launcher paths, environment files, runtime snapshot store, update pin,
Claude autocompact settings, and framework release-guard handling. Defaults include launchers
under `~/.local/bin` and `~/.config/tautline/tautline.env`, with a legacy compatibility mirror.
New installations pin update trust to the installed commit. Keep credentials outside tracked
files; the generated environment may preserve existing local exports.

`tautline init` separately writes the project's configuration and agent instructions. The
Claude plugin separately supplies startup context and its configured-builder hook. Neither is
an automatic consequence of installing the PyPI package.

## Remove a checkout installation

```bash
tautline uninstall-cli --dry-run
tautline uninstall-cli --keep-env
```

`--keep-env` preserves environment files and any local exports in them. Omit it only when you
intend to remove those files too. Use the same `--bin-dir` / `--config-env` overrides as your
installation when applicable.

The uninstaller removes launchers and, unless retained, generated environment files. It leaves
the checkout, project instructions, snapshot store, Claude autocompact settings, and any
existing Git hooks in place. It reports retained integration points. Keep the snapshot store
while a session may still use it.

For a full removal, uninstall the agent plugin in its host, review the reported settings and
hooks, and remove only Tautline-owned entries. Older releases may have installed completion or
review hooks that the current plugin no longer uses. Preserve other tools' settings and any
pre-existing hook backups. Review local handoffs, manifests, decisions, and evidence before
removing their stores; these may be the only copy of useful work context.
