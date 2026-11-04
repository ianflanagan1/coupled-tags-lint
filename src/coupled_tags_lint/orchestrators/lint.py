"""Linting a repository's COUPLED tags: gather its tagged lines and the values its `also` notes
reach, and check them."""

from dataclasses import dataclass
from typing import Protocol, final

from coupled_tags_lint.core.check import Problem, Site, Source, also_entries, check, is_value_group
from coupled_tags_lint.core.tags import AlsoEntry, Hit, Malformed, Tag, find_tags
from coupled_tags_lint.core.values import (
    Reading,
    Unreadable,
    read_file_value,
    read_value,
    value_line,
)


class TagSearch(Protocol):
    def hits(self, root: str) -> list[Hit]:
        """Every line under root holding `COUPLED:`."""
        ...


class Files(Protocol):
    def read(self, path: str) -> str | None:
        """The content of the file at path, or None if it can't be read."""
        ...


class Checkouts(Protocol):
    def find(self, name: str) -> list[str]:
        """The paths of the checkouts of the repository called name."""
        ...


@final
@dataclass(frozen=True)
class Report:
    problems: list[Problem]
    # Each key, in the order first found, with its sites' locations.
    keys: list[tuple[str, list[str]]]


@final
class Lint:
    def __init__(self, search: TagSearch, files: Files, checkouts: Checkouts) -> None:
        self._search = search
        self._files = files
        self._checkouts = checkouts

    def run(self, root: str, excludes: list[str]) -> Report:
        hits = [hit for hit in self._search.hits(root) if not _excluded(hit.path, excludes)]
        lines: dict[str, list[str]] = {}
        sites: list[Site] = []
        keys: dict[str, list[str]] = {}
        for hit in hits:
            if hit.path not in lines:
                lines[hit.path] = (self._files.read(root + "/" + hit.path) or "").splitlines()
            file_lines = lines[hit.path]
            where = f"{hit.path}:{hit.line}"
            for found in find_tags(hit.text):
                code = value_line(file_lines, hit.line - 1) if hit.line <= len(file_lines) else None
                sites.append(Site(where, found, code))
                if not isinstance(found, Malformed):
                    keys.setdefault(found.key, []).append(where)

        sources: dict[str, list[Source]] = {}
        for key, wheres in keys.items():
            tags = [
                site.found
                for site in sites
                if isinstance(site.found, Tag) and site.found.key == key
            ]
            if not is_value_group(tags):
                continue
            tagged_paths = {where.rsplit(":", 1)[0] for where in wheres}
            for entry in also_entries(tags):
                if entry.repo is None and entry.path in tagged_paths:
                    continue
                sources.setdefault(key, []).extend(self._sources(root, key, entry))
        return Report(check(sites, sources), list(keys.items()))

    def _sources(self, root: str, key: str, entry: AlsoEntry) -> list[Source]:
        """The values the `also` entry reaches: the file in this repository, or in a checkout of
        another, by its tags of key if it has any, else by its pointer or whole content."""
        if entry.repo is None:
            directory = root
        else:
            checkouts = self._checkouts.find(entry.repo.rpartition("/")[2])
            if not checkouts:
                return []  # Not checked out here, so it can't be checked.
            directory = checkouts[0]
        content = self._files.read(directory + "/" + entry.path)
        label = entry.text()
        if content is None:
            if entry.pointer is None:
                return []  # The note only lists it, and it may be untracked, such as .env.
            return [Source(label, label, Unreadable("the file isn't there"))]

        file_lines = content.splitlines()
        tagged: list[Source] = []
        for index, line in enumerate(file_lines):
            for found in find_tags(line):
                if isinstance(found, Tag) and found.key == key:
                    where = (
                        f"{'' if entry.repo is None else entry.repo + ': '}{entry.path}:{index + 1}"
                    )
                    code = value_line(file_lines, index)
                    reading: Reading = (
                        Unreadable("there's no line after the tag")
                        if code is None
                        else read_value(code, found.selector)
                    )
                    tagged.append(Source(where, code or "", reading))
        if tagged:
            # A tag here that can't be read is this repository's to report; one in another
            # repository is that repository's, so it's left out rather than reported twice.
            return [
                source
                for source in tagged
                if entry.repo is None or not isinstance(source.reading, Unreadable)
            ]
        file_reading = read_file_value(content, entry.pointer)
        return [] if file_reading is None else [Source(label, label, file_reading)]


def _excluded(path: str, excludes: list[str]) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in excludes)
