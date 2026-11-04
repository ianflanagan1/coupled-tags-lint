"""Finding checkouts of other repositories by name, under the directories in
$COUPLED_TAGS_REPO_ROOTS."""

import os
from typing import final

ROOTS_VARIABLE = "COUPLED_TAGS_REPO_ROOTS"

_SKIPPED_DIRECTORIES = {"node_modules", "vendor"}
_MAX_DEPTH = 3


def roots_from_environment() -> list[str]:
    return [root for root in os.environ.get(ROOTS_VARIABLE, "").split(os.pathsep) if root]


@final
class DirectoryCheckouts:
    """The git checkouts up to three levels under roots, found on first use. A repository's own
    subdirectories, and hidden directories, aren't searched."""

    def __init__(self, roots: list[str]) -> None:
        self._roots = roots
        self._found: dict[str, list[str]] | None = None

    def find(self, name: str) -> list[str]:
        if self._found is None:
            self._found = {}
            for root in self._roots:
                self._walk(root, 1)
        return self._found.get(name, [])

    def _walk(self, directory: str, depth: int) -> None:
        assert self._found is not None
        try:
            children = [entry for entry in os.scandir(directory) if entry.is_dir()]
        except OSError:
            return
        for child in sorted(children, key=lambda entry: entry.name):
            if child.name.startswith(".") or child.name in _SKIPPED_DIRECTORIES:
                continue
            if os.path.exists(os.path.join(child.path, ".git")):
                self._found.setdefault(child.name, []).append(os.path.realpath(child.path))
            elif depth < _MAX_DEPTH:
                self._walk(child.path, depth + 1)
