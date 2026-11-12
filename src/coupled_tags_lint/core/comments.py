"""The comment syntaxes tags are written in: finding a comment's opener, and code outside it."""

import re

# A comment opener: anywhere after whitespace, or `*` starting a docblock line.
_OPENER = re.compile(r"(?:^|(?<=\s))(?://|#|;|/\*|<!--|--|\{#)|^\s*\*")
_COMMENT_LINE = re.compile(r"^\s*(?:#|//|/\*|\*|;|<!--|--|\{#)")

# Openers of comments that end with their line.
LINE_OPENERS = frozenset({"#", "//", ";", "--"})

# Each block comment's opener, with the text that closes it.
BLOCK_CLOSERS = {"/*": "*/", "*": "*/", "<!--": "-->", "{#": "#}"}


def opener(text: str) -> str | None:
    """The opener of the comment text runs into, or None if it isn't in one."""
    match = _OPENER.search(text)
    return None if match is None else match.group().strip()


def strip_comment(text: str) -> str:
    """text up to the comment in it."""
    match = _OPENER.search(text)
    return text if match is None else text[: match.start()]


def is_comment_line(line: str) -> bool:
    """Whether line holds only a comment."""
    return _COMMENT_LINE.match(line) is not None
