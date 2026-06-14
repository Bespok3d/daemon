# Changelog

## 0.11.8-dev

First release cut from the standalone daemon repository, extracted from the Bespok3d monorepo
(ADR-0030, "b3 zero"). The daemon is now packaged as a publishable `.b3` and carries its own gate
(`scripts/check.sh`: ruff + mypy + pytest on Python 3.11), packer (`scripts/pack.sh`), and release CI.

No runtime behavior change versus the monorepo's `0.11.8-dev`. The only code change in the extraction
was making the daemon's strict mypy gate genuinely pass: 19 pre-existing type errors that the monorepo
gate had hidden (it ran mypy without the daemon's config) are now fixed, all type-only or runtime
no-ops (the full test suite is unchanged at 265 passed / 5 skipped).
