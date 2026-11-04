import unittest
from decimal import Decimal

from coupled_tags_lint.core.tags import (
    AlsoEntry,
    Arith,
    Formula,
    Malformed,
    NoOp,
    StructuralOp,
    Tag,
    ValueOp,
    find_tags,
)


def only_tag(text: str) -> Tag:
    found = find_tags(text)
    assert len(found) == 1 and isinstance(found[0], Tag), found
    return found[0]


class FindingTags(unittest.TestCase):
    def test_a_trailing_tag_gives_its_key_and_op(self) -> None:
        tag = only_tag("X = 1  # COUPLED:x-limit: =")
        self.assertEqual(("x-limit", ValueOp.EQ, None), (tag.key, tag.op, tag.target))

    def test_prose_mentions_and_search_patterns_are_not_tags(self) -> None:
        self.assertEqual(
            [], find_tags("Search for `COUPLED:<key>:`, `COUPLED:` or 'COUPLED:x-limit:'.")
        )

    def test_a_key_with_an_uppercase_letter_is_malformed(self) -> None:
        self.assertEqual([Malformed()], find_tags("# COUPLED:X-limit: ="))

    def test_a_key_not_followed_by_a_space_is_malformed(self) -> None:
        self.assertEqual([Malformed()], find_tags("# COUPLED:x-limit:="))

    def test_a_relation_without_an_op_is_reported_with_its_key(self) -> None:
        self.assertEqual([NoOp("x-limit")], find_tags("# COUPLED:x-limit: equals Y"))

    def test_an_op_run_into_its_target_is_not_an_op(self) -> None:
        self.assertEqual([NoOp("x-limit")], find_tags("# COUPLED:x-limit: =Y"))

    def test_two_tags_in_one_comment_are_each_found(self) -> None:
        found = find_tags("X = 1  # COUPLED:x-limit: = COUPLED:y-limit: < Z")
        self.assertEqual(["x-limit", "y-limit"], [tag.key for tag in found if isinstance(tag, Tag)])

    def test_comment_closers_after_a_tag_are_not_part_of_it(self) -> None:
        for text in (
            "/* COUPLED:x: = Y */",
            "<!-- COUPLED:x: = Y -->",
            '"COUPLED:x: = Y",',
            "| COUPLED:x: = Y |",
        ):
            self.assertEqual("Y", only_tag(text).target, text)


class Ops(unittest.TestCase):
    def test_every_op_is_recognised(self) -> None:
        for op in [*ValueOp, *StructuralOp]:
            self.assertEqual(op, only_tag(f"# COUPLED:x: {op} Y").op)

    def test_value_ops_and_ops_that_go_bare_need_no_target(self) -> None:
        for op in ("=", "same-as", "same-shape"):
            self.assertEqual((), only_tag(f"# COUPLED:x: {op}").problems, op)

    def test_other_ops_need_a_target(self) -> None:
        for op in ("!=", "<", "<=", ">", ">=", "subset-of", "superset-of"):
            self.assertIn(
                f"Name the other value after {op}",
                " ".join(only_tag(f"# COUPLED:x: {op}").problems),
            )

    def test_a_note_alone_is_not_a_target(self) -> None:
        self.assertIn(
            "Name the other value after <", " ".join(only_tag("# COUPLED:x: < (seconds)").problems)
        )


class Targets(unittest.TestCase):
    def test_a_target_may_have_spaces_and_parentheses(self) -> None:
        self.assertEqual("Idle timeout", only_tag("# COUPLED:x: < Idle timeout").target)
        self.assertEqual(
            "Validator::validate()", only_tag("# COUPLED:x: same-as Validator::validate()").target
        )

    def test_a_formula_after_the_target_is_split_off(self) -> None:
        tag = only_tag("# COUPLED:x: > Idle timeout * 1_000 (ms vs s)")
        self.assertEqual("Idle timeout", tag.target)
        self.assertEqual(Formula(Arith.MUL, Decimal(1000)), tag.formula)
        self.assertEqual("(ms vs s)", tag.note)

    def test_each_arithmetic_operator_makes_a_formula(self) -> None:
        for arith in Arith:
            self.assertEqual(
                Formula(arith, Decimal("2.5")), only_tag(f"# COUPLED:x: = Y {arith} 2.5").formula
            )

    def test_a_formula_after_a_structural_op_is_reported(self) -> None:
        self.assertIn(
            "Use a formula or selector only after",
            " ".join(only_tag("# COUPLED:x: same-as Y + 1").problems),
        )


class Selectors(unittest.TestCase):
    def test_a_selector_is_split_off_before_the_note(self) -> None:
        tag = only_tag(r"# COUPLED:x: = HTTP_PORT @/:(\d+)/ (dev only)")
        self.assertEqual(
            ("HTTP_PORT", r":(\d+)", "(dev only)"), (tag.target, tag.selector, tag.note)
        )

    def test_a_selector_may_hold_spaces_and_parentheses(self) -> None:
        self.assertEqual(r"line (\/\w+\/)", only_tag(r"# COUPLED:x: = @/line (\/\w+\/)/").selector)

    def test_a_selector_that_is_not_a_regex_is_reported(self) -> None:
        self.assertIn(
            "Fix the selector's regex", " ".join(only_tag("# COUPLED:x: = @/(/").problems)
        )

    def test_a_selector_with_two_capture_groups_is_reported(self) -> None:
        self.assertIn(
            "at most one capture group", " ".join(only_tag("# COUPLED:x: = @/(a)(b)/").problems)
        )


class Notes(unittest.TestCase):
    def test_a_note_that_is_not_closed_is_reported(self) -> None:
        self.assertIn("End the note with )", " ".join(only_tag("# COUPLED:x: = (seconds").problems))

    def test_text_after_a_note_is_reported(self) -> None:
        self.assertIn(
            "End the note with )", " ".join(only_tag("# COUPLED:x: = (seconds) and more").problems)
        )

    def test_an_also_note_lists_paths_pointers_and_files_in_other_repositories(self) -> None:
        tag = only_tag(
            "# COUPLED:x: = (also .nvmrc, package.json#/engines/node, other-repo: src/x.py, "
            "someone/third.repo: y.json#/a/0; in seconds)"
        )
        self.assertEqual(
            (
                AlsoEntry(None, ".nvmrc", None),
                AlsoEntry(None, "package.json", "/engines/node"),
                AlsoEntry("other-repo", "src/x.py", None),
                AlsoEntry("someone/third.repo", "y.json", "/a/0"),
            ),
            tag.also,
        )
        self.assertEqual((), tag.problems)

    def test_an_also_entry_that_is_a_phrase_is_reported(self) -> None:
        self.assertIn(
            "Write each `also` entry",
            " ".join(only_tag("# COUPLED:x: = (also the nvmrc file)").problems),
        )

    def test_an_empty_also_entry_is_reported(self) -> None:
        self.assertIn(
            "Write each `also` entry",
            " ".join(only_tag("# COUPLED:x: = (also .nvmrc, , y.py)").problems),
        )

    def test_a_note_that_only_explains_has_no_also_entries(self) -> None:
        self.assertIsNone(only_tag("# COUPLED:x: = (seconds)").also)


if __name__ == "__main__":
    unittest.main()
