"""Checking the groups of tags in a repository: each tag's form, how its equations resolve to
other sites, that every equation between two tagged sites is written at both, that every tag
refers to the same files, and each group's relations; and the fixes for what can be fixed by
adding clauses to tags."""

import re
from dataclasses import dataclass
from typing import assert_never, final

from coupled_tags_lint.core.tags import (
    Arith,
    Clause,
    End,
    Equation,
    FileRef,
    Formula,
    Found,
    Malformed,
    Name,
    Named,
    Op,
    Pointer,
    Ref,
    StructuralOp,
    Tag,
    Unclosed,
    ValueOp,
    find_tags,
    ref_text,
    with_clauses,
)
from coupled_tags_lint.core.values import (
    Fails,
    Holds,
    Incomparable,
    Reading,
    Unreadable,
    Value,
    block_lines,
    compare,
    declared_name,
    read_file_value,
    read_value,
    value_line,
)

# What a problem the lint can fix says about it.
FIX_HINT = "--fix adds it"


@final
@dataclass(frozen=True)
class Site:
    """A tag found in this repository, at where (`path:line`), with the code of the line it
    describes, or None if there's no such line, and the lines of the block it describes."""

    where: str
    found: Found
    code: str | None
    block: tuple[str, ...]


def file_sites(path: str, lines: list[str]) -> list[Site]:
    """A site for each tag and END in the lines of the file at path."""
    placed = find_tags(lines)
    return [
        Site(
            f"{path}:{item.line + 1}",
            item.found,
            value_line(lines, item.line, item.end),
            tuple(block_lines(lines, item, placed)),
        )
        for item in placed
    ]


@final
@dataclass(frozen=True)
class Content:
    """A file a tag refers to, read."""

    text: str


@final
@dataclass(frozen=True)
class Missing:
    """A file a tag refers to that isn't there."""


type FileRead = Content | Missing


@final
@dataclass(frozen=True)
class Problem:
    where: str
    message: str


@final
@dataclass(frozen=True)
class Fix:
    """A tag to rewrite: the one starting on the line at index line of the file at path,
    written as tag."""

    path: str
    line: int
    tag: Tag


def file_paths(tags: list[Tag]) -> list[str]:
    """The distinct paths in this repository that tags refer to, in order: the files check
    needs read."""
    paths: list[str] = []
    for tag in tags:
        paths += [ref.path for ref in tag.files() if ref.repo is None and ref.path not in paths]
    return paths


def unchecked(sites: list[Site]) -> list[str]:
    """The distinct repositories tags refer to files in, in order, which the lint doesn't
    read."""
    repos: list[str] = []
    for site in sites:
        if isinstance(site.found, Tag):
            repos += [repo for repo in site.found.repos() if repo not in repos]
    return repos


def is_value_group(tags: list[Tag]) -> bool:
    return bool(tags) and not any(isinstance(op, StructuralOp) for tag in tags for op in tag.ops())


def outside_files(key: str, sites: list[Site]) -> list[FileRef]:
    """The distinct files in this repository that key's tags refer to and that hold no tag of
    key, without their optional marks: the files whose values the search doesn't find."""
    tags = [site.found for site in sites if isinstance(site.found, Tag) and site.found.key == key]
    tagged = _tagged_paths(key, sites)
    refs: list[FileRef] = []
    for tag in tags:
        for ref in tag.files():
            plain = ref.unmarked()
            if ref.repo is None and ref.path not in tagged and plain not in refs:
                refs.append(plain)
    return refs


def check(sites: list[Site], files: dict[str, FileRead]) -> list[Problem]:
    """The problems with sites, grouped by key, given each file in this repository that tags
    refer to (see file_paths). The repositories tags refer to aren't read."""
    return _analyse(sites, files)[0]


def fixes(sites: list[Site], files: dict[str, FileRead]) -> list[Fix]:
    """The tags to rewrite, with the clauses check asks for that the lint can write: the mirror
    of an equation another tag states to it, and the files the group's other tags refer to."""
    added = _analyse(sites, files)[1]
    result: list[Fix] = []
    for site in sites:
        if site.where in added and isinstance(site.found, Tag):
            path, line = site.where.rsplit(":", 1)
            result.append(Fix(path, int(line) - 1, with_clauses(site.found, added[site.where])))
    return result


# A site of a group: where it is, what was found there, and the code of the line it describes.
type _Member = tuple[str, Tag | Unclosed, str | None]

# The clauses to add to each tag, by where it is.
type _Additions = dict[str, list[Clause]]


def _analyse(sites: list[Site], files: dict[str, FileRead]) -> tuple[list[Problem], _Additions]:
    problems = _site_problems(sites)
    added: _Additions = {}
    for key, members in _groups(sites).items():
        problems += _file_problems(key, members, sites, files, added)
        form, tags = _form(members)
        problems += form
        if not form:
            problems += _GroupCheck(key, tags, sites, files, added).problems()
    return problems, added


def _site_problems(sites: list[Site]) -> list[Problem]:
    """The problems with sites that aren't tags of a group: malformed tags and ENDs."""
    problems: list[Problem] = []
    for site in sites:
        match site.found:
            case Malformed():
                problems.append(
                    Problem(
                        site.where,
                        "Malformed tag. Must be `COUPLED:<key>:[<clauses>]`, or "
                        "`COUPLED:<key>:END` closing a block, with a key of lowercase letters "
                        "and digits, in words joined by single hyphens",
                    )
                )
            case End(_, end_problems):
                problems += [Problem(site.where, message) for message in end_problems]
            case Unclosed() | Tag():
                pass
            case _:
                assert_never(site.found)
    return problems


def _groups(sites: list[Site]) -> dict[str, list[_Member]]:
    """Each key's sites, in the order first found."""
    groups: dict[str, list[_Member]] = {}
    for site in sites:
        if isinstance(site.found, Tag | Unclosed):
            groups.setdefault(site.found.key, []).append((site.where, site.found, site.code))
    return groups


def _path(where: str) -> str:
    return where.rsplit(":", 1)[0]


def _tagged_paths(key: str, sites: list[Site]) -> set[str]:
    """The files in this repository that hold a tag of key."""
    return {
        _path(site.where)
        for site in sites
        if isinstance(site.found, Tag | Unclosed) and site.found.key == key
    }


def _add(added: _Additions, where: str, clause: Clause) -> None:
    mine = added.setdefault(where, [])
    if clause not in mine:
        mine.append(clause)


def _file_problems(
    key: str,
    members: list[_Member],
    sites: list[Site],
    files: dict[str, FileRead],
    added: _Additions,
) -> list[Problem]:
    """The problems with the files key's tags refer to: one that isn't there, a file clause
    naming a file the search already finds, and a tag that doesn't refer to every file the
    others do, or marks one differently. A file holding a tag of key is left out of the last
    two, as a ref to it picks out a tagged site."""
    tagged = _tagged_paths(key, sites)
    tags = [(where, found) for where, found, _ in members if isinstance(found, Tag)]
    problems: list[Problem] = []

    reported: list[FileRef] = []
    for _, tag in tags:
        for ref in tag.files():
            if ref.repo is not None or ref.optional or ref in reported:
                continue
            if isinstance(files.get(ref.path), Missing):
                reported.append(ref)
                problems.append(
                    Problem(
                        ref.text(),
                        f"A tag of COUPLED:{key}: refers to this file, but it isn't there. Fix "
                        "the path, or if the file is only sometimes there, such as an untracked "
                        ".env, mark it optional: ./<path>?",
                    )
                )

    for where, tag in tags:
        for clause in tag.clauses:
            if isinstance(clause, FileRef) and clause.repo is None and clause.path in tagged:
                problems.append(
                    Problem(
                        where,
                        f"Drop `{clause.text()}`: the search already finds its tag of "
                        f"COUPLED:{key}:",
                    )
                )

    def outside(ref: FileRef) -> bool:
        return ref.repo is not None or ref.path not in tagged

    # Every file the group refers to, as first written.
    every: list[FileRef] = []
    for _, tag in tags:
        for ref in tag.files():
            if outside(ref) and ref.unmarked() not in [known.unmarked() for known in every]:
                every.append(ref)
    for where, tag in tags:
        mine = [ref for ref in tag.files() if outside(ref)]
        plain = [ref.unmarked() for ref in mine]
        absent = [ref for ref in every if ref.unmarked() not in plain]
        if absent:
            problems.append(
                Problem(
                    where,
                    f"Add {', '.join(f'`{ref.text()}`' for ref in absent)} to this tag: every "
                    f"tag of COUPLED:{key}: in a repository refers to the same files; {FIX_HINT}",
                )
            )
            for ref in absent:
                if ref.repo is not None or not isinstance(files.get(ref.path), Missing):
                    _add(added, where, ref)
        for ref in mine:
            others = [
                other.text()
                for _, tag_other in tags
                for other in tag_other.files()
                if other.unmarked() == ref.unmarked() and other.optional != ref.optional
            ]
            if others:
                problems.append(
                    Problem(
                        where,
                        f"Write `{ref.text()}` the same way on every tag of COUPLED:{key}:; "
                        f"another writes it `{others[0]}`",
                    )
                )
    return problems


# A well-formed tag of a group, with where it is and the code of the line it describes.
type _TagSite = tuple[str, Tag, str | None]


def _form(members: list[_Member]) -> tuple[list[Problem], list[_TagSite]]:
    """The problems with the form of a group's tags, and its tags."""
    problems: list[Problem] = []
    tags: list[_TagSite] = []
    for where, found, code in members:
        match found:
            case Unclosed(_, before):
                problems.append(Problem(where, f"Close the tag with ] before {before}"))
            case Tag():
                problems += [Problem(where, message) for message in found.problems]
                if code is None:
                    problems.append(
                        Problem(
                            where,
                            "Put the line this tag describes directly after its comment: "
                            + _NO_LINE,
                        )
                    )
                tags.append((where, found, code))
            case _:
                assert_never(found)

    linked = any(tag.files() for _, tag, _ in tags)
    if len(members) < 2 and not linked:
        problems.append(Problem(members[0][0], "Orphan key with only one site"))
    if not tags:
        return problems, tags

    ops = [op for _, tag, _ in tags for op in tag.ops()]
    if not ops:
        problems.append(
            Problem(
                tags[0][0],
                f"Give a tag of COUPLED:{tags[0][1].key}: an op: its group relates nothing",
            )
        )
        return problems, tags
    first_kind = isinstance(ops[0], ValueOp)
    for where, tag, _ in tags:
        if any(isinstance(op, ValueOp) != first_kind for op in tag.ops()):
            problems.append(
                Problem(
                    where,
                    "Use only value ops (= != < <= > >=) or only structural ops "
                    "(same-as same-shape subset-of superset-of) in one group; "
                    "split it into two keys",
                )
            )
        elif len(set(ops)) > 1 and tag.bare() is not None:
            problems.append(
                Problem(
                    where,
                    f"Name the other value after {tag.bare()}: "
                    "its group mixes ops, so a bare op is ambiguous",
                )
            )
    return problems, tags


_NO_LINE = "there's no line of code directly after the tag's comment"


@final
@dataclass(frozen=True)
class _ToSite:
    """An equation's ref names the group's tag at this index."""

    index: int


@final
@dataclass(frozen=True)
class _ToFile:
    """An equation's ref names a file in this repository without a tag of the key."""

    ref: FileRef


@final
@dataclass(frozen=True)
class _Elsewhere:
    """An equation's ref is in another repository, which the lint doesn't read."""


@final
@dataclass(frozen=True)
class _Unresolved:
    message: str


type _Resolution = _ToSite | _ToFile | _Elsewhere | _Unresolved


_FLIPPED: dict[Op, Op] = {
    ValueOp.EQ: ValueOp.EQ,
    ValueOp.NE: ValueOp.NE,
    ValueOp.LT: ValueOp.GT,
    ValueOp.LE: ValueOp.GE,
    ValueOp.GT: ValueOp.LT,
    ValueOp.GE: ValueOp.LE,
    StructuralOp.SAME_AS: StructuralOp.SAME_AS,
    StructuralOp.SAME_SHAPE: StructuralOp.SAME_SHAPE,
    StructuralOp.SUBSET_OF: StructuralOp.SUPERSET_OF,
    StructuralOp.SUPERSET_OF: StructuralOp.SUBSET_OF,
}


def _inverse(formula: Formula | None) -> Formula | None:
    """The formula undoing formula: + for -, * for /, and the reverse."""
    if formula is None:
        return None
    match formula.arith:
        case Arith.ADD:
            arith = Arith.SUB
        case Arith.SUB:
            arith = Arith.ADD
        case Arith.MUL:
            arith = Arith.DIV
        case Arith.DIV:
            arith = Arith.MUL
        case _:
            assert_never(formula.arith)
    return Formula(arith, formula.operand)


def mirror(equation: Equation, ref: Ref) -> Equation:
    """The equation stated from the other end, naming this end by ref: `= $d + 1` at $e is
    `= $e - 1` at $d."""
    return Equation(_FLIPPED[equation.op], ref, _inverse(equation.formula))


def _mirrors(equation: Equation, other: Equation) -> bool:
    return equation.op == _FLIPPED[other.op] and equation.formula == _inverse(other.formula)


@final
class _GroupCheck:
    """The checks of a group whose tags are well formed: its equations' refs, their mirrors,
    that it relates every site and file, and in a group using value ops, its values."""

    def __init__(
        self,
        key: str,
        tags: list[_TagSite],
        sites: list[Site],
        files: dict[str, FileRead],
        added: _Additions,
    ) -> None:
        self._key = key
        self._tags = tags
        self._files = files
        self._added = added
        self._tagged = _tagged_paths(key, sites)
        self._names = [None if code is None else declared_name(code) for _, _, code in tags]
        self._remote = any(tag.repos() for _, tag, _ in tags)
        self._resolved = {
            (index, n): self._resolve(index, equation.ref)
            for index, (_, tag, _) in enumerate(tags)
            for n, equation in enumerate(tag.equations())
        }

    def problems(self) -> list[Problem]:
        problems: list[Problem] = []
        for (index, _), resolution in self._resolved.items():
            if isinstance(resolution, _Unresolved):
                problems.append(Problem(self._tags[index][0], resolution.message))
        problems += self._mirror_problems()
        problems += self._unrelated()
        if is_value_group([tag for _, tag, _ in self._tags]):
            problems += self._values()
        return problems

    def _resolve(self, index: int, ref: Ref) -> _Resolution:
        """What ref, in an equation of the tag at index, names."""
        others = [n for n in range(len(self._tags)) if n != index]
        match ref:
            case Name(text):
                return self._by_name(others, text, ref) or (
                    _Elsewhere()
                    if self._remote
                    else _Unresolved(
                        f"No other site of COUPLED:{self._key}: has `{text}`. Name the other "
                        "value as it's written at its site, or refer to a file as ./<path>"
                    )
                )
            case FileRef(repo=None, path=path):
                if path not in self._tagged:
                    if isinstance(ref.fragment, Named):
                        return _Unresolved(
                            f"Point into `./{path}` with a JSON Pointer, #/<path>, or tag the "
                            f"value there: `#{ref.fragment.text}` picks out a tagged site"
                        )
                    return _ToFile(ref.unmarked())
                in_file = [n for n in others if _path(self._tags[n][0]) == path]
                match ref.fragment:
                    case Pointer(pointer):
                        return _Unresolved(
                            f"Drop #{pointer}: `./{path}` holds tags of COUPLED:{self._key}:, "
                            "and its values are read from them"
                        )
                    case Named(text):
                        return self._by_name(in_file, text, ref) or _Unresolved(
                            f"`{ref.text()}` names no other site of COUPLED:{self._key}:"
                        )
                    case None:
                        if len(in_file) == 1:
                            return _ToSite(in_file[0])
                        if not in_file:
                            return _Unresolved(
                                f"`{ref.text()}` holds no other site of COUPLED:{self._key}:"
                            )
                        return _Unresolved(
                            f"`./{path}` holds several tags of COUPLED:{self._key}:. Say which "
                            f"with the name of its value: `./{path}#<name>`"
                        )
                    case _:
                        assert_never(ref.fragment)
            case FileRef():
                return _Elsewhere()
            case _:
                assert_never(ref)

    def _by_name(self, candidates: list[int], text: str, ref: Ref) -> _Resolution | None:
        """The one candidate whose line declares text, or else the one whose line mentions it;
        a problem if several do; None if none does."""
        for matching in (
            [n for n in candidates if self._names[n] == text],
            [n for n in candidates if _mentions(self._tags[n][2] or "", text)],
        ):
            if len(matching) == 1:
                return _ToSite(matching[0])
            if matching:
                wheres = [self._tags[n][0] for n in matching]
                example = f"./{_path(wheres[0])}#{text}"
                said = "" if isinstance(ref, FileRef) else f" Say which with its file: `{example}`"
                return _Unresolved(
                    f"`{ref_text(ref)}` names several sites: {', '.join(wheres)}.{said}"
                )
        return None

    def _mirror_problems(self) -> list[Problem]:
        """A problem for each equation between two tagged sites that isn't written at both,
        with the mirror to add where the lint can name this end; and for each pair written
        at both that don't mirror each other."""
        problems: list[Problem] = []
        for index, (where, tag, _) in enumerate(self._tags):
            for n, equation in enumerate(tag.equations()):
                target = self._resolved[(index, n)]
                if not isinstance(target, _ToSite):
                    continue
                other_where, other, _ = self._tags[target.index]
                back = [
                    theirs
                    for m, theirs in enumerate(other.equations())
                    if self._resolved[(target.index, m)] == _ToSite(index)
                ]
                if back:
                    if index < target.index and not any(_mirrors(b, equation) for b in back):
                        wanted = mirror(equation, back[0].ref)
                        problems.append(
                            Problem(
                                where,
                                f"`{equation.text()}` here and `{back[0].text()}` at "
                                f"{other_where} don't mirror each other: that one would be "
                                f"`{wanted.text()}`. Change one to match the other",
                            )
                        )
                    continue
                if equation.formula is None and other.bare() == _FLIPPED[equation.op]:
                    continue
                if self._has_unresolved(target.index):
                    # Its mirror may be the ref that doesn't resolve, so wait until it does.
                    continue
                ref = self._ref_to(index, target.index)
                if ref is None:
                    problems.append(
                        Problem(
                            other_where,
                            f"Add the mirror of `{equation.text()}` at {where} to this tag, "
                            f"naming {where} so that no other site matches",
                        )
                    )
                    continue
                wanted = mirror(equation, ref)
                problems.append(
                    Problem(
                        other_where,
                        f"Add `{wanted.text()}` to this tag, the mirror of `{equation.text()}` "
                        f"at {where}: an equation is written at both its sites; {FIX_HINT}",
                    )
                )
                _add(self._added, other_where, wanted)
        return problems

    def _has_unresolved(self, index: int) -> bool:
        return any(
            isinstance(resolution, _Unresolved)
            for (n, _), resolution in self._resolved.items()
            if n == index
        )

    def _ref_to(self, index: int, at: int) -> Ref | None:
        """A ref the tag at index at names the tag at index by: one another tag already uses,
        else its value's name, alone or in its file, else its file alone. None if none of them
        names it alone."""
        used = [
            equation.ref
            for (n, m), resolution in self._resolved.items()
            if resolution == _ToSite(index)
            for equation in [self._tags[n][1].equations()[m]]
        ]
        path = _path(self._tags[index][0])
        name = self._names[index]
        candidates: list[Ref] = list(used)
        if name is not None:
            candidates += [Name(name), FileRef(None, path, False, Named(name))]
        candidates.append(FileRef(None, path, False, None))
        for ref in candidates:
            if self._resolve(at, ref) == _ToSite(index):
                return ref
        return None

    def _unrelated(self) -> list[Problem]:
        """A problem for each tagged site and file of the group that nothing relates."""
        targets = set(self._resolved.values())
        bare = any(tag.bare() is not None for _, tag, _ in self._tags)
        problems: list[Problem] = []
        for index, (where, tag, _) in enumerate(self._tags):
            if not tag.ops() and _ToSite(index) not in targets:
                problems.append(
                    Problem(
                        where,
                        "Nothing relates this site: give it an equation, or give another tag "
                        f"of COUPLED:{self._key}: one to it",
                    )
                )
        if bare:
            return problems
        for ref in self._outside():
            if _ToFile(ref) not in targets:
                problems.append(
                    Problem(
                        ref.text(),
                        f"Nothing relates this file: give a tag of COUPLED:{self._key}: an "
                        f"equation to it, such as `= {ref.text()}`",
                    )
                )
        return problems

    def _outside(self) -> list[FileRef]:
        """The files in this repository the group refers to that hold no tag of its key."""
        refs: list[FileRef] = []
        for _, tag, _ in self._tags:
            for ref in tag.files():
                plain = ref.unmarked()
                if ref.repo is None and ref.path not in self._tagged and plain not in refs:
                    refs.append(plain)
        return refs

    def _values(self) -> list[Problem]:
        """The relations of a group using value ops."""
        problems: list[Problem] = []
        readings: list[Reading] = []
        for where, tag, code in self._tags:
            reading = Unreadable(_NO_LINE) if code is None else read_value(code, tag.selector())
            if isinstance(reading, Unreadable):
                problems.append(
                    Problem(
                        where,
                        f"Can't read this site's value: {reading.reason}. Pick it out with a "
                        "selector clause, @/<regex>/, or if the group isn't single values, use "
                        "a structural op",
                    )
                )
            readings.append(reading)
        sources: dict[FileRef, Reading] = {}
        for ref in self._outside():
            file = self._files.get(ref.path)
            match file:
                case Content(text):
                    reading, read_problems = _file_reading(self._key, ref, text)
                    sources[ref] = reading
                    problems += read_problems
                    if isinstance(reading, Unreadable):
                        problems.append(
                            Problem(ref.text(), f"Can't read this site's value: {reading.reason}")
                        )
                case Missing() | None:
                    pass  # Reported by _file_problems, unless it's optional.
                case _:
                    assert_never(file)
        if problems:
            return problems

        for (index, n), target in self._resolved.items():
            where, tag, _ = self._tags[index]
            equation = tag.equations()[n]
            assert isinstance(equation.op, ValueOp)
            match target:
                case _ToSite(other):
                    problems += _relation(
                        where,
                        equation.op,
                        equation.formula,
                        readings[index],
                        self._tags[other][0],
                        readings[other],
                    )
                case _ToFile(ref):
                    if ref in sources:
                        problems += _relation(
                            where,
                            equation.op,
                            equation.formula,
                            readings[index],
                            ref.text(),
                            sources[ref],
                        )
                case _Elsewhere() | _Unresolved():
                    pass
                case _:
                    assert_never(target)

        # Bare = sites, and the files in this repository, all hold one value.
        equal = [
            (where, reading)
            for (where, tag, _), reading in zip(self._tags, readings, strict=True)
            if tag.bare() is not None
        ]
        if equal:
            equal += [(ref.text(), reading) for ref, reading in sources.items()]
        for where, reading in equal[1:]:
            problems += _relation(where, ValueOp.EQ, None, reading, equal[0][0], equal[0][1])
        return problems


def _file_reading(key: str, ref: FileRef, text: str) -> tuple[Reading, list[Problem]]:
    """The value a file a tag refers to gives: its one tag of key if it has one, as when it's
    excluded from the search, or else its value at the pointer or its one line."""
    lines = text.splitlines()
    tagged = [
        (placed, placed.found)
        for placed in find_tags(lines)
        if isinstance(placed.found, Tag) and placed.found.key == key
    ]
    if tagged:
        problems = []
        if isinstance(ref.fragment, Pointer):
            problems.append(
                Problem(
                    ref.text(),
                    f"Drop #{ref.fragment.text}: the file has tags of COUPLED:{key}:, and its "
                    "values are read from them",
                )
            )
        if len(tagged) > 1:
            return Unreadable(f"it holds several tags of COUPLED:{key}:"), problems
        placed, found = tagged[0]
        code = value_line(lines, placed.line, placed.end)
        reading = Unreadable(_NO_LINE) if code is None else read_value(code, found.selector())
        return reading, problems
    pointer = ref.fragment.text if isinstance(ref.fragment, Pointer) else None
    reading = read_file_value(text, pointer)
    if reading is None:
        reading = Unreadable(
            f"it has no tag of COUPLED:{key}: and more than one line. Tag the value there, or "
            "if it's JSON, point at it with #<pointer>"
        )
    return reading, []


def _relation(
    where: str,
    op: ValueOp,
    formula: Formula | None,
    mine: Reading,
    other_where: str,
    other: Reading,
) -> list[Problem]:
    assert isinstance(mine, Value) and isinstance(other, Value)
    match compare(op, mine.text, other.text, formula):
        case Holds():
            return []
        case Fails(shown):
            return [Problem(where, f"Relation doesn't hold with {other_where}: {shown}")]
        case Incomparable(reason):
            return [Problem(where, f"Can't compare with {other_where}: {reason}")]


def _mentions(text: str, name: str) -> bool:
    """Whether text holds name as a whole name, not inside a longer one."""
    return re.search(r"(?<![\w.$-])" + re.escape(name) + r"(?![\w$-])", text) is not None
