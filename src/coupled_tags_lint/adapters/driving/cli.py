"""The coupled-tags-lint command line."""

import os

from cli_kit import cli, outcome
from cli_kit.outcome import Done, NothingToDo, Precondition

from coupled_tags_lint.core.lock import LOCK_FILE
from coupled_tags_lint.orchestrators.lint import Lint, Report

_PROG = "coupled-tags-lint"

_DESCRIPTION = """\
Check the COUPLED:<key>: tags in a repository.

Reports malformed tags and clauses, orphan keys, refs that name no site or
several, an equation between two tagged sites that isn't written at both, a tag
that doesn't refer to every file the others do, files that aren't there, sites
and files nothing relates, and in groups using = != < <= > >=, values that
can't be read and relations that don't hold. Files in other repositories aren't
checked, and the status line lists their repositories.

--fix adds what it can to the tags: the mirror of an equation another tag
states, and the files the group's other tags refer to.

It also compares the groups with .coupled-tags.lock, which records each group's
sites and relations, the unit on each value, and a fingerprint of each block a
structural op relates. A site added or removed, a relation or unit changed or a
block edited is reported until the group is reviewed and recorded with --update.

Exit status: 0 clean, 1 problems found, 2 usage error."""


def run(lint: Lint, argv: list[str]) -> int:
    parser = cli.ArgumentParser(prog=_PROG, description=_DESCRIPTION)
    parser.add_argument("-l", action="store_true", help="list every key and its sites")
    parser.add_argument(
        "-x",
        action="append",
        default=[],
        metavar="<path>",
        help="exclude a path prefix (relative to <dir>); repeatable",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="add the clauses the lint can write to the tags, then check",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help=f"record the groups as they are now in {LOCK_FILE}, then check",
    )
    parser.add_argument(
        "dir", nargs="?", default=".", metavar="<dir>", help="directory to scan (default: .)"
    )
    args = parser.parse_args(argv)

    if not os.path.isdir(args.dir):
        parser.error(f"{args.dir} isn't a directory")
    excludes = [path.rstrip("/") for path in args.x]
    return cli.finish(
        _PROG, lambda: _show(lint.run(args.dir, excludes, args.update, args.fix), args.l)
    )


def _show(report: Report, list_keys: bool) -> Done | NothingToDo:
    if list_keys:
        for key, wheres in report.keys:
            print(f"{key} ({len(wheres)})" + "".join("\n    " + where for where in wheres))
    changes = []
    if report.fixed:
        changes.append(f"Fixed tags in {', '.join(report.fixed)}.")
    if report.updated:
        changes.append(f"Updated {LOCK_FILE}.")
    if report.problems:
        for change in changes:
            outcome.changed(change)
        raise Precondition(
            f"{_count(len(report.problems), 'problem')} in COUPLED tags.",
            *(f"{problem.where} {problem.message}" for problem in report.problems),
        )
    if report.keys:
        summary = f"No problems in {_count(len(report.keys), 'COUPLED key')}."
    else:
        summary = "No COUPLED tags."
    if report.unchecked:
        summary += f" Not checked, as they're other repositories: {', '.join(report.unchecked)}."
    if changes:
        return Done(" ".join(changes), summary)
    return NothingToDo(summary)


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"
