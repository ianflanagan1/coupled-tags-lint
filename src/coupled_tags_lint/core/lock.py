"""The lock: a record of each group's sites, so that a change to a group the lint can't check by
value fails until someone has reviewed the group and recorded it again with --update.

It records, for each key, every site with its relation; in a group using value ops, the unit on
each site's value; and in a group using structural ops, a fingerprint of each site's block and of
each file in this repository its tags refer to. Files in other repositories aren't recorded. So a
site added or removed, a relation rewritten, a unit changed or a structural block edited all
fail, and the change shows in the lock's diff. compare and its messages name the lock file and
how to update it, as each lock's tool gives them.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import assert_never, final

from coupled_tags_lint.core.check import (
    Content,
    FileRead,
    Missing,
    Problem,
    Site,
    is_value_group,
    outside_files,
)
from coupled_tags_lint.core.tags import FileRef, Pointer, Tag
from coupled_tags_lint.core.values import Value, json_at, read_value, unit_of

LOCK_FILE = ".coupled-tags.lock"
# How to update coupled-tags-lint's lock, as compare's messages end.
UPDATE = "rerun with --update"

_VERSION = 1


@final
@dataclass(frozen=True)
class LockedSite:
    """A site as the lock records it: a tag in the file at path, or a file a tag refers to
    (relation None), by its ref's text."""

    path: str
    relation: str | None
    unit: str | None
    block: str | None


# Each key's sites, in order.
type Lock = dict[str, list[LockedSite]]


@final
@dataclass(frozen=True)
class Unparseable:
    reason: str


@final
@dataclass(frozen=True)
class CurrentSite:
    """A site as it is now, at where (`path:line`, or a file ref's text)."""

    where: str
    locked: LockedSite


# Each key's sites as they are now.
type Current = dict[str, list[CurrentSite]]


def current(sites: list[Site], files: dict[str, FileRead]) -> Current:
    """The lock's record of sites as they are now, given each file in this repository that
    tags refer to."""
    records: Current = {}
    for key, members in _keys(sites).items():
        tags = [site.found for site in members if isinstance(site.found, Tag)]
        value_group = is_value_group(tags)
        records[key] = [_record(site, value_group) for site in members]
        if value_group:
            continue
        for ref in outside_files(key, sites):
            file = files.get(ref.path)
            match file:
                case Content(text):
                    records[key].append(_fingerprinted(ref, text))
                case Missing() | None:
                    pass  # Reported by check, unless it's optional.
                case _:
                    assert_never(file)
    return records


def _keys(sites: list[Site]) -> dict[str, list[Site]]:
    """Each key's tags, in the order first found."""
    keys: dict[str, list[Site]] = {}
    for site in sites:
        if isinstance(site.found, Tag):
            keys.setdefault(site.found.key, []).append(site)
    return keys


def _fingerprinted(ref: FileRef, text: str) -> CurrentSite:
    """A file a tag refers to, recorded by a fingerprint of it, or of the value its pointer
    reaches."""
    label = ref.text()
    pointer = ref.fragment.text if isinstance(ref.fragment, Pointer) else None
    reached = text if pointer is None else json_at(text, pointer)
    block = fingerprint((reached or text).splitlines())
    return CurrentSite(label, LockedSite(label, None, None, block))


def _record(site: Site, value_group: bool) -> CurrentSite:
    assert isinstance(site.found, Tag)
    path = site.where.rsplit(":", 1)[0]
    unit = None
    block = None
    if not value_group:
        block = fingerprint(site.block)
    elif site.code is not None:
        reading = read_value(site.code, site.found.selector())
        if isinstance(reading, Value):
            unit = unit_of(reading.text)
    return CurrentSite(site.where, LockedSite(path, site.found.relation(), unit, block))


def fingerprint(lines: list[str] | tuple[str, ...]) -> str:
    """A short hash of lines, ignoring indentation and blank lines."""
    text = "\n".join(line.strip() for line in lines if line.strip())
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def parse(text: str) -> Lock | Unparseable:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        return Unparseable(f"it isn't JSON: {error}")
    if not isinstance(data, dict) or data.get("version") != _VERSION:
        return Unparseable(f"it isn't a version {_VERSION} lock")
    keys = data.get("keys")
    if not isinstance(keys, dict):
        return Unparseable("it has no `keys` object")
    lock: Lock = {}
    for key, entries in keys.items():
        if not isinstance(entries, list):
            return Unparseable(f"`{key}` isn't a list of sites")
        lock[key] = []
        for entry in entries:
            site = _parse_site(entry)
            if site is None:
                return Unparseable(f"a site of `{key}` isn't an object with a `path`")
            lock[key].append(site)
    return lock


def _parse_site(entry: object) -> LockedSite | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
        return None
    fields = [entry.get(name) for name in ("relation", "unit", "block")]
    if any(field is not None and not isinstance(field, str) for field in fields):
        return None
    relation, unit, block = (field if isinstance(field, str) else None for field in fields)
    return LockedSite(entry["path"], relation, unit, block)


def render(lock: Lock) -> str:
    """The lock's text: its keys in order, each site on one line, so its diff shows each change."""
    keys = []
    for key in sorted(lock):
        sites = sorted(lock[key], key=lambda site: site.path)
        lines = "".join(
            "\n      " + json.dumps(_site_data(site)) + ("," if n < len(sites) - 1 else "")
            for n, site in enumerate(sites)
        )
        keys.append(f"    {json.dumps(key)}: [{lines}\n    ]")
    body = "{" + ("\n" + ",\n".join(keys) + "\n  " if keys else "") + "}"
    return f'{{\n  "version": {_VERSION},\n  "keys": {body}\n}}\n'


def _site_data(site: LockedSite) -> dict[str, str]:
    data = {"path": site.path}
    for name, field in (("relation", site.relation), ("unit", site.unit), ("block", site.block)):
        if field is not None:
            data[name] = field
    return data


def updated(old: Lock | Unparseable | None, now: Current, excludes: list[str]) -> Lock:
    """The lock recording now, keeping the locked sites in excluded paths, which now can't see."""
    lock: Lock = {key: [site.locked for site in sites] for key, sites in now.items()}
    match old:
        case None | Unparseable():
            return lock
        case dict():
            for key, sites in old.items():
                kept = [site for site in sites if excluded(site.path, excludes)]
                if kept:
                    lock.setdefault(key, []).extend(kept)
            return lock
        case _:
            assert_never(old)


def compare(
    old: Lock | Unparseable | None,
    now: Current,
    excludes: list[str],
    lock_file: str,
    update: str,
) -> list[Problem]:
    """The differences between the lock and the sites as they are now, each saying what to do.
    lock_file is the lock's name, and update how to update it, such as UPDATE."""
    match old:
        case None:
            if not now:
                return []
            return [
                Problem(
                    lock_file,
                    f"There's no lock. Check that every group holds, then {update} to record them",
                )
            ]
        case Unparseable(reason):
            return [Problem(lock_file, f"Can't read the lock: {reason}. {update.capitalize()}")]
        case dict():
            return _compare_lock(old, now, excludes, lock_file, update)
        case _:
            assert_never(old)


def _compare_lock(
    old: Lock, now: Current, excludes: list[str], lock_file: str, update: str
) -> list[Problem]:
    problems: list[Problem] = []
    for key in sorted(set(old) | set(now)):
        sites = now.get(key, [])
        if key not in old:
            problems.append(
                Problem(
                    sites[0].where,
                    f"COUPLED:{key}: isn't in {lock_file}. Check that its group holds, then "
                    f"{update} to record it",
                )
            )
            continue
        locked = [site for site in old[key] if not excluded(site.path, excludes)]
        if locked and not sites:
            problems.append(
                Problem(
                    lock_file,
                    f"COUPLED:{key}: has no sites now. If removing it was intended, {update}",
                )
            )
            continue
        problems += _compare_key(key, locked, sites, lock_file, update)
    return problems


def _compare_key(
    key: str, locked: list[LockedSite], sites: list[CurrentSite], lock_file: str, update: str
) -> list[Problem]:
    problems: list[Problem] = []
    wheres = [site.where for site in sites]
    paths = sorted({site.path for site in locked} | {site.locked.path for site in sites})
    for path in paths:
        then = [site for site in locked if site.path == path]
        here = [site for site in sites if site.locked.path == path]
        for index in range(max(len(then), len(here))):
            if index >= len(here):
                problems.append(
                    Problem(
                        path,
                        f"A site of COUPLED:{key}: that {lock_file} records here is gone. If "
                        f"removing it was intended, {update}",
                    )
                )
            elif index >= len(then):
                problems.append(
                    Problem(
                        here[index].where,
                        f"This site of COUPLED:{key}: isn't in {lock_file}. Check that its "
                        f"group holds, then {update}",
                    )
                )
            else:
                problems += _changes(key, then[index], here[index], wheres, lock_file, update)
    return problems


def _changes(
    key: str,
    then: LockedSite,
    site: CurrentSite,
    wheres: list[str],
    lock_file: str,
    update: str,
) -> list[Problem]:
    problems: list[Problem] = []
    now = site.locked
    if now.relation != then.relation:
        problems.append(
            Problem(
                site.where,
                f"Its relation has changed from `{then.relation}` since {lock_file}. If the "
                f"group holds as it's now written, {update}",
            )
        )
    if now.unit != then.unit:
        problems.append(
            Problem(
                site.where,
                f"Its unit has changed from {_unit(then.unit)} to {_unit(now.unit)} since "
                f"{lock_file}. The lint compares numbers without their units, so convert this "
                f"value, or the formulas of COUPLED:{key}:, to the old unit; or if the group "
                f"holds in the new one, {update}",
            )
        )
    if now.block != then.block:
        others = [where for where in wheres if where != site.where]
        problems.append(
            Problem(
                site.where,
                f"It has changed since {lock_file}. Read every site of COUPLED:{key}: "
                f"({', '.join(others) or 'none other here'}, and the files its tags "
                f"refer to), change them together so the group holds, then {update}",
            )
        )
    return problems


def _unit(unit: str | None) -> str:
    return "none" if unit is None else f"`{unit}`"


def excluded(path: str, excludes: list[str]) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in excludes)
