import unittest

from coupled_tags_lint.core.rewrite import rewritten
from coupled_tags_lint.core.tags import Tag, parse_relation


def tag(relation: str) -> Tag:
    return parse_relation("x", relation)


class Rewriting(unittest.TestCase):
    def test_a_tag_on_one_line_is_rewritten_in_place(self) -> None:
        self.assertEqual(
            ["$d = 13;  // Checked. COUPLED:x:[= $c + 1; = $e - 1] More prose.", "$e = 14;"],
            rewritten(
                ["$d = 13;  // Checked. COUPLED:x:[= $c + 1] More prose.", "$e = 14;"],
                {0: tag("= $c + 1; = $e - 1")},
            ),
        )

    def test_an_empty_tag_is_filled(self) -> None:
        self.assertEqual(
            ["// COUPLED:x:[= $d - 1]", "$c = 12;"],
            rewritten(["// COUPLED:x:[]", "$c = 12;"], {0: tag("= $d - 1")}),
        )

    def test_a_tag_that_ran_on_is_wrapped_within_its_longest_line(self) -> None:
        self.assertEqual(
            [
                "// COUPLED:x:[= $d + 1; = $c + 2;",
                "//   = ./b.json#/b + 3;",
                "//   = ./a.json#/a + 4] Prose.",
                "$e = 14;",
            ],
            rewritten(
                ["// COUPLED:x:[= $d + 1; = $c + 2;", "//   = ./b.json#/b + 3] Prose.", "$e = 14;"],
                {0: tag("= $d + 1; = $c + 2; = ./b.json#/b + 3; = ./a.json#/a + 4")},
            ),
        )

    def test_a_docblock_tag_that_ran_on_keeps_its_stars(self) -> None:
        self.assertEqual(
            ["/**", " * COUPLED:x:[same-as;", " * ./a.txt; ./b.txt]", " */"],
            rewritten(
                ["/**", " * COUPLED:x:[same-as;", " * ./a.txt]", " */"],
                {1: tag("same-as; ./a.txt; ./b.txt")},
            ),
        )

    def test_several_tags_in_a_file_are_each_rewritten(self) -> None:
        self.assertEqual(
            [
                "A = 1  # COUPLED:x:[= B]",
                "# COUPLED:x:[= A;",
                "#   ./c.txt;",
                "#   ./d.txt]",
                "B = 1",
            ],
            rewritten(
                ["A = 1  # COUPLED:x:[]", "# COUPLED:x:[= A;", "#   ./c.txt]", "B = 1"],
                {0: tag("= B"), 1: tag("= A; ./c.txt; ./d.txt")},
            ),
        )

    def test_a_line_without_a_tag_is_left_alone(self) -> None:
        self.assertEqual(["X = 1"], rewritten(["X = 1"], {0: tag("=")}))


if __name__ == "__main__":
    unittest.main()
