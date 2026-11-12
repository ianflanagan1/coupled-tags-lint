"""Parsing COUPLED:<key>: tags out of a file's lines.

A tag is `COUPLED:<key>:[<clause>; <clause>; ...]`, holding none or more clauses, each one of:

- an equation, `<op> <ref> [<arith> <number>]`, relating this site's value to another's
- a bare op, `=`, `same-as` or `same-shape`, the same as every other site of the key
- a file, `./<path>[?][#<fragment>]` in this repository or
  `//<git-host>/<owner>/<name>/<path>[?][#<fragment>]` in another, which is in the group but
  can't hold a tag
- a selector, `@/<regex>/`, picking this site's value out of its line

A ref is a name, a value's own name at its site, or a file, whose fragment is a JSON Pointer
(starting `/`) or the name of a value at a tagged site in it. The tag may run on over the
following lines of its comment, up to the `]` that closes it; text before and after it is
prose. A tag with a structural op can be closed by a later `COUPLED:<key>:END`, so that it
describes the block of lines between them.
"""

import re
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from typing import assert_never, final

from coupled_tags_lint.core.comments import BLOCK_CLOSERS, LINE_OPENERS, opener


class ValueOp(StrEnum):
    """An op that compares the values at two sites."""

    EQ = "="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="


class StructuralOp(StrEnum):
    """An op relating code or structure, which an agent judges and the lint doesn't compare."""

    SAME_AS = "same-as"
    SAME_SHAPE = "same-shape"
    SUBSET_OF = "subset-of"
    SUPERSET_OF = "superset-of"


type Op = ValueOp | StructuralOp

# The ops a tag can write bare, without a ref, when every op in its group is the same.
BARE_OPS: frozenset[Op] = frozenset({ValueOp.EQ, StructuralOp.SAME_AS, StructuralOp.SAME_SHAPE})

OPS_TEXT = " ".join([*ValueOp, *StructuralOp])


class Arith(StrEnum):
    ADD = "+"
    SUB = "-"
    MUL = "*"
    DIV = "/"


@final
@dataclass(frozen=True)
class Formula:
    """What the ref's value goes through before it's compared: `<ref> <arith> <operand>`."""

    arith: Arith
    operand: Decimal

    def text(self) -> str:
        return f"{self.arith} {self.operand}"


@final
@dataclass(frozen=True)
class Name:
    """A value by its own name at its site: `MAX_UPLOAD_MB`, `Idle timeout`."""

    text: str


@final
@dataclass(frozen=True)
class Pointer:
    """A JSON Pointer to a value in a file, starting with `/`."""

    text: str


@final
@dataclass(frozen=True)
class Named:
    """The name of a value at a tagged site in a file, to tell it from others of the same name."""

    text: str


type Fragment = Pointer | Named


@final
@dataclass(frozen=True)
class FileRef:
    """A file: in this repository (repo None), or in the repository repo,
    `<git-host>/<owner>/<name>`, which the lint doesn't read. An optional file (`?`) is only
    sometimes there, such as an untracked .env, so its absence isn't a problem. fragment picks
    a value in it."""

    repo: str | None
    path: str
    optional: bool
    fragment: Fragment | None

    def text(self) -> str:
        where = "./" + self.path if self.repo is None else f"//{self.repo}/{self.path}"
        optional = "?" if self.optional else ""
        return where + optional + ("" if self.fragment is None else "#" + self.fragment.text)

    def unmarked(self) -> "FileRef":
        """The ref without its optional mark: what it refers to, however it's marked."""
        return replace(self, optional=False)


type Ref = Name | FileRef


def ref_text(ref: Ref) -> str:
    match ref:
        case Name(text):
            return text
        case FileRef():
            return ref.text()
        case _:
            assert_never(ref)


@final
@dataclass(frozen=True)
class Equation:
    """`<op> <ref> [<arith> <number>]`: this site's value, op, the ref's through the formula."""

    op: Op
    ref: Ref
    formula: Formula | None

    def text(self) -> str:
        formula = "" if self.formula is None else " " + self.formula.text()
        return f"{self.op} {ref_text(self.ref)}{formula}"


@final
@dataclass(frozen=True)
class BareOp:
    """An op without a ref: this site is the same as every other site of its key."""

    op: Op


@final
@dataclass(frozen=True)
class Selector:
    """`@/<regex>/`, picking this site's value out of its line."""

    regex: str


type Clause = Equation | BareOp | FileRef | Selector


def clause_text(clause: Clause) -> str:
    match clause:
        case Equation() | FileRef():
            return clause.text()
        case BareOp(op):
            return op
        case Selector(regex):
            return f"@/{regex}/"
        case _:
            assert_never(clause)


@final
@dataclass(frozen=True)
class Tag:
    key: str
    # The tag's well-formed clauses, in the order written.
    clauses: tuple[Clause, ...]
    # What's wrong with the tag on its own, as messages saying how to fix it.
    problems: tuple[str, ...]

    def relation(self) -> str:
        """The tag's clauses, written in their canonical form: what goes between its brackets."""
        return "; ".join(clause_text(clause) for clause in self.clauses)

    def equations(self) -> list[Equation]:
        return [clause for clause in self.clauses if isinstance(clause, Equation)]

    def bare(self) -> Op | None:
        """The tag's bare op, or None if it has none."""
        ops = [clause.op for clause in self.clauses if isinstance(clause, BareOp)]
        return ops[0] if ops else None

    def ops(self) -> list[Op]:
        """The ops of its bare op and equations, in order."""
        return [clause.op for clause in self.clauses if isinstance(clause, BareOp | Equation)]

    def files(self) -> list[FileRef]:
        """The files it refers to, in its file clauses and its equations, in order."""
        refs: list[FileRef] = []
        for clause in self.clauses:
            if isinstance(clause, FileRef):
                refs.append(clause)
            elif isinstance(clause, Equation) and isinstance(clause.ref, FileRef):
                refs.append(clause.ref)
        return refs

    def selector(self) -> str | None:
        regexes = [clause.regex for clause in self.clauses if isinstance(clause, Selector)]
        return regexes[0] if regexes else None

    def repos(self) -> list[str]:
        """The other repositories its files are in, in order, each once. The lint doesn't read
        them."""
        repos: list[str] = []
        for ref in self.files():
            if ref.repo is not None and ref.repo not in repos:
                repos.append(ref.repo)
        return repos


def with_clauses(tag: Tag, added: list[Clause]) -> Tag:
    """tag with the clauses added, each after the last clause of its kind or an earlier one, the
    kinds in the order ops, files, selector, or else first."""
    clauses = list(tag.clauses)
    for clause in added:
        before = [n for n, mine in enumerate(clauses) if _kind(mine) <= _kind(clause)]
        clauses.insert(before[-1] + 1 if before else 0, clause)
    return replace(tag, clauses=tuple(clauses))


def _kind(clause: Clause) -> int:
    match clause:
        case BareOp() | Equation():
            return 0
        case FileRef():
            return 1
        case Selector():
            return 2
        case _:
            assert_never(clause)


@final
@dataclass(frozen=True)
class Unclosed:
    """A tag with no closing `]` before what ends it: its comment, a blank line or the end of
    the file."""

    key: str
    before: str


@final
@dataclass(frozen=True)
class End:
    """`COUPLED:<key>:END`, closing the block a structural tag of key opened above it, with
    what's wrong with how it closes it, as messages saying how to fix it."""

    key: str
    problems: tuple[str, ...]


@final
@dataclass(frozen=True)
class Malformed:
    """Text that starts like a tag but isn't `COUPLED:<key>:[` or `COUPLED:<key>:END` with a
    well-formed key."""


type Found = Tag | Unclosed | End | Malformed


@final
@dataclass(frozen=True)
class Placed:
    """A tag found in a file's lines: what it is, the indexes of the lines it starts and ends
    on, the same line unless its relation runs on, and the index of the line holding the END
    that closes its block, or None if nothing closes it. start is the column after its `[` on
    its first line and stop the column of its `]` on its last; for anything but a Tag, both are
    where `COUPLED:` ends."""

    found: Found
    line: int
    end: int
    close: int | None
    start: int
    stop: int


# A key: lowercase letters and digits, in words joined by single hyphens. A key starting with a
# hyphen would read as an option to a search run on the key alone.
_KEY_PATTERN = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_KEY = re.compile(rf"({_KEY_PATTERN}):\[")
_END = re.compile(rf"({_KEY_PATTERN}):END(?![A-Za-z0-9_-])")
_SEARCH_PATTERN = re.compile(rf"{_KEY_PATTERN}:['\"`]")
_OP = re.compile(r"(!=|<=|>=|=|<|>|same-as|same-shape|subset-of|superset-of)(?= |$)")
_SELECTOR_START = re.compile(r"(?:^|(?<=\s))@/")
_FORMULA = re.compile(r"(.+?)\s+([-+*/])\s+(\d[\d_]*(?:\.\d+)?)")
_LOCAL_FILE = re.compile(r"\./([^\s?#/][^\s?#]*)(\?)?(?:#(.+))?")
_REMOTE_FILE = re.compile(r"//([^\s/?#]+/[^\s/?#]+/[^\s/?#]+)/([^\s?#]+)(\?)?(?:#(.+))?")

LINK_PROBLEM = "Put a space after the tag's ], so Markdown doesn't read it as a link"

FILE_FORM = (
    "Write a file as ./<path>[?][#<fragment>] in this repository, or "
    "//<git-host>/<owner>/<name>/<path>[?][#<fragment>] in another"
)


def find_tags(lines: list[str]) -> list[Placed]:
    """The tags and ENDs in a file's lines, in order, each tag with the END closing its block.
    Mentions in prose such as `COUPLED:<key>:`, and search patterns such as
    `'COUPLED:x-limit:'`, aren't tags."""
    placed: list[Placed] = []
    index, column = 0, 0
    while index < len(lines):
        line = lines[index]
        start = line.find("COUPLED:", column)
        if start < 0:
            index, column = index + 1, 0
            continue
        column = start + len("COUPLED:")
        rest = line[column:]
        if not re.match(r"[A-Za-z0-9_-]", rest) or _SEARCH_PATTERN.match(rest):
            continue
        end_match = _END.match(rest)
        if end_match is not None:
            placed.append(Placed(End(end_match.group(1), ()), index, index, None, column, column))
            column += end_match.end()
            continue
        key = _KEY.match(rest)
        if key is None:
            placed.append(Placed(Malformed(), index, index, None, column, column))
            continue
        opened = column + key.end()
        read = _read_relation(lines, index, opened, opener(line[:start]))
        if isinstance(read, str):
            placed.append(Placed(Unclosed(key.group(1), read), index, index, None, column, column))
            continue
        relation, end, end_column = read
        found = parse_relation(key.group(1), relation)
        if lines[end][end_column + 1 : end_column + 2] in ("(", "["):
            found = replace(found, problems=(*found.problems, LINK_PROBLEM))
        placed.append(Placed(found, index, end, None, opened, end_column))
        index, column = end, end_column + 1
    return _paired(placed)


def _paired(placed: list[Placed]) -> list[Placed]:
    """placed, with each END closing the nearest tag of its key above it that no END closes
    yet, and each END's problems: one closing nothing or a value op's tag, and blocks that
    nest in one of their own key or overlap another."""
    closes: dict[int, int] = {}
    problems: dict[int, list[str]] = {}
    for position, item in enumerate(placed):
        if not isinstance(item.found, End):
            continue
        key = item.found.key
        mine = problems.setdefault(position, [])
        opens = [
            earlier
            for earlier in range(position)
            if isinstance(placed[earlier].found, Tag | Unclosed) and _key_of(placed[earlier]) == key
        ]
        free = [earlier for earlier in opens if earlier not in closes]
        if not free:
            mine.append(f"Open this block with a tag of COUPLED:{key}: above it, or drop this END")
            continue
        opening = free[-1]
        closes[opening] = position
        found = placed[opening].found
        if isinstance(found, Tag) and any(isinstance(op, ValueOp) for op in found.ops()):
            mine.append(
                f"Drop this END: the tag of COUPLED:{key}: on line {placed[opening].line + 1} "
                "has a value op, so it describes only the line after it"
            )
        inner = [earlier for earlier in opens if opening < earlier and earlier in closes]
        if inner:
            mine.append(
                f"This block holds another of COUPLED:{key}: (line {placed[inner[0]].line + 1}): "
                "blocks of one key can't nest"
            )
    for opening, closing in closes.items():
        for other, other_closing in closes.items():
            if opening < other < closing < other_closing:
                problems[closing].append(
                    f"Blocks can nest but not overlap: the block of COUPLED:"
                    f"{_key_of(placed[other])}: on line {placed[other].line + 1} runs on past "
                    "this END"
                )
    result: list[Placed] = []
    for position, item in enumerate(placed):
        if isinstance(item.found, End):
            item = replace(item, found=End(item.found.key, tuple(problems[position])))
        elif position in closes:
            item = replace(item, close=placed[closes[position]].line)
        result.append(item)
    return result


def _key_of(item: Placed) -> str | None:
    match item.found:
        case Tag(key=key) | Unclosed(key=key) | End(key=key):
            return key
        case Malformed():
            return None
        case _:
            assert_never(item.found)


def _read_relation(
    lines: list[str], index: int, column: int, comment: str | None
) -> tuple[str, int, int] | str:
    """The relation starting at lines[index][column], with the index and column of its closing
    `]`, or what ended it before one: the text of its lines, without their comment openers,
    joined by spaces. It runs on while its comment does: over lines starting with the same
    opener for a line comment, and over any lines for a block comment or none."""
    closer = BLOCK_CLOSERS.get(comment or "")
    joined = lines[index][column:].rstrip()
    # Where each line's text starts in joined, and the line and column it came from.
    segments = [(0, index, column)]
    while True:
        close = _close(joined)
        if close is not None:
            start, line, line_column = next(s for s in reversed(segments) if s[0] <= close)
            return joined[:close], line, line_column + close - start
        if closer is not None and closer in joined:
            return "the end of its comment"
        index += 1
        if index >= len(lines):
            return "the end of the file"
        line_text = lines[index]
        if not line_text.strip():
            return "a blank line"
        body = line_text.lstrip()
        if comment in LINE_OPENERS:
            if not body.startswith(comment):
                return "the end of its comment"
            body = body[len(comment) :]
        elif closer == "*/" and body.startswith("*") and not body.startswith("*/"):
            body = body[1:]
        body = body.lstrip()
        joined += " "
        segments.append((len(joined), index, len(line_text) - len(body)))
        joined += body.rstrip()


def _close(text: str) -> int | None:
    """The index of the `]` closing a relation that starts text: the first not closing a `[`
    opened in it, outside a selector. None if it isn't closed."""
    depth = 0
    index = 0
    while index < len(text):
        if _SELECTOR_START.match(text, index):
            end = _selector_end(text, index + 2)
            if end is None:
                return None
            index = end + 1
            continue
        if text[index] == "[":
            depth += 1
        elif text[index] == "]":
            if depth == 0:
                return index
            depth -= 1
        index += 1
    return None


def _selector_end(text: str, start: int) -> int | None:
    """The index of the `/` ending the selector whose regex starts at text[start]: the first
    one not escaped or in a character class, followed by a space, `;`, `]` or the end. None if
    there's none."""
    in_class = False
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if in_class:
            in_class = char != "]"
        elif char == "[":
            in_class = True
        elif char == "/" and text[index + 1 : index + 2] in ("", " ", "\t", "]", ";"):
            return index
        index += 1
    return None


def _split(relation: str) -> list[str]:
    """The clauses of a relation: its text split at each `;` outside a selector and outside
    brackets and parentheses."""
    clauses: list[str] = []
    depth = 0
    start = 0
    index = 0
    while index < len(relation):
        if _SELECTOR_START.match(relation, index):
            end = _selector_end(relation, index + 2)
            if end is not None:
                index = end + 1
                continue
        char = relation[index]
        if char in "([{":
            depth += 1
        elif char in ")]}" and depth > 0:
            depth -= 1
        elif char == ";" and depth == 0:
            clauses.append(relation[start:index])
            start = index + 1
        index += 1
    clauses.append(relation[start:])
    return [clause.strip() for clause in clauses]


def parse_relation(key: str, relation: str) -> Tag:
    """The tag for key whose text between `COUPLED:<key>:[` and its `]` is relation."""
    clauses: list[Clause] = []
    problems: list[str] = []
    texts = _split(relation)
    if texts == [""]:
        texts = []
    for text in texts:
        parsed = _clause(text)
        if isinstance(parsed, str):
            problems.append(parsed)
        else:
            clauses.append(parsed)
    tag = Tag(key, tuple(clauses), ())
    return replace(tag, problems=tuple(problems + _tag_problems(tag)))


def _clause(text: str) -> Clause | str:
    """The clause text holds, or a message saying how to write it."""
    if not text:
        return "Drop the empty clause: write clauses separated by `; `"
    if _SELECTOR_START.match(text):
        end = _selector_end(text, 2)
        if end == len(text) - 1:
            return Selector(text[2:end])
    if text.startswith("("):
        return (
            f"Move the note `{text}` after the ]: a tag holds only clauses, and prose goes "
            "around it"
        )
    if text.startswith(("./", "//")):
        ref = _file_ref(text)
        return f"{FILE_FORM}, not `{text}`" if ref is None else ref
    op_match = _OP.match(text)
    if op_match is None:
        return (
            f"Start each clause with an op ({OPS_TEXT}), a file (./ or //) or a selector "
            f"(@/<regex>/), separated by `; `: `{text}` has none"
        )
    op = _op(op_match.group())
    rest = text[op_match.end() :].strip()
    if not rest:
        if op not in BARE_OPS:
            return f"Name the other value after {op}; only = same-as same-shape can go without one"
        return BareOp(op)
    if _SELECTOR_START.search(rest):
        return f"Put the selector in a clause of its own, after `; `: `{text}`"
    formula = None
    if (formula_match := _FORMULA.fullmatch(rest)) is not None:
        rest = formula_match.group(1)
        formula = Formula(
            Arith(formula_match.group(2)), Decimal(formula_match.group(3).replace("_", ""))
        )
    if rest.startswith(("./", "//")):
        ref = _file_ref(rest)
        if ref is None:
            return f"{FILE_FORM}, not `{rest}`"
        return Equation(op, ref, formula)
    return Equation(op, Name(rest), formula)


def _file_ref(text: str) -> FileRef | None:
    """The file text refers to, or None if it isn't written as one."""
    local = _LOCAL_FILE.fullmatch(text)
    if local is not None:
        return FileRef(None, local.group(1), local.group(2) is not None, _fragment(local.group(3)))
    remote = _REMOTE_FILE.fullmatch(text)
    if remote is not None:
        return FileRef(
            remote.group(1),
            remote.group(2),
            remote.group(3) is not None,
            _fragment(remote.group(4)),
        )
    return None


def _fragment(text: str | None) -> Fragment | None:
    if text is None:
        return None
    return Pointer(text) if text.startswith("/") else Named(text)


def _op(text: str) -> Op:
    try:
        return ValueOp(text)
    except ValueError:
        return StructuralOp(text)


def _tag_problems(tag: Tag) -> list[str]:
    """What's wrong with how a tag's well-formed clauses go together."""
    problems: list[str] = []
    selectors = [clause for clause in tag.clauses if isinstance(clause, Selector)]
    if len(selectors) > 1:
        problems.append("Give the tag at most one selector")
    for selector in selectors:
        try:
            if re.compile(selector.regex).groups > 1:
                problems.append("Give the selector at most one capture group, around the value")
        except re.error as error:
            problems.append(f"Fix the selector's regex: {error}")
    ops = tag.ops()
    if tag.bare() is not None and len(ops) > 1:
        problems.append(
            f"Write a bare {tag.bare()} only as the tag's one op, or give every op a ref"
        )
    structural = [op for op in ops if isinstance(op, StructuralOp)]
    formulas = [equation for equation in tag.equations() if equation.formula is not None]
    if structural and (selectors or formulas):
        problems.append(
            f"Use a formula or selector only with {' '.join(ValueOp)}, not {structural[0]}"
        )
    for equation in formulas:
        assert equation.formula is not None
        if equation.formula.arith in (Arith.MUL, Arith.DIV) and equation.formula.operand == 0:
            problems.append(f"Multiply or divide by a number other than 0: `{equation.text()}`")
    refs = [equation.ref for equation in tag.equations()] + [
        clause for clause in tag.clauses if isinstance(clause, FileRef)
    ]
    seen: list[Ref] = []
    for ref in refs:
        plain = ref.unmarked() if isinstance(ref, FileRef) else ref
        if plain in seen:
            problems.append(f"Refer to `{ref_text(ref)}` only once in a tag")
        else:
            seen.append(plain)
    return problems
