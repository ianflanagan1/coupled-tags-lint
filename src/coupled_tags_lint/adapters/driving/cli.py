"""The coupled-tags-lint command line."""

import os

from cli_kit import cli
from cli_kit.outcome import NothingToDo, Precondition

from coupled_tags_lint.orchestrators.lint import Lint, Report

_PROG = "coupled-tags-lint"

_DESCRIPTION = """\
Check the COUPLED:<key>: tags in a repository.

Reports malformed tags, relations that don't start with an op, missing targets,
notes and `also` entries that aren't well formed, orphan keys, and in groups
using = != < <= > >=, values that can't be read and relations that don't hold.
Sites in other repositories are checked when they're checked out under
$COUPLED_TAGS_REPO_ROOTS, and skipped otherwise.

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
        "dir", nargs="?", default=".", metavar="<dir>", help="directory to scan (default: .)"
    )
    args = parser.parse_args(argv)

    if not os.path.isdir(args.dir):
        parser.error(f"{args.dir} isn't a directory")
    excludes = [path.rstrip("/") for path in args.x]
    return cli.finish(_PROG, lambda: _show(lint.run(args.dir, excludes), args.l))


def _show(report: Report, list_keys: bool) -> NothingToDo:
    if list_keys:
        for key, wheres in report.keys:
            print(f"{key} ({len(wheres)})" + "".join("\n    " + where for where in wheres))
    if report.problems:
        raise Precondition(
            f"{_count(len(report.problems), 'problem')} in COUPLED tags.",
            *(f"{problem.where} {problem.message}" for problem in report.problems),
        )
    if not report.keys:
        return NothingToDo("No COUPLED tags.")
    return NothingToDo(f"No problems in {_count(len(report.keys), 'COUPLED key')}.")


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"
