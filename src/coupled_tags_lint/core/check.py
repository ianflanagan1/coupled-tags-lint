"""Checking the groups of tags in a repository: each tag's form, and each group's relations."""

import re
from dataclasses import dataclass
from typing import final

from coupled_tags_lint.core.tags import (
    BARE_OPS,
    OPS_TEXT,
    AlsoEntry,
    Formula,
    Found,
    Malformed,
    NoOp,
    StructuralOp,
    Tag,
    ValueOp,
)
from coupled_tags_lint.core.values import (
    Fails,
    Holds,
    Incomparable,
    Reading,
    Unreadable,
    Value,
    compare,
    read_value,
)


@final
@dataclass(frozen=True)
class Site:
    """A tag found in this repository, at where (`path:line`), with the code of the line it
    describes, or None if there's no such line."""

    where: str
    found: Found
    code: str | None


@final
@dataclass(frozen=True)
class Source:
    """A value a group's relations can be checked against, from outside this repository's
    search: a file an `also` note names, or a tagged site in another repository. names is
    the text a target is looked for in."""

    where: str
    names: str
    reading: Reading


@final
@dataclass(frozen=True)
class Problem:
    where: str
    message: str


def check(sites: list[Site], sources: dict[str, list[Source]]) -> list[Problem]:
    """The problems with sites, grouped by key, given the outside sources of each key."""
    problems: list[Problem] = []
    groups: dict[str, list[tuple[str, Tag | NoOp, str | None]]] = {}
    for site in sites:
        match site.found:
            case Malformed():
                problems.append(
                    Problem(
                        site.where,
                        "Malformed tag. Must be `COUPLED:<key>: <relation>` with key [a-z0-9-]",
                    )
                )
            case NoOp() | Tag():
                groups.setdefault(site.found.key, []).append((site.where, site.found, site.code))
    for key, members in groups.items():
        problems += _check_group(members, sources.get(key, []))
    return problems


def _check_group(
    members: list[tuple[str, Tag | NoOp, str | None]], sources: list[Source]
) -> list[Problem]:
    problems: list[Problem] = []
    tags: list[tuple[str, Tag, str | None]] = []
    for where, found, code in members:
        match found:
            case NoOp():
                problems.append(
                    Problem(where, f"Start the relation with one of {OPS_TEXT}, then a space")
                )
            case Tag():
                problems += [Problem(where, message) for message in found.problems]
                tags.append((where, found, code))

    if len(members) < 2 and not any(tag.also is not None for _, tag, _ in tags):
        problems.append(Problem(members[0][0], "Orphan key with only one site"))
    if not tags:
        return problems

    ops = {tag.op for _, tag, _ in tags}
    first_kind = isinstance(tags[0][1].op, ValueOp)
    for where, tag, _ in tags:
        if isinstance(tag.op, ValueOp) != first_kind:
            problems.append(
                Problem(
                    where,
                    "Use only value ops (= != < <= > >=) or only structural ops "
                    "(same-as same-shape subset-of superset-of) in one group; "
                    "split it into two keys",
                )
            )
        elif len(ops) > 1 and tag.target is None and tag.op in BARE_OPS:
            problems.append(
                Problem(
                    where,
                    f"Name the other value after {tag.op}: "
                    "its group mixes ops, so a bare op is ambiguous",
                )
            )
    if problems or not first_kind:
        return problems
    return _check_values(tags, sources)


def _check_values(tags: list[tuple[str, Tag, str | None]], sources: list[Source]) -> list[Problem]:
    """The relations of a value group whose tags are well formed."""
    problems: list[Problem] = []
    readings: list[Source] = []
    for where, tag, code in tags:
        reading = (
            Unreadable("there's no line after the tag")
            if code is None
            else read_value(code, tag.selector)
        )
        if isinstance(reading, Unreadable):
            problems.append(
                Problem(
                    where,
                    f"Can't read this site's value: {reading.reason}. Pick it out with "
                    "@/<regex>/, or if the group isn't single values, use a structural op",
                )
            )
        readings.append(Source(where, code or "", reading))
    for source in sources:
        if isinstance(source.reading, Unreadable):
            problems.append(
                Problem(source.where, f"Can't read this site's value: {source.reading.reason}")
            )
    if problems:
        return problems

    everything = readings + sources
    for (where, tag, _), mine in zip(tags, readings, strict=True):
        if tag.target is None:
            continue
        others = [
            other
            for other in everything
            if other.where != where and _mentions(other.names, tag.target)
        ]
        if not others:
            problems.append(
                Problem(
                    where,
                    f"No other site in the group mentions {tag.target}. Name the "
                    "other value as it's written at its site",
                )
            )
        elif len(others) > 1:
            problems.append(
                Problem(
                    where,
                    f"{tag.target} is mentioned at several sites: "
                    f"{', '.join(other.where for other in others)}. Name the other value so "
                    "only its own site mentions it",
                )
            )
        else:
            assert isinstance(tag.op, ValueOp)
            problems += _relation(where, tag.op, mine, others[0], tag.formula)

    # Bare = sites, and when every op is =, the outside sources, all hold one value.
    equal = [mine for (_, tag, _), mine in zip(tags, readings, strict=True) if tag.target is None]
    if all(tag.op == ValueOp.EQ for _, tag, _ in tags):
        equal += sources
    for other in equal[1:]:
        problems += _relation(other.where, ValueOp.EQ, other, equal[0], None)
    return problems


def _relation(
    where: str, op: ValueOp, mine: Source, other: Source, formula: Formula | None
) -> list[Problem]:
    assert isinstance(mine.reading, Value) and isinstance(other.reading, Value)
    match compare(op, mine.reading.text, other.reading.text, formula):
        case Holds():
            return []
        case Fails(shown):
            return [Problem(where, f"Relation doesn't hold with {other.where}: {shown}")]
        case Incomparable(reason):
            return [Problem(where, f"Can't compare with {other.where}: {reason}")]


def _mentions(text: str, name: str) -> bool:
    """Whether text holds name as a whole name, not inside a longer one."""
    return re.search(r"(?<![\w.$-])" + re.escape(name) + r"(?![\w$-])", text) is not None


def also_entries(tags: list[Tag]) -> list[AlsoEntry]:
    """The distinct entries of the `also` notes on tags, in order."""
    entries: list[AlsoEntry] = []
    for tag in tags:
        for entry in tag.also or ():
            if entry not in entries:
                entries.append(entry)
    return entries


def is_value_group(tags: list[Tag]) -> bool:
    return bool(tags) and not any(isinstance(tag.op, StructuralOp) for tag in tags)
