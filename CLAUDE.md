# coupled-tags-lint

`devbox run -- task check` runs ruff and the tests, then builds the flake and lints this repository's tags with the command it packages; run it before finishing. `devbox run -- task lint-file -- <files>` formats and fixes the Python files given.

The lint is a functional core (`core/`) with an orchestrator (`orchestrators/lint.py`) and adapters; test the core with plain values, and the command through `tests/test_cli.py`, which runs it as a program. The tag format is defined in coupled-tags (`~/projects/claude/coupled-tags`): its SKILL.md and README, this repository's `core/tags.py`, and its gate hook, which imports `core/tags.py` and `adapters/driven/checkouts.py`, change together. `flake.nix` packages the command for other projects' devbox, which pin a release tag, so a change reaches them only once it's released and they move to the new tag. The flake builds only files git tracks, so a new file needs `git add` before `task tags` sees it.
