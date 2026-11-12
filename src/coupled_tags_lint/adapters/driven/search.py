"""Finding the files that hold `COUPLED:` with git grep, or grep outside a git work tree."""

import subprocess
from typing import final


@final
class GrepSearch:
    def paths(self, root: str) -> list[str]:
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
                "--files-with-matches",
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
                "--files-with-matches",
                "--fixed-strings",
                "COUPLED:",
                "--exclude-dir=.git",
                "--exclude-dir=node_modules",
                "--exclude-dir=vendor",
                ".",
            ]
        output = subprocess.run(command, cwd=root, capture_output=True, text=True).stdout
        return [path.removeprefix("./") for path in output.splitlines() if path]
