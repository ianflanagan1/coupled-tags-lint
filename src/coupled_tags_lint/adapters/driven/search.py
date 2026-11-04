"""Finding the lines that hold `COUPLED:` with git grep, or grep outside a git work tree."""

import subprocess
from typing import final

from coupled_tags_lint.core.tags import Hit


@final
class GrepSearch:
    def hits(self, root: str) -> list[Hit]:
        """In a git work tree, its tracked files and untracked files that aren't ignored;
        elsewhere every file, skipping .git, node_modules and vendor."""
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture_output=True, text=True
        )
        if inside.returncode == 0:
            command = [
                "git",
                "grep",
                "--untracked",
                "-I",
                "--line-number",
                "--fixed-strings",
                "COUPLED:",
                "--",
                ".",
            ]
        else:
            command = [
                "grep",
                "--recursive",
                "-I",
                "--line-number",
                "--fixed-strings",
                "COUPLED:",
                "--exclude-dir=.git",
                "--exclude-dir=node_modules",
                "--exclude-dir=vendor",
                ".",
            ]
        output = subprocess.run(command, cwd=root, capture_output=True, text=True).stdout
        hits = []
        for row in output.splitlines():
            path, _, rest = row.partition(":")
            line, _, text = rest.partition(":")
            if line.isdigit():
                hits.append(Hit(path.removeprefix("./"), int(line), text))
        return hits
