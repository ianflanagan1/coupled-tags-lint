import unittest
from decimal import Decimal

from coupled_tags_lint.core.tags import Arith, Formula, ValueOp, find_tags
from coupled_tags_lint.core.values import (
    Fails,
    Holds,
    Incomparable,
    Unreadable,
    Value,
    block_lines,
    compare,
    declared_name,
    described_line,
    json_at,
    read_file_value,
    read_value,
    unit_of,
    value_line,
)


def block(*lines: str) -> list[str]:
    """The block of the first tag in lines."""
    placed = find_tags(list(lines))
    return block_lines(list(lines), placed[0], placed)


class ValueLines(unittest.TestCase):
    def test_a_trailing_tag_describes_the_code_before_its_comment(self) -> None:
        for line, code in (
            ("MAX_UPLOAD_MB = 8  # COUPLED:x:[=]", "MAX_UPLOAD_MB = 8"),
            ("client_max_body_size 10m;  # COUPLED:x:[=]", "client_max_body_size 10m;"),
            ("mapId: 'a#b',  // COUPLED:x:[=]", "mapId: 'a#b',"),
            (
                "xdebug.output_dir = /tmp/profiles  ; COUPLED:x:[=]",
                "xdebug.output_dir = /tmp/profiles",
            ),
            ("- Map ID: `dog-cafe-map`. COUPLED:x:[=]", "- Map ID: `dog-cafe-map`."),
        ):
            self.assertEqual(code, value_line([line], 0, 0), line)

    def test_a_tag_on_a_comment_line_describes_the_next_line_of_code(self) -> None:
        lines = [
            "# Base image. COUPLED:x:[=] Pinned for the build.",
            "# COUPLED:y:[same-as]",
            "# Another comment.",
            "FROM node:24-slim  # pinned",
        ]
        self.assertEqual("FROM node:24-slim", value_line(lines, 0, 0))

    def test_a_tag_running_on_over_lines_describes_the_line_of_code_after_them(self) -> None:
        lines = ["# COUPLED:x:[=; ./.nvmrc;", "# ./package.json#/engines/node]", "FROM node:24"]
        self.assertEqual("FROM node:24", value_line(lines, 0, 1))

    def test_a_trailing_tag_running_on_describes_its_own_line(self) -> None:
        lines = ["MAX = 8  # COUPLED:x:[<= limit;", "#   ./l.json#/limit]", "Y = 1"]
        self.assertEqual("MAX = 8", value_line(lines, 0, 1))

    def test_a_line_declares_the_name_left_of_its_assignment(self) -> None:
        for code, name in (
            ("MAX_UPLOAD_MB = 8", "MAX_UPLOAD_MB"),
            ("$d = 13;", "$d"),
            ('public const string CACHE_IGNORE = "/cache/";', "CACHE_IGNORE"),
            ("server.keepAliveTimeout = 65_000;", "server.keepAliveTimeout"),
            ('node-version: "24"', "node-version"),
            ("APP_URL=http://localhost:8080", "APP_URL"),
            ("client_max_body_size 10m;", "client_max_body_size"),
        ):
            self.assertEqual(name, declared_name(code), code)

    def test_a_line_that_names_nothing_declares_no_name(self) -> None:
        for code in ("FROM node:24.22.1-slim", "- Map ID: `dog-cafe-map`.", "if a == b:"):
            self.assertIsNone(declared_name(code), code)

    def test_a_tag_with_a_blank_line_before_its_code_describes_nothing(self) -> None:
        self.assertIsNone(value_line(["# COUPLED:x:[=]", "", "X = 1"], 0, 0))
        self.assertEqual([], block("# COUPLED:x:[same-as]", "", "def f():"))

    def test_a_tag_with_no_code_after_it_describes_nothing(self) -> None:
        self.assertIsNone(value_line(["# COUPLED:x:[=]", "# end"], 0, 0))


class DescribedLines(unittest.TestCase):
    def test_a_trailing_tag_describes_its_own_line(self) -> None:
        self.assertEqual(0, described_line(["X = 1  # COUPLED:x:[=]", "Y = 2"], 0, 0))

    def test_a_tag_on_its_own_line_describes_the_next_line_past_comments(self) -> None:
        self.assertEqual(2, described_line(["# COUPLED:x:[=]", "# More words.", "X = 1"], 0, 0))

    def test_a_tag_on_its_own_line_of_markdown_describes_the_next_line(self) -> None:
        self.assertEqual(1, described_line(["COUPLED:x:[same-as]", "- rule: A unit is"], 0, 0))

    def test_a_tag_with_a_blank_line_before_its_code_describes_no_line(self) -> None:
        self.assertIsNone(described_line(["COUPLED:x:[same-as]", "", "- rule: A unit is"], 0, 0))


class ReadingValues(unittest.TestCase):
    def test_the_value_of_common_lines_is_read(self) -> None:
        for code, value in (
            ("private const string FOLDER = 'user';", "user"),
            ('SESSIONS = "claude-sessions"', "claude-sessions"),
            ("- API key: `AIza123`.", "AIza123"),
            ("FROM php:8.5-fpm-bookworm AS builder", "8.5"),
            ("FROM --platform=linux/amd64 node:24.22.1-alpine", "24.22.1"),
            ("image: docker.io/library/node:24.22.1-alpine", "24.22.1"),
            ("HTTP_PORT=8080", "8080"),
            ("IMAGE_NAMESPACE: ianflanagan1", "ianflanagan1"),
            ("xdebug.output_dir = /tmp/profiles", "/tmp/profiles"),
            ("dir=$HOME/.local/state/x", "$HOME/.local/state/x"),
            ("server.keepAliveTimeout = 65_000;", "65_000"),
            ("client_max_body_size 10m;", "10m"),
            ("location ^~ /media/ {", "/media/"),
        ):
            self.assertEqual(Value(value), read_value(code, None), code)

    def test_a_line_with_several_quoted_values_is_unreadable(self) -> None:
        self.assertIsInstance(read_value("f('a', 'b')", None), Unreadable)

    def test_a_line_with_no_single_value_is_unreadable(self) -> None:
        for code in (
            "RUN mkdir /tmp/profiles \\",
            "LINTED: bin src config",
            "type listing struct {",
        ):
            self.assertIsInstance(read_value(code, None), Unreadable, code)

    def test_a_selector_picks_its_capture_group(self) -> None:
        self.assertEqual(Value("8080"), read_value("APP_URL=http://localhost:8080", r":(\d+)$"))

    def test_a_selector_without_a_group_picks_its_whole_match(self) -> None:
        self.assertEqual(
            Value("/tmp/profiles"), read_value("RUN mkdir /tmp/profiles \\", r"/tmp/\w+")
        )

    def test_a_selector_that_does_not_match_is_unreadable(self) -> None:
        self.assertIsInstance(read_value("X = 1", r"port (\d+)"), Unreadable)


class FileValues(unittest.TestCase):
    def test_a_one_line_file_is_its_value(self) -> None:
        self.assertEqual(Value("24"), read_file_value("24\n", None))

    def test_a_longer_file_without_a_pointer_has_no_value(self) -> None:
        self.assertIsNone(read_file_value("{\n}\n", None))

    def test_a_pointer_reads_a_value_in_json(self) -> None:
        content = '{"engines": {"node": ">=24"}, "list": [1, 2.5], "a/b": {"~c": "d"}}'
        self.assertEqual(Value(">=24"), read_file_value(content, "/engines/node"))
        self.assertEqual(Value("2.5"), read_file_value(content, "/list/1"))
        self.assertEqual(Value("d"), read_file_value(content, "/a~1b/~0c"))

    def test_a_pointer_to_nothing_or_to_an_object_is_unreadable(self) -> None:
        self.assertIsInstance(read_file_value('{"a": 1}', "/b"), Unreadable)
        self.assertIsInstance(read_file_value('{"a": {}}', "/a"), Unreadable)
        self.assertIsInstance(read_file_value('{"a": true}', "/a"), Unreadable)

    def test_a_pointer_into_a_file_that_is_not_json_is_unreadable(self) -> None:
        self.assertIsInstance(read_file_value("a = 1", "/a"), Unreadable)


class Comparing(unittest.TestCase):
    def test_equal_strings_hold_and_different_ones_fail(self) -> None:
        self.assertEqual(Holds(), compare(ValueOp.EQ, "/cache/", "/cache/", None))
        self.assertIsInstance(compare(ValueOp.EQ, "/cache/", "/caches/", None), Fails)
        self.assertEqual(Holds(), compare(ValueOp.NE, "staging", "prod", None))

    def test_versions_compare_on_the_components_both_give(self) -> None:
        self.assertEqual(Holds(), compare(ValueOp.EQ, "24", "24.22.1", None))
        self.assertEqual(Holds(), compare(ValueOp.EQ, "v3.12", "3.12.4", None))
        self.assertIsInstance(compare(ValueOp.EQ, "24.1", "24.2", None), Fails)
        self.assertEqual(Holds(), compare(ValueOp.LT, "8.5", "8.10", None))

    def test_numbers_compare_numerically_ignoring_a_unit_suffix(self) -> None:
        self.assertEqual(Holds(), compare(ValueOp.GE, "10m", "8", None))
        self.assertEqual(Holds(), compare(ValueOp.EQ, "65_000", "65000", None))
        self.assertIsInstance(compare(ValueOp.LT, "9", "8", None), Fails)

    def test_ordering_strings_is_incomparable(self) -> None:
        self.assertIsInstance(compare(ValueOp.LT, "a", "b", None), Incomparable)

    def test_a_formula_applies_to_the_other_value(self) -> None:
        self.assertEqual(
            Holds(), compare(ValueOp.GT, "65_000", "60", Formula(Arith.MUL, Decimal(1000)))
        )
        self.assertEqual(
            Holds(), compare(ValueOp.LT, "60", "65_000", Formula(Arith.DIV, Decimal(1000)))
        )
        self.assertEqual(Holds(), compare(ValueOp.GE, "65s", "60", Formula(Arith.ADD, Decimal(5))))
        self.assertEqual(Holds(), compare(ValueOp.EQ, "55", "60", Formula(Arith.SUB, Decimal(5))))

    def test_a_failing_formula_shows_its_working(self) -> None:
        verdict = compare(ValueOp.GT, "59000", "60", Formula(Arith.MUL, Decimal(1000)))
        self.assertEqual(Fails("59000 > 60 * 1000 (= 60000)"), verdict)

    def test_a_formula_on_a_value_that_is_not_a_number_is_incomparable(self) -> None:
        self.assertIsInstance(
            compare(ValueOp.EQ, "a", "60", Formula(Arith.ADD, Decimal(1))), Incomparable
        )

    def test_dividing_by_zero_is_incomparable(self) -> None:
        self.assertIsInstance(
            compare(ValueOp.EQ, "1", "60", Formula(Arith.DIV, Decimal(0))), Incomparable
        )


class Blocks(unittest.TestCase):
    def test_a_block_runs_from_the_line_its_tag_describes_to_its_end(self) -> None:
        self.assertEqual(
            ["private int vat(int net) {", "return net / 5;", "// rounded down", "}"],
            block(
                "/**",
                " * COUPLED:vat:[same-as]",
                " */",
                "private int vat(int net) {",
                "    return net / 5;",
                "",
                "    // rounded down",
                "}",
                "// COUPLED:vat:END",
                "private int other() {",
            ),
        )

    def test_a_block_ends_at_its_end_whatever_the_indentation(self) -> None:
        self.assertEqual(
            ["services:", "app:", "image: app", "worker:"],
            block(
                "# COUPLED:x:[same-shape]",
                "services:",
                "  app:",
                "    image: app",
                "worker:",
                "# COUPLED:x:END",
            ),
        )

    def test_a_trailing_tag_starts_the_block_on_its_own_line_without_its_comment(self) -> None:
        self.assertEqual(
            ["def f():", "return 1"],
            block("def f():  # COUPLED:x:[same-as]", "    return 1", "# COUPLED:x:END"),
        )

    def test_a_tag_without_an_end_describes_only_its_line(self) -> None:
        self.assertEqual(
            ["def f():"], block("# COUPLED:x:[same-as]", "def f():", "    return 1", "")
        )
        self.assertEqual(
            ["disable_functions = exec,popen"],
            block("disable_functions = exec,popen ; COUPLED:x:[subset-of y]", "  other = 1"),
        )

    def test_the_tags_of_blocks_inside_a_block_are_not_part_of_it(self) -> None:
        self.assertEqual(
            ["def f():", "TABLE = {", "}", "x = 1", "return TABLE"],
            block(
                "# COUPLED:outer:[same-as]",
                "def f():",
                "    # COUPLED:inner:[same-shape;",
                "    #   ./schema.json]",
                "    TABLE = {",
                "    }",
                "    # COUPLED:inner:END",
                "    x = 1  # COUPLED:other:[= Y]",
                "    return TABLE",
                "# COUPLED:outer:END",
            ),
        )

    def test_a_tag_describing_no_line_has_no_block(self) -> None:
        self.assertEqual([], block("x = 1", "# COUPLED:x:[same-as]"))

    def test_a_tag_whose_end_comes_before_any_code_has_no_block(self) -> None:
        self.assertEqual([], block("# COUPLED:x:[same-as]", "# COUPLED:x:END", "f()"))


class Units(unittest.TestCase):
    def test_a_number_s_unit_is_its_suffix(self) -> None:
        self.assertEqual("m", unit_of("10m"))
        self.assertEqual("M", unit_of("10M"))
        self.assertEqual("ms", unit_of("65_000 ms"))

    def test_a_number_without_a_suffix_or_a_non_number_has_no_unit(self) -> None:
        for text in ("8", "3.12", "24.22.1", "/cache/", "node"):
            with self.subTest(text=text):
                self.assertIsNone(unit_of(text))


class JsonAt(unittest.TestCase):
    def test_a_pointer_reaches_a_subtree_written_canonically(self) -> None:
        self.assertEqual('{"a": 1, "b": 2}', json_at('{"x": {"b": 2, "a": 1}}', "/x"))

    def test_nothing_at_the_pointer_or_not_json_is_none(self) -> None:
        self.assertIsNone(json_at('{"x": 1}', "/y"))
        self.assertIsNone(json_at("x: 1", "/x"))


if __name__ == "__main__":
    unittest.main()
