"""coupled-tags-lint: wire the adapters to the lint and run the command line."""

import sys

from coupled_tags_lint.adapters.driven.files import LocalFiles
from coupled_tags_lint.adapters.driven.search import GrepSearch
from coupled_tags_lint.adapters.driving.cli import run
from coupled_tags_lint.orchestrators.lint import Lint


def main() -> None:
    sys.exit(run(Lint(GrepSearch(), LocalFiles()), sys.argv[1:]))


if __name__ == "__main__":
    main()
