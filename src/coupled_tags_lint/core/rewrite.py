"""Writing tags back into a file's lines, as --fix does."""

import re

from coupled_tags_lint.core.tags import Placed, Tag, clause_text, find_tags

# What starts a line a tag runs on over, before its text: indentation, then a line comment's
# opener or a docblock's `*`, then spaces.
_CONTINUATION = re.compile(r"\s*(?:#|//|;|--|\*(?!/))?\s*")


def rewritten(lines: list[str], tags: dict[int, Tag]) -> list[str]:
    """lines with each tag starting on a line whose index is in tags written as the tag given
    for it. A tag on one line stays on it. One that ran on over several lines is wrapped
    again, at the `; ` between its clauses, to fit within its longest line, each further line
    starting as its second line did."""
    placed = {item.line: item for item in find_tags(lines) if isinstance(item.found, Tag)}
    result = list(lines)
    for index in sorted(tags, reverse=True):
        item = placed.get(index)
        if item is None:
            continue
        result[item.line : item.end + 1] = _written(lines, item, tags[index])
    return result


def _written(lines: list[str], item: Placed, tag: Tag) -> list[str]:
    head = lines[item.line][: item.start]
    tail = lines[item.end][item.stop :]
    clauses = [clause_text(clause) for clause in tag.clauses]
    if item.line == item.end:
        return [head + "; ".join(clauses) + tail]
    second = lines[item.line + 1]
    match = _CONTINUATION.match(second)
    prefix = second[: match.end()] if match is not None else ""
    width = max(len(line) for line in lines[item.line : item.end + 1])
    written: list[str] = []
    current = head
    # Whether current has no clause on it yet.
    fresh = True
    for n, clause in enumerate(clauses):
        piece = clause + (tail if n == len(clauses) - 1 else ";")
        if not fresh and len(current + " " + piece) > width:
            written.append(current)
            current, fresh = prefix, True
        current += piece if fresh else " " + piece
        fresh = False
    if not clauses:
        current += tail
    written.append(current)
    return written
