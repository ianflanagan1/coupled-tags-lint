# coupled-tags-lint

Checks the `COUPLED:<key>:[<relation>]` tags in a repository: that each is well formed, that the values they relate agree, and that no group has changed since it was last reviewed. The tag convention, and the Claude Code skill and hook that go with it, are in [coupled-tags](https://github.com/ianflanagan1/coupled-tags).

```
$ coupled-tags-lint
⚠️ 1 problem in COUPLED tags.
app.py:1 Relation doesn't hold with nginx.conf:1: 12 <= 10m
```

Runs on macOS and Linux. Built on [cli-kit](https://github.com/ianflanagan1/cli-kit).

## What it reports

- **malformed tags:** the key has uppercase letters or underscores, or isn't followed straight by `:[` or `:END`
- **clauses:** a clause that isn't an equation, a bare op, a file or a selector, such as an old `(note)`; an op other than `=`, `same-as` or `same-shape` with no ref; a bare op beside another op in its tag; a ref written twice in a tag; a file not written `./<path>` or `//<git-host>/<owner>/<name>/<path>`; a selector inside an equation, more than one selector, or one that isn't a regex; a formula or selector with a structural op; and a formula multiplying or dividing by 0
- **brackets:** a tag with no closing `]` before its comment ends, a blank line or the end of the file, and a `]` followed straight by `(` or `[`, which Markdown reads as a link
- **block ends:** a `COUPLED:<key>:END` with no tag of its key above it to close, or closing a tag with a value op, a block holding another of its own key, and blocks that overlap
- **placement:** a tag with no line of code directly after its comment, such as one with a blank line between
- **refs:** a name no other site of the key has, or several have, saying how to pick one out with its file (`./B.php#$a`); a file holding several tags of the key named without a value's name; a JSON Pointer into a file that holds tags of the key; and a value's name into a file that holds none
- **mirrors:** an equation between two tagged sites that isn't written at both (`= $d + 1` at `$e` needs `= $e - 1` at `$d`), and two that are written at both but don't mirror each other
- **files:** a tag that doesn't refer to every file the other tags of its key in this repository refer to, in an equation or alone, or that marks one differently, such as `./.env` on one and `./.env?` on another; a file clause naming a file that already holds a tag of the key, which the search finds without it; and a file in this repository that isn't there, unless it's marked optional with `?`
- **orphan keys:** the key appears only once, which usually means the other end was deleted, unless its tag refers to a file
- **groups:** a group with no op, one that mixes value ops with structural ops, a bare op in a group that mixes ops, and a site or file nothing relates
- **values**, in groups using value ops: a site whose value it can't read, and a relation that doesn't hold, with the values it compared. A file a tag refers to gives its one tag of the key, if it's excluded from the search, or else its value at the pointer, or its one line; a longer file with neither can't be read.
- **the lock:** a group that differs from what `.coupled-tags.lock` records (see [The lock](#the-lock))
- **unreadable files:** a file holding `COUPLED:` that isn't UTF-8

A tag runs from `[` to the `]` that closes it, which may be on a later line of its comment, so a tag that a formatter or editor wraps is still read whole. The opener of a line comment (`#`, `//`, `;`, `--`) and the `*` of a docblock line are left out where it runs on; in a block comment, or outside one as in Markdown, it runs on over any lines. Brackets inside it, such as `$_ENV['X']`, and a selector's regex don't close it. Text before `COUPLED:` and after the `]` isn't part of the tag, so prose goes there, and comment lines between a tag on its own line and the code it describes are skipped.

Between its brackets a tag holds none or more clauses, separated by `; `:

- `<op> <ref> [<arith> <number>]`, an equation: this site's value, by op, the ref's through the formula
- `=`, `same-as` or `same-shape` alone, a bare op: the same as every other site of the key
- `./<path>[?][#<fragment>]`, a file in this repository, or `//<git-host>/<owner>/<name>/<path>[?][#<fragment>]`, one in another, that's in the group but can't hold a tag
- `@/<regex>/`, a selector, picking this site's value out of its line

A ref is a value's name at its site (`MAX_UPLOAD_MB`), or a file. A file's fragment is a JSON Pointer (`#/engines/node`), or the name of a value at a tagged site in it (`./B.php#$a`), which picks out one site when several have the name. A name matches the site whose line declares it, by assignment or directive, before one whose line only mentions it.

```
COUPLED:upload-limit:[<= client_max_body_size; = ./limits.json#/upload_mb; ./.env?] nginx answers larger bodies with a 413.
```

The lint doesn't read other repositories, since which revision to compare against, and how to reach it, depend on how the two are released. It checks that each `//` file is well formed and on every tag of its key, leaves unchecked a name no site here has when the group refers to another repository, and names the repositories in its status line. To check them against each repository's default branch, run [coupled-tags-cross-repo](https://github.com/ianflanagan1/coupled-tags-cross-repo) beside the lint.

### Fixing

`--fix` adds to the tags what the lint can write itself, then checks:

- the mirror of an equation at its other site, flipping the op and undoing the formula (`< $d * 2` at `$e` gives `> $e / 2` at `$d`), naming this end as another tag already does, else by its declared name, alone or in its file, else by its file alone
- each file the group's other tags refer to, alone, unless it's in this repository and isn't there

It leaves to you what it can't decide: two equations that don't mirror each other, a ref that names no site or several (and the mirrors of a tag holding one), and values that don't hold. A tag on one line stays on it; one that ran on over several lines is wrapped again at its `; `, within its longest line. The fix doesn't touch the lock, so run `--update` once you've reviewed the group, or pass both.

## The lock

Relations between values are checked on every run, but structural ops (`same-as`, `same-shape`, `subset-of`, `superset-of`) can't be, and a group can lose a site without any relation failing. So `.coupled-tags.lock`, at the repository's root, records each group as it was last reviewed:

- every site, with its relation
- in a group using value ops, the unit on each value (`m` in `10m`), since numbers are compared without their units
- in a group using structural ops, a fingerprint of each site's block, and of each file in this repository its tags refer to

The lint fails when the code differs: a site added or removed, a relation rewritten, a unit changed, or a structural block or named file edited. It names the group's other sites. Read them, change them together so the group holds, then rerun with `--update` to record it; commit the lock with the change, so its diff shows the group was touched. Values themselves aren't recorded: changing one is checked by its relations.

A block is the line the tag describes and, if a later `COUPLED:<key>:END` closes the tag, every line down to the END, whatever their indentation. A structural tag with no END describes only its line. Indentation, blank lines, and the tags and ENDs of blocks nested inside it don't count, so reindenting a block or rewording a tag inside it isn't a change.

A repository with tags and no lock fails until `--update` writes one. Sites under a `-x` path are kept in the lock as they were and not compared, so run `--update` with the same `-x` options as the check. Other repositories aren't recorded.

It does **not** look at diffs. Diff-aware enforcement in the style of Google's `LINT.IfChange` is out of scope; the lock gives the same effect from the code alone.

## Usage

```sh
coupled-tags-lint            # check the current directory
coupled-tags-lint -l         # also list every key and its sites
coupled-tags-lint -x docs/   # exclude a path prefix (repeatable)
coupled-tags-lint --fix      # add mirrored equations and missing files to the tags, then check
coupled-tags-lint --update   # record the groups in .coupled-tags.lock, then check
```

In a git work tree it scans tracked files plus untracked files that aren't ignored. Elsewhere it uses `grep --recursive`, skipping `.git`, `node_modules` and `vendor`. It ends with one status line: `➖` and exit status 0 when clean, `⚠️` and the problems, one per line, with exit status 1 when it finds any. A usage error exits with 2.

## Adding it to a project

This repository is a Nix flake that packages the lint as the `coupled-tags-lint` command, with the Python, `git` and `grep` it uses pinned, so it behaves the same on macOS, Linux and CI. Add a release of it to a project's devbox:

```sh
devbox add github:ianflanagan1/coupled-tags-lint/v0.2.0#coupled-tags-lint
```

Then run `coupled-tags-lint` in the project's check, as a step of its Taskfile `check` task, so CI runs it too, and commit `.coupled-tags.lock`.

To move to a new release, change the tag in `devbox.json` and run `devbox update`. Without devbox, `nix run github:ianflanagan1/coupled-tags-lint` runs it once.

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

`src/coupled_tags_lint/core/` parses tags, reads values and blocks, checks groups, works out fixes, rewrites tags and builds and compares the lock as pure functions; `orchestrators/lint.py` gathers the files holding tags, the files they refer to and the lock through its ports, and writes the fixed tags and the lock; `adapters/` holds git grep, the file system and the command line; `__main__.py` wires them.

To release, raise `version` in `pyproject.toml`, commit, then run `github release . patch|minor|major`. Projects move to it by changing their tag.
