"""Parsing COUPLED:<key>: tags out of a line of text.

A tag is `COUPLED:<key>: <op> [<target> [<arith> <number>]] [@/<regex>/] [(<note>)]`, and runs to
the next tag or the end of the line, less any comment closer after it.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import final


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

# The ops a tag can leave its target out after, when every site in its group has the same op.
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
    """What the target's value goes through before it's compared: `<target> <arith> <operand>`."""

    arith: Arith
    operand: Decimal

    def text(self) -> str:
        return f"{self.arith} {self.operand}"


@final
@dataclass(frozen=True)
class AlsoEntry:
    """A site an `also` note names: a file in this repository (repo None) or in another, and
    optionally a JSON Pointer to the value in it."""

    repo: str | None
    path: str
    pointer: str | None

    def text(self) -> str:
        pointer = "" if self.pointer is None else "#" + self.pointer
        return ("" if self.repo is None else self.repo + ": ") + self.path + pointer


@final
@dataclass(frozen=True)
class Tag:
    key: str
    op: Op
    target: str | None
    formula: Formula | None
    selector: str | None
    note: str | None
    # The entries of an `also` note, or None if the tag has none.
    also: tuple[AlsoEntry, ...] | None
    # What's wrong with the tag on its own, as messages saying how to fix it.
    problems: tuple[str, ...]


@final
@dataclass(frozen=True)
class NoOp:
    """A tag whose relation doesn't start with an op."""

    key: str


@final
@dataclass(frozen=True)
class Malformed:
    """Text that starts like a tag but has no well-formed key."""


type Found = Tag | NoOp | Malformed


@final
@dataclass(frozen=True)
class Hit:
    """A line holding `COUPLED:`, in a file given by its path relative to the repository."""

    path: str
    line: int
    text: str


_KEY = re.compile(r"[a-z0-9-]+:(?= |$)")
_OP = re.compile(r"(!=|<=|>=|=|<|>|same-as|same-shape|subset-of|superset-of)(?= |$)")
_CLOSER = re.compile(r"[ \t]*(\*/|-->|#}|\",?|\|)$")
_SELECTOR = re.compile(r"(?:^|\s)@/(.*?)/(?=\s|$)")
_FORMULA = re.compile(r"(.+?)\s+([-+*/])\s+(\d[\d_]*(?:\.\d+)?)")
_LOCAL_ENTRY = re.compile(r"([^\s,;:#]+)(?:#(\S+))?")
_REPO_ENTRY = re.compile(r"((?:[A-Za-z0-9._-]+/)?[A-Za-z0-9._-]+): ([^\s,;#]+)(?:#(\S+))?")


def find_tags(text: str) -> list[Found]:
    """The tags in a line of text, in order. Mentions in prose such as `COUPLED:<key>:`, and
    search patterns such as `'COUPLED:x-limit:'`, aren't tags."""
    found: list[Found] = []
    rest = text
    while (start := rest.find("COUPLED:")) >= 0:
        rest = rest[start + len("COUPLED:") :]
        if not re.match(r"[A-Za-z0-9_-]", rest) or re.match(r"[a-z0-9-]+:['\"`]", rest):
            continue
        key = _KEY.match(rest)
        if key is None:
            found.append(Malformed())
            continue
        relation = rest[key.end() :]
        end = relation.find("COUPLED:")
        found.append(parse_relation(key.group()[:-1], relation if end < 0 else relation[:end]))
    return found


def parse_relation(key: str, relation: str) -> Tag | NoOp:
    """The tag for key whose text after `COUPLED:<key>:` is relation."""
    relation = _CLOSER.sub("", relation.strip()).strip()
    op_match = _OP.match(relation)
    if op_match is None:
        return NoOp(key)
    op = _op(op_match.group())
    rest = relation[op_match.end() :].strip()
    problems: list[str] = []

    selector = None
    if (selector_match := _SELECTOR.search(rest)) is not None:
        selector = selector_match.group(1)
        rest = (rest[: selector_match.start()] + " " + rest[selector_match.end() :]).strip()
        try:
            compiled = re.compile(selector)
            if compiled.groups > 1:
                problems.append("Give the selector at most one capture group, around the value")
        except re.error as error:
            problems.append(f"Fix the selector's regex: {error}")

    if rest.startswith("("):
        target, note = "", rest
    elif (n := rest.find(" (")) >= 0:
        target, note = rest[:n].strip(), rest[n + 1 :].strip()
    else:
        target, note = rest, ""

    formula = None
    if (formula_match := _FORMULA.fullmatch(target)) is not None:
        target = formula_match.group(1)
        formula = Formula(
            Arith(formula_match.group(2)), Decimal(formula_match.group(3).replace("_", ""))
        )

    also = None
    if note and not note.endswith(")"):
        problems.append("End the note with ), and put any text after it inside the note")
    elif note.startswith("(also "):
        also = _also_entries(note)
        if also is None:
            problems.append(
                "Write each `also` entry as <path>[#<pointer>] or "
                "[<owner>/]<repo>: <path>[#<pointer>], separated by `, `, "
                "with any other text after `; `"
            )
            also = ()

    if isinstance(op, StructuralOp) and (formula is not None or selector is not None):
        problems.append(f"Use a formula or selector only after {' '.join(ValueOp)}, not {op}")
    if not target and op not in BARE_OPS:
        problems.append(
            f"Name the other value after {op}; only = same-as same-shape can go without one"
        )

    return Tag(
        key=key,
        op=op,
        target=target or None,
        formula=formula,
        selector=selector,
        note=note or None,
        also=also,
        problems=tuple(problems),
    )


def _op(text: str) -> Op:
    try:
        return ValueOp(text)
    except ValueError:
        return StructuralOp(text)


def _also_entries(note: str) -> tuple[AlsoEntry, ...] | None:
    """The entries of an `(also ...)` note, or None if any isn't a well-formed entry."""
    body = note[len("(also ") : -1].split(";")[0]
    entries = []
    for text in body.split(","):
        text = text.strip()
        if (local := _LOCAL_ENTRY.fullmatch(text)) is not None:
            entries.append(AlsoEntry(None, local.group(1), local.group(2)))
        elif (remote := _REPO_ENTRY.fullmatch(text)) is not None:
            entries.append(AlsoEntry(remote.group(1), remote.group(2), remote.group(3)))
        else:
            return None
    return tuple(entries)
