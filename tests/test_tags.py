import unittest
from decimal import Decimal

from coupled_tags_lint.core.tags import (
    Arith,
    BareOp,
    End,
    Equation,
    FileRef,
    Formula,
    Malformed,
    Name,
    Named,
    Placed,
    Pointer,
    Selector,
    StructuralOp,
    Tag,
    Unclosed,
    ValueOp,
    find_tags,
    with_clauses,
)


def found(*lines: str) -> list[object]:
    return [placed.found for placed in find_tags(list(lines))]


def only_tag(*lines: str) -> Tag:
    tags = found(*lines)
    assert len(tags) == 1 and isinstance(tags[0], Tag), tags
    return tags[0]


def clauses(relation: str) -> tuple[object, ...]:
    tag = only_tag(f"# COUPLED:x:[{relation}]")
    assert tag.problems == (), tag.problems
    return tag.clauses


def problems(relation: str) -> str:
    return " ".join(only_tag(f"# COUPLED:x:[{relation}]").problems)


class FindingTags(unittest.TestCase):
    def test_a_trailing_tag_gives_its_key_and_clauses(self) -> None:
        tag = only_tag("X = 1  # COUPLED:x-limit:[=]")
        self.assertEqual(("x-limit", (BareOp(ValueOp.EQ),)), (tag.key, tag.clauses))

    def test_prose_mentions_and_search_patterns_are_not_tags(self) -> None:
        self.assertEqual(
            [],
            found("Search for `COUPLED:<key>:[<clauses>]`, `COUPLED:` or 'COUPLED:x-limit:'."),
        )

    def test_a_key_with_an_uppercase_letter_is_malformed(self) -> None:
        self.assertEqual([Malformed()], found("# COUPLED:X-limit:[=]"))

    def test_a_key_of_digits_and_words_joined_by_hyphens_is_a_tag(self) -> None:
        self.assertEqual("http2-max-3", only_tag("# COUPLED:http2-max-3:[=]").key)

    def test_a_key_starting_or_ending_with_a_hyphen_is_malformed(self) -> None:
        self.assertEqual([Malformed()], found("# COUPLED:-x-limit:[=]"))
        self.assertEqual([Malformed()], found("# COUPLED:x-limit-:[=]"))
        self.assertEqual([Malformed()], found("# COUPLED:-:[=]"))

    def test_a_key_with_a_doubled_hyphen_is_malformed(self) -> None:
        self.assertEqual([Malformed()], found("# COUPLED:x--limit:[=]"))

    def test_an_end_whose_key_starts_or_ends_with_a_hyphen_is_malformed(self) -> None:
        self.assertEqual([Malformed()], found("# COUPLED:-x:END"))
        self.assertEqual([Malformed()], found("# COUPLED:x-:END"))

    def test_a_key_not_followed_by_a_bracket_is_malformed(self) -> None:
        self.assertEqual([Malformed()], found("# COUPLED:x-limit: ="))
        self.assertEqual([Malformed()], found("# COUPLED:x-limit: [=]"))

    def test_text_before_and_after_a_tag_is_not_part_of_it(self) -> None:
        tag = only_tag("X = 1  # Checked at deploy. COUPLED:x:[< Y] (seconds) See the runbook.")
        self.assertEqual(
            ((Equation(ValueOp.LT, Name("Y"), None),), ()), (tag.clauses, tag.problems)
        )

    def test_two_tags_in_one_comment_are_each_found(self) -> None:
        tags = found("X = 1  # COUPLED:x-limit:[=] COUPLED:y-limit:[< Z]")
        self.assertEqual(["x-limit", "y-limit"], [tag.key for tag in tags if isinstance(tag, Tag)])

    def test_comment_closers_after_a_tag_are_not_part_of_it(self) -> None:
        for text in (
            "/* COUPLED:x:[= Y] */",
            "<!-- COUPLED:x:[= Y] -->",
            '"COUPLED:x:[= Y]",',
            "| COUPLED:x:[= Y] |",
        ):
            self.assertEqual("= Y", only_tag(text).relation(), text)

    def test_brackets_in_a_name_do_not_close_the_tag(self) -> None:
        self.assertEqual(
            (Equation(ValueOp.EQ, Name("$_ENV['LIMIT']"), None),), clauses("= $_ENV['LIMIT']")
        )

    def test_a_tag_followed_directly_by_a_parenthesis_or_bracket_is_reported(self) -> None:
        for text in ("COUPLED:x:[= Y](link)", "COUPLED:x:[= Y][ref]"):
            self.assertIn("Put a space after the tag's ]", " ".join(only_tag(text).problems))

    def test_a_tag_is_placed_with_the_columns_inside_its_brackets(self) -> None:
        placed = find_tags(["X = 1  # COUPLED:x:[= Y] more"])[0]
        self.assertEqual((20, 23), (placed.start, placed.stop))


class Clauses(unittest.TestCase):
    def test_an_empty_tag_has_no_clauses(self) -> None:
        self.assertEqual((), clauses(""))

    def test_clauses_are_separated_by_semicolons(self) -> None:
        self.assertEqual(
            (
                Equation(ValueOp.EQ, Name("$d"), Formula(Arith.ADD, Decimal(1))),
                Equation(ValueOp.EQ, Name("$c"), Formula(Arith.ADD, Decimal(2))),
                FileRef(None, "a.json", False, Pointer("/key_a")),
            ),
            clauses("= $d + 1; = $c + 2; ./a.json#/key_a"),
        )

    def test_a_semicolon_inside_parentheses_does_not_separate_clauses(self) -> None:
        self.assertEqual((Equation(ValueOp.EQ, Name("f(a; b)"), None),), clauses("= f(a; b)"))

    def test_an_empty_clause_is_reported(self) -> None:
        self.assertIn("Drop the empty clause", problems("= X; ; = Y"))

    def test_a_clause_without_an_op_file_or_selector_is_reported(self) -> None:
        self.assertIn("Start each clause with an op", problems("= X; equals Y"))

    def test_an_op_run_into_its_name_is_not_an_op(self) -> None:
        self.assertIn("Start each clause with an op", problems("=Y"))

    def test_a_note_in_parentheses_is_told_to_move_after_the_bracket(self) -> None:
        self.assertIn("Move the note `(seconds)` after the ]", problems("< Y; (seconds)"))

    def test_a_relation_is_written_canonically(self) -> None:
        tag = only_tag(r"# COUPLED:x:[>=  REQUEST_TIMEOUT + 5;./.env? ;  @/(\d+)/]")
        self.assertEqual(r">= REQUEST_TIMEOUT + 5; ./.env?; @/(\d+)/", tag.relation())


class Ops(unittest.TestCase):
    def test_every_op_is_recognised(self) -> None:
        for op in [*ValueOp, *StructuralOp]:
            self.assertEqual((Equation(op, Name("Y"), None),), clauses(f"{op} Y"))

    def test_ops_that_go_bare_need_no_ref(self) -> None:
        for op in (ValueOp.EQ, StructuralOp.SAME_AS, StructuralOp.SAME_SHAPE):
            self.assertEqual((BareOp(op),), clauses(op))

    def test_other_ops_need_a_ref(self) -> None:
        for op in ("!=", "<", "<=", ">", ">=", "subset-of", "superset-of"):
            self.assertIn(f"Name the other value after {op}", problems(op))

    def test_a_bare_op_with_another_op_in_its_tag_is_reported(self) -> None:
        self.assertIn("Write a bare = only as the tag's one op", problems("=; = X"))

    def test_a_ref_written_twice_in_a_tag_is_reported(self) -> None:
        self.assertIn("Refer to `./a.json?` only once", problems("= ./a.json; ./a.json?"))
        self.assertIn("Refer to `X` only once", problems("= X; < X"))


class Equations(unittest.TestCase):
    def test_a_name_may_have_spaces_and_parentheses(self) -> None:
        self.assertEqual(
            (Equation(ValueOp.LT, Name("Idle timeout"), None),), clauses("< Idle timeout")
        )
        self.assertEqual(
            (Equation(StructuralOp.SAME_AS, Name("Validator::validate()"), None),),
            clauses("same-as Validator::validate()"),
        )

    def test_a_formula_after_the_ref_is_split_off(self) -> None:
        self.assertEqual(
            (Equation(ValueOp.GT, Name("Idle timeout"), Formula(Arith.MUL, Decimal(1000))),),
            clauses("> Idle timeout * 1_000"),
        )

    def test_each_arithmetic_operator_makes_a_formula(self) -> None:
        for arith in Arith:
            self.assertEqual(
                (Equation(ValueOp.EQ, Name("Y"), Formula(arith, Decimal("2.5"))),),
                clauses(f"= Y {arith} 2.5"),
            )

    def test_multiplying_or_dividing_by_zero_is_reported(self) -> None:
        self.assertIn("Multiply or divide by a number other than 0", problems("= Y * 0"))

    def test_a_formula_after_a_structural_op_is_reported(self) -> None:
        self.assertIn("Use a formula or selector only with", problems("same-as Y + 1"))

    def test_an_equation_can_relate_a_file(self) -> None:
        self.assertEqual(
            (
                Equation(
                    ValueOp.EQ,
                    FileRef(None, "b.json", False, Pointer("/key_b")),
                    Formula(Arith.ADD, Decimal(3)),
                ),
            ),
            clauses("= ./b.json#/key_b + 3"),
        )

    def test_a_file_fragment_not_starting_with_a_slash_names_a_value(self) -> None:
        self.assertEqual(
            (Equation(ValueOp.EQ, FileRef(None, "B.php", False, Named("$a")), None),),
            clauses("= ./B.php#$a"),
        )


class Files(unittest.TestCase):
    def test_a_file_here_may_be_optional_and_point_at_a_value(self) -> None:
        self.assertEqual(
            (
                BareOp(ValueOp.EQ),
                FileRef(None, ".nvmrc", False, None),
                FileRef(None, "package.json", False, Pointer("/engines/node")),
                FileRef(None, ".env", True, None),
                FileRef(None, "c.json", True, Pointer("/a")),
            ),
            clauses("=; ./.nvmrc; ./package.json#/engines/node; ./.env?; ./c.json?#/a"),
        )

    def test_a_file_in_another_repository_names_it_by_its_git_host(self) -> None:
        tag = only_tag("# COUPLED:x:[=; //github.com/acme/infra/terraform/limits.json#/upload]")
        self.assertEqual(
            (
                BareOp(ValueOp.EQ),
                FileRef(
                    "github.com/acme/infra", "terraform/limits.json", False, Pointer("/upload")
                ),
            ),
            tag.clauses,
        )
        self.assertEqual(["github.com/acme/infra"], tag.repos())

    def test_a_file_in_another_repository_without_a_path_is_reported(self) -> None:
        self.assertIn("Write a file as ./<path>", problems("=; //github.com/acme/infra"))

    def test_a_file_written_without_its_dot_slash_is_a_name(self) -> None:
        self.assertEqual((Equation(ValueOp.EQ, Name(".nvmrc"), None),), clauses("= .nvmrc"))

    def test_a_file_is_written_back_as_it_was_given(self) -> None:
        tag = only_tag("# COUPLED:x:[=; ./.env?; ./c.json?#/a; //github.com/a/b/x.py#X]")
        self.assertEqual(
            ["./.env?", "./c.json?#/a", "//github.com/a/b/x.py#X"],
            [ref.text() for ref in tag.files()],
        )

    def test_files_include_those_equations_relate(self) -> None:
        tag = only_tag("# COUPLED:x:[= ./a.json#/a; ./b.json]")
        self.assertEqual(["./a.json#/a", "./b.json"], [ref.text() for ref in tag.files()])


class Selectors(unittest.TestCase):
    def test_a_selector_is_a_clause_of_its_own(self) -> None:
        self.assertEqual(
            (Equation(ValueOp.EQ, Name("HTTP_PORT"), None), Selector(r":(\d+)")),
            clauses(r"= HTTP_PORT; @/:(\d+)/"),
        )

    def test_a_selector_inside_an_equation_is_reported(self) -> None:
        self.assertIn("Put the selector in a clause of its own", problems(r"= HTTP_PORT @/(\d+)/"))

    def test_a_selector_may_hold_spaces_parentheses_and_semicolons(self) -> None:
        self.assertEqual(
            r"line (\/\w+\/);", only_tag(r"# COUPLED:x:[=; @/line (\/\w+\/);/]").selector()
        )

    def test_a_slash_in_a_character_class_or_escaped_does_not_end_a_selector(self) -> None:
        self.assertEqual(r"[^/]+\/x", only_tag(r"# COUPLED:x:[=; @/[^/]+\/x/]").selector())

    def test_a_bracket_in_a_selector_does_not_close_the_tag(self) -> None:
        self.assertEqual(r"\](\d+)", only_tag(r"# COUPLED:x:[=; @/\](\d+)/]").selector())

    def test_a_selector_that_is_not_a_regex_is_reported(self) -> None:
        self.assertIn("Fix the selector's regex", problems("=; @/(/"))

    def test_a_selector_with_two_capture_groups_is_reported(self) -> None:
        self.assertIn("at most one capture group", problems("=; @/(a)(b)/"))

    def test_two_selectors_are_reported(self) -> None:
        self.assertIn("at most one selector", problems("=; @/a/; @/b/"))

    def test_a_selector_with_a_structural_op_is_reported(self) -> None:
        self.assertIn("Use a formula or selector only with", problems("same-as; @/a/"))


class AddingClauses(unittest.TestCase):
    def test_an_added_clause_goes_after_the_last_of_its_kind(self) -> None:
        tag = only_tag(r"# COUPLED:x:[= A; ./a.json; @/(\d+)/]")
        added = with_clauses(
            tag, [Equation(ValueOp.LT, Name("B"), None), FileRef(None, "b", False, None)]
        )
        self.assertEqual(r"= A; < B; ./a.json; ./b; @/(\d+)/", added.relation())

    def test_an_added_op_goes_first_in_a_tag_with_none(self) -> None:
        tag = only_tag("# COUPLED:x:[./a.json]")
        added = with_clauses(tag, [Equation(ValueOp.EQ, Name("B"), None)])
        self.assertEqual("= B; ./a.json", added.relation())


class RunningOn(unittest.TestCase):
    def test_a_tag_runs_on_over_the_lines_of_its_comment(self) -> None:
        placed = find_tags(
            [
                "# COUPLED:node-version:[=; ./.nvmrc;",
                "# ./package.json#/engines/node] Pinned for the build.",
                "FROM node:24.22.1-slim",
            ]
        )
        self.assertEqual(1, len(placed))
        self.assertEqual((0, 1), (placed[0].line, placed[0].end))
        tag = placed[0].found
        assert isinstance(tag, Tag)
        self.assertEqual("=; ./.nvmrc; ./package.json#/engines/node", tag.relation())
        self.assertEqual((), tag.problems)

    def test_a_trailing_tag_runs_on_over_the_comment_lines_after_it(self) -> None:
        tag = only_tag(
            "MAX_UPLOAD_MB = 8  # COUPLED:upload:[<= upload_limit_mb;",
            "#   ./limits.json#/upload_limit_mb]",
        )
        self.assertEqual("<= upload_limit_mb; ./limits.json#/upload_limit_mb", tag.relation())

    def test_a_tag_runs_on_over_a_docblock_without_its_stars(self) -> None:
        tag = only_tag("/**", " * COUPLED:vat:[same-as vat();", " * ./rates.txt]", " */")
        self.assertEqual("same-as vat(); ./rates.txt", tag.relation())

    def test_a_tag_runs_on_over_plain_lines_outside_a_comment(self) -> None:
        tag = only_tag("Idle timeout: `60` s. COUPLED:k:[<", "server.keepAliveTimeout / 1000]")
        self.assertEqual("< server.keepAliveTimeout / 1000", tag.relation())

    def test_a_tag_starting_where_another_ends_is_found_on_its_own_line(self) -> None:
        placed = find_tags(["# COUPLED:a:[< x", "# y] COUPLED:b:[=]", "X = 1"])
        self.assertEqual([(0, 1), (1, 1)], [(p.line, p.end) for p in placed])
        assert isinstance(placed[0].found, Tag)
        self.assertEqual("< x y", placed[0].found.relation())


class Unclosing(unittest.TestCase):
    def test_a_line_comment_ending_before_the_bracket_leaves_it_unclosed(self) -> None:
        self.assertEqual(
            [Unclosed("x", "the end of its comment")], found("# COUPLED:x:[= Y", "X = 1")
        )

    def test_a_block_comment_ending_before_the_bracket_leaves_it_unclosed(self) -> None:
        self.assertEqual(
            [Unclosed("x", "the end of its comment")], found("/* COUPLED:x:[= Y */", "X = 1")
        )

    def test_a_blank_line_before_the_bracket_leaves_it_unclosed(self) -> None:
        self.assertEqual([Unclosed("x", "a blank line")], found("COUPLED:x:[= Y", "", "more text]"))

    def test_the_end_of_the_file_before_the_bracket_leaves_it_unclosed(self) -> None:
        self.assertEqual([Unclosed("x", "the end of the file")], found("COUPLED:x:[= Y"))

    def test_an_unclosed_tag_is_placed_on_its_first_line(self) -> None:
        self.assertEqual(
            [Placed(Unclosed("x", "the end of its comment"), 0, 0, None, 10, 10)],
            find_tags(["# COUPLED:x:[= Y", "X = 1"]),
        )


def end_problems(*lines: str) -> list[str]:
    return [problem for item in found(*lines) if isinstance(item, End) for problem in item.problems]


class Closes(unittest.TestCase):
    def test_an_end_closes_the_block_its_key_opened(self) -> None:
        placed = find_tags(["# COUPLED:x:[same-as]", "def f():", "    pass", "# COUPLED:x:END"])
        self.assertEqual([(Tag, 3), (End, None)], [(type(p.found), p.close) for p in placed])
        self.assertEqual([], end_problems("# COUPLED:x:[same-as]", "f()", "# COUPLED:x:END"))

    def test_a_structural_tag_without_an_end_has_no_close(self) -> None:
        self.assertIsNone(find_tags(["# COUPLED:x:[same-as]", "f()"])[0].close)

    def test_an_end_in_markdown_or_a_block_comment_is_found(self) -> None:
        for line in ("COUPLED:x:END", "/* COUPLED:x:END */", "<!-- COUPLED:x:END -->"):
            self.assertEqual(3, find_tags(["COUPLED:x:[same-as]", "a", "b", line])[0].close, line)

    def test_an_end_with_no_tag_of_its_key_above_it_is_reported(self) -> None:
        self.assertEqual(
            ["Open this block with a tag of COUPLED:x: above it, or drop this END"],
            end_problems("f()", "# COUPLED:x:END", "# COUPLED:x:[same-as]", "g()"),
        )

    def test_an_end_after_a_value_op_is_reported(self) -> None:
        self.assertEqual(
            [
                "Drop this END: the tag of COUPLED:x: on line 1 has a value op, "
                "so it describes only the line after it"
            ],
            end_problems("# COUPLED:x:[= Y]", "X = 1", "# COUPLED:x:END"),
        )

    def test_blocks_of_different_keys_nest(self) -> None:
        lines = [
            "# COUPLED:outer:[same-as]",
            "def f():",
            "    # COUPLED:inner:[same-shape]",
            "    TABLE = {",
            "    }",
            "    # COUPLED:inner:END",
            "# COUPLED:outer:END",
        ]
        self.assertEqual([6, 5, None, None], [p.close for p in find_tags(lines)])
        self.assertEqual([], end_problems(*lines))

    def test_a_block_nested_in_one_of_its_own_key_is_reported(self) -> None:
        self.assertEqual(
            ["This block holds another of COUPLED:x: (line 2): blocks of one key can't nest"],
            end_problems(
                "# COUPLED:x:[same-as]",
                "# COUPLED:x:[same-as]",
                "f()",
                "# COUPLED:x:END",
                "# COUPLED:x:END",
            ),
        )

    def test_blocks_that_overlap_are_reported(self) -> None:
        self.assertEqual(
            [
                "Blocks can nest but not overlap: the block of COUPLED:b: on line 2 runs on "
                "past this END"
            ],
            end_problems(
                "# COUPLED:a:[same-as]",
                "# COUPLED:b:[same-as]",
                "f()",
                "# COUPLED:a:END",
                "# COUPLED:b:END",
            ),
        )

    def test_a_lowercase_end_is_malformed(self) -> None:
        self.assertEqual([Malformed()], found("# COUPLED:x:end"))


if __name__ == "__main__":
    unittest.main()
