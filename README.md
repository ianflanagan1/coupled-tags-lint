# coupled-tags-lint

Checks the `COUPLED:<key>:` tags in a repository: that each is well formed, and that the values they relate agree. The tag convention, and the Claude Code skill and hook that go with it, are in [coupled-tags](https://github.com/ianflanagan1/coupled-tags).

```
$ coupled-tags-lint
⚠️ 1 problem in COUPLED tags.
app.py:1 Relation doesn't hold with nginx.conf:1: 12 <= 10m
```

Runs on macOS and Linux. Built on [cli-kit](https://github.com/ianflanagan1/cli-kit).

## What it reports

- **malformed tags:** the key has uppercase letters or underscores, or is missing the `:` or the space after it
- **relations:** a relation that doesn't start with an op, an op that needs a target and lacks one, a note that isn't one parenthesised piece at the end, a selector that isn't a regex, or a formula or selector after a structural op
- **`also` notes:** an entry that isn't `<path>[#<pointer>]` or `[<owner>/]<repo>: <path>[#<pointer>]`, such as a phrase
- **orphan keys:** the key appears only once, which usually means the other end was deleted, unless its note starts `also`
- **groups:** a group that mixes value ops with structural ops
- **values**, in groups using value ops: a site whose value it can't read, a target no other site mentions or several do, and a relation that doesn't hold, with the values it compared

Files an `also` note names are checked when they're there; one without a pointer that's missing (an untracked `.env`) is skipped. A `<repo>: <path>` entry is checked when that repository is checked out under the directories in `COUPLED_TAGS_REPO_ROOTS` (separated by `:`, three levels deep, skipping hidden directories): by the tags of the key in that file, or else by its pointer or one line. A repository that isn't checked out is skipped, so the lint gives the same result in CI.

It does **not** check that changes to a key touch every site. Diff-aware enforcement in the style of Google's `LINT.IfChange` is out of scope.

## Usage

```sh
coupled-tags-lint            # check the current directory
coupled-tags-lint -l         # also list every key and its sites
coupled-tags-lint -x docs/   # exclude a path prefix (repeatable)
```

In a git work tree it scans tracked files plus untracked files that aren't ignored. Elsewhere it uses `grep --recursive`, skipping `.git`, `node_modules` and `vendor`. It ends with one status line: `➖` and exit status 0 when clean, `⚠️` and the problems, one per line, with exit status 1 when it finds any. A usage error exits with 2.

## Adding it to a project

This repository is a Nix flake that packages the lint as the `coupled-tags-lint` command, with the Python, `git` and `grep` it uses pinned, so it behaves the same on macOS, Linux and CI. Add a release of it to a project's devbox:

```sh
devbox add github:ianflanagan1/coupled-tags-lint/v0.1.0#coupled-tags-lint
```

Then run `coupled-tags-lint` in the project's check, as a step of its Taskfile `check` task, so CI runs it too. To move to a new release, change the tag in `devbox.json` and run `devbox update`. Without devbox, `nix run github:ianflanagan1/coupled-tags-lint` runs it once.

## Installing it for yourself

```sh
cd ~/projects/cli/coupled-tags-lint
devbox run -- task setup   # uv sync, then link coupled-tags-lint into ~/.local/bin
```

## Development

```sh
devbox run -- task test    # pytest
devbox run -- task lint    # ruff check and format
devbox run -- task check   # lint, test, then build the flake and lint this repository's tags
```

`src/coupled_tags_lint/core/` parses tags, reads values and checks groups as pure functions; `orchestrators/lint.py` gathers the tagged lines and `also` files through its ports; `adapters/` holds git grep, the file system, the checkout finder and the command line; `__main__.py` wires them.

To release, raise `version` in `pyproject.toml`, commit, then run `github release . patch|minor|major`. Projects move to it by changing their tag.
