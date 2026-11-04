"""Reading the value a tag describes, and comparing two values under an op and formula."""

import json
import re
from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import assert_never, final

from coupled_tags_lint.core.tags import Arith, Formula, ValueOp


@final
@dataclass(frozen=True)
class Value:
    text: str


@final
@dataclass(frozen=True)
class Unreadable:
    """No single value could be read, and why."""

    reason: str


type Reading = Value | Unreadable

# A comment opener: anywhere after whitespace, or `*` starting a docblock line.
_OPENER = re.compile(r"(?:^|(?<=\s))(?://|#|;|/\*|<!--|--|\{#)|^\s*\*")
_COMMENT_LINE = re.compile(r"^\s*(?:#|//|/\*|\*|;|<!--|--|\{#)")

_QUOTED = re.compile(r"'([^']*)'|\"([^\"]*)\"|`([^`]*)`")
_IMAGE = re.compile(r"(?:^\s*FROM\s+(?:--\S+\s+)*|\bimage:\s*)[^\s:]+:v?(\d+(?:\.\d+)*)")
_ASSIGNMENT = re.compile(r"^\s*(?:[\w$]+\s+)*?[\w.$-]+\s*[=:]\s*([^\s;,]+)\s*[;,]?\s*\\?$")
_DIRECTIVE = re.compile(r"^\s*[\w.-]+(?:\s+[~^=*]+)?\s+([^\s;{]+)\s*[;{]?\s*$")

_VERSION = re.compile(r"v?(\d+(?:\.\d+)*)")
_NUMBER = re.compile(r"(-?\d[\d_]*(?:\.\d+)?)\s*[A-Za-z%]*")


def value_line(lines: list[str], index: int) -> str | None:
    """The code of the line the tag on lines[index] describes, without its comment: that line's
    code before the comment holding the tag, or if it has none, the next line that isn't blank
    or only a comment. None if there's no such line."""
    line = lines[index]
    head = line[: line.find("COUPLED:")] if "COUPLED:" in line else line
    code = _strip_comment(head).strip()
    if code:
        return code
    for following in lines[index + 1 :]:
        if following.strip() and not _COMMENT_LINE.match(following):
            return _strip_comment(following).strip()
    return None


def _strip_comment(text: str) -> str:
    opener = _OPENER.search(text)
    return text if opener is None else text[: opener.start()]


def read_value(code: str, selector: str | None) -> Reading:
    """The value in a line of code: what the selector matches (its capture group, if it has
    one), or else the one quoted literal, image tag, assignment or directive value on it."""
    if selector is not None:
        match = re.search(selector, code)
        if match is None:
            return Unreadable(f"the selector @/{selector}/ doesn't match `{code}`")
        return Value(match.group(1) if match.re.groups else match.group())
    quoted = _QUOTED.findall(code)
    if len(quoted) == 1:
        return Value("".join(quoted[0]))
    if len(quoted) > 1:
        return Unreadable(f"`{code}` has several quoted values")
    for pattern in (_IMAGE, _ASSIGNMENT, _DIRECTIVE):
        if (match := pattern.search(code)) is not None:
            return Value(match.group(1))
    return Unreadable(f"`{code}` has no single value")


def read_file_value(content: str, pointer: str | None) -> Reading | None:
    """The value in a file an `also` note names: at the JSON Pointer, or if there's none, the
    whole file when it's one line. None when there's no pointer and the file is longer, so the
    entry only lists the file."""
    if pointer is None:
        lines = content.strip().splitlines()
        return Value(lines[0].strip()) if len(lines) == 1 else None
    try:
        node = json.loads(content)
    except json.JSONDecodeError:
        return Unreadable("it isn't JSON, so a #<pointer> can't reach into it")
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            return Unreadable(f"it has nothing at #{pointer}")
    if isinstance(node, bool) or not isinstance(node, str | int | float):
        return Unreadable(f"#{pointer} isn't a string or number")
    return Value(str(node))


@final
@dataclass(frozen=True)
class Holds:
    pass


@final
@dataclass(frozen=True)
class Fails:
    """The relation doesn't hold; shown is it written out with the values."""

    shown: str


@final
@dataclass(frozen=True)
class Incomparable:
    reason: str


type Verdict = Holds | Fails | Incomparable


def compare(op: ValueOp, left: str, right: str, formula: Formula | None) -> Verdict:
    """Whether `left <op> right [formula]` holds.

    With a formula, both are numbers. Without one, two versions (dotted numbers, at least one
    with a dot) compare on the components both give, so 24 = 24.22.1; two numbers, which may
    carry a unit suffix such as 10m or 65s, compare numerically; anything else only by = and !=.
    """
    if formula is not None:
        left_number, right_number = _number(left), _number(right)
        for text, number in ((left, left_number), (right, right_number)):
            if number is None:
                return Incomparable(f"`{text}` isn't a number, so it can't take a formula")
        assert left_number is not None and right_number is not None
        result = _apply(right_number, formula)
        if result is None:
            return Incomparable("the formula divides by zero")
        applied = format(result.normalize(), "f")
        shown = f"{left_number} {op} {right_number} {formula.text()} (= {applied})"
        return _verdict(op, _sign(left_number - result), shown)
    left_version, right_version = _version(left), _version(right)
    if left_version is not None and right_version is not None and "." in left + right:
        shared = min(len(left_version), len(right_version))
        a, b = left_version[:shared], right_version[:shared]
        return _verdict(op, (a > b) - (a < b), f"{left} {op} {right}")
    left_number, right_number = _number(left), _number(right)
    if left_number is not None and right_number is not None:
        return _verdict(op, _sign(left_number - right_number), f"{left} {op} {right}")
    match op:
        case ValueOp.EQ | ValueOp.NE:
            return _verdict(op, 0 if left == right else 1, f"`{left}` {op} `{right}`")
        case ValueOp.LT | ValueOp.LE | ValueOp.GT | ValueOp.GE:
            return Incomparable(
                f"{op} compares numbers or versions, and `{left}` {op} `{right}` aren't"
            )
        case _:
            assert_never(op)


def _verdict(op: ValueOp, sign: int, shown: str) -> Verdict:
    match op:
        case ValueOp.EQ:
            holds = sign == 0
        case ValueOp.NE:
            holds = sign != 0
        case ValueOp.LT:
            holds = sign < 0
        case ValueOp.LE:
            holds = sign <= 0
        case ValueOp.GT:
            holds = sign > 0
        case ValueOp.GE:
            holds = sign >= 0
        case _:
            assert_never(op)
    return Holds() if holds else Fails(shown)


def _apply(value: Decimal, formula: Formula) -> Decimal | None:
    match formula.arith:
        case Arith.ADD:
            return value + formula.operand
        case Arith.SUB:
            return value - formula.operand
        case Arith.MUL:
            return value * formula.operand
        case Arith.DIV:
            try:
                return value / formula.operand
            except (DivisionByZero, InvalidOperation):
                return None
        case _:
            assert_never(formula.arith)


def _sign(difference: Decimal) -> int:
    return (difference > 0) - (difference < 0)


def _number(text: str) -> Decimal | None:
    match = _NUMBER.fullmatch(text.strip())
    return None if match is None else Decimal(match.group(1).replace("_", ""))


def _version(text: str) -> tuple[int, ...] | None:
    match = _VERSION.fullmatch(text.strip())
    return None if match is None else tuple(int(part) for part in match.group(1).split("."))
