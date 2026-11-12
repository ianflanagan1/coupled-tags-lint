"""Linting a repository's COUPLED tags: gather the tags in its files, the files in it that they
refer to and the lock; with --fix, add the clauses the lint can write to the tags and gather
again; with --update, record the groups in the lock; then check them. Files in other
repositories aren't read."""

from dataclasses import dataclass
from typing import Protocol, final

from coupled_tags_lint.core import lock
from coupled_tags_lint.core.check import (
    Content,
    FileRead,
    Missing,
    Problem,
    Site,
    check,
    file_paths,
    file_sites,
    fixes,
    unchecked,
)
from coupled_tags_lint.core.rewrite import rewritten
from coupled_tags_lint.core.tags import Tag, Unclosed


class TagSearch(Protocol):
    def paths(self, root: str) -> list[str]:
        """The path, relative to root, of every file under root holding `COUPLED:`."""
        ...


class Files(Protocol):
    def read(self, path: str) -> str | None:
        """The content of the file at path, or None if it can't be read."""
        ...

    def write(self, path: str, content: str) -> None: ...


@final
@dataclass(frozen=True)
class Report:
    problems: list[Problem]
    # Each key, in the order first found, with its sites' locations.
    keys: list[tuple[str, list[str]]]
    # The repositories tags refer to files in, which weren't checked.
    unchecked: list[str]
    # The files --fix rewrote tags in.
    fixed: list[str]
    # Whether --update changed the lock.
    updated: bool


@final
@dataclass(frozen=True)
class _Gathered:
    sites: list[Site]
    files: dict[str, FileRead]
    # A problem for each file holding tags that couldn't be read.
    unreadable: list[Problem]


@final
class Lint:
    def __init__(self, search: TagSearch, files: Files) -> None:
        self._search = search
        self._files = files

    def run(self, root: str, excludes: list[str], update: bool, fix: bool) -> Report:
        gathered = self._gather(root, excludes)
        fixed: list[str] = []
        if fix:
            fixed = self._fix(root, gathered)
            if fixed:
                gathered = self._gather(root, excludes)
        sites = gathered.sites

        now = lock.current(sites, gathered.files)
        lock_path = root + "/" + lock.LOCK_FILE
        text = self._files.read(lock_path)
        old = None if text is None else lock.parse(text)
        updated = False
        if update:
            new = lock.updated(old, now, excludes)
            new_text = lock.render(new)
            if new_text != text and (new or text is not None):
                self._files.write(lock_path, new_text)
                updated = True
            old = new

        problems = (
            gathered.unreadable
            + check(sites, gathered.files)
            + lock.compare(old, now, excludes, lock.LOCK_FILE, lock.UPDATE)
        )
        keys: dict[str, list[str]] = {}
        for site in sites:
            if isinstance(site.found, Tag | Unclosed):
                keys.setdefault(site.found.key, []).append(site.where)
        return Report(problems, list(keys.items()), unchecked(sites), fixed, updated)

    def _gather(self, root: str, excludes: list[str]) -> _Gathered:
        paths = [path for path in self._search.paths(root) if not lock.excluded(path, excludes)]
        sites: list[Site] = []
        unreadable: list[Problem] = []
        for path in paths:
            text = self._files.read(root + "/" + path)
            if text is None:
                unreadable.append(Problem(path, "Can't read this file as UTF-8 to check its tags"))
                continue
            sites += file_sites(path, text.splitlines())
        tags = [site.found for site in sites if isinstance(site.found, Tag)]
        files = {path: self._read(root, path) for path in file_paths(tags)}
        return _Gathered(sites, files, unreadable)

    def _fix(self, root: str, gathered: _Gathered) -> list[str]:
        """Rewrites the tags fixes gives, returning the paths of the files changed."""
        by_path: dict[str, dict[int, Tag]] = {}
        for item in fixes(gathered.sites, gathered.files):
            by_path.setdefault(item.path, {})[item.line] = item.tag
        changed: list[str] = []
        for path, tags in by_path.items():
            text = self._files.read(root + "/" + path)
            if text is None:
                continue
            lines = rewritten(text.splitlines(), tags)
            new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
            if new_text != text:
                self._files.write(root + "/" + path, new_text)
                changed.append(path)
        return changed

    def _read(self, root: str, path: str) -> FileRead:
        content = self._files.read(root + "/" + path)
        return Missing() if content is None else Content(content)
