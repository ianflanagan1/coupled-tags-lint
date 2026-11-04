import unittest

from coupled_tags_lint.core.check import Problem, Site, Source, check
from coupled_tags_lint.core.tags import find_tags
from coupled_tags_lint.core.values import Unreadable, Value, value_line


def sites(*lines: str) -> list[Site]:
    """A site for each tag in lines, each line being its own file `<n>.txt`."""
    found = []
    for number, line in enumerate(lines, start=1):
        for tag in find_tags(line):
            found.append(Site(f"{number}.txt:1", tag, value_line([line], 0)))
    return found


def messages(problems: list[Problem]) -> list[str]:
    return [f"{problem.where} {problem.message}" for problem in problems]


class Groups(unittest.TestCase):
    def test_a_key_with_two_agreeing_sites_is_clean(self) -> None:
        self.assertEqual([], check(sites("X = 1  # COUPLED:x: =", "x 1;  # COUPLED:x: ="), {}))

    def test_a_key_with_one_site_is_an_orphan(self) -> None:
        self.assertEqual(
            ["1.txt:1 Orphan key with only one site"],
            messages(check(sites("X = 1  # COUPLED:x: ="), {})),
        )

    def test_a_single_site_whose_note_names_another_site_is_not_an_orphan(self) -> None:
        self.assertEqual([], check(sites("X = 1  # COUPLED:x: = (also other-repo: src/x.py)"), {}))

    def test_a_single_site_whose_note_only_explains_is_an_orphan(self) -> None:
        self.assertIn(
            "Orphan key", " ".join(messages(check(sites("X = 1  # COUPLED:x: = (seconds)"), {})))
        )

    def test_a_malformed_tag_is_reported(self) -> None:
        self.assertIn(
            "1.txt:1 Malformed tag", " ".join(messages(check(sites("# COUPLED:X: ="), {})))
        )

    def test_a_tag_without_an_op_names_the_ops(self) -> None:
        problems = messages(check(sites("# COUPLED:x: equals Y", "# COUPLED:x: same-as"), {}))
        self.assertIn(
            "1.txt:1 Start the relation with one of = != < <= > >= same-as same-shape",
            " ".join(problems),
        )

    def test_a_bare_op_in_a_group_that_mixes_ops_needs_a_target(self) -> None:
        problems = messages(check(sites("X = 1  # COUPLED:x: =", "Y = 1  # COUPLED:x: >= X"), {}))
        self.assertIn(
            "1.txt:1 Name the other value after =: its group mixes ops", " ".join(problems)
        )

    def test_a_group_mixing_value_and_structural_ops_is_reported(self) -> None:
        problems = messages(check(sites("X = 1  # COUPLED:x: =", "# COUPLED:x: same-as"), {}))
        self.assertIn("2.txt:1 Use only value ops", " ".join(problems))

    def test_structural_groups_are_not_compared(self) -> None:
        lines = (
            "# COUPLED:x: same-shape",
            "# COUPLED:x: same-shape",
            "a, b  # COUPLED:y: subset-of c",
            "c  # COUPLED:y: superset-of a",
        )
        self.assertEqual([], check(sites(*lines), {}))


class BareEquals(unittest.TestCase):
    def test_bare_equal_sites_that_differ_are_reported_at_the_odd_one(self) -> None:
        problems = messages(
            check(
                sites(
                    "A = 'a'  # COUPLED:x: =", "B = 'a'  # COUPLED:x: =", "C = 'c'  # COUPLED:x: ="
                ),
                {},
            )
        )
        self.assertEqual(["3.txt:1 Relation doesn't hold with 1.txt:1: `c` = `a`"], problems)

    def test_an_outside_source_joins_a_group_of_equals(self) -> None:
        group = sites(
            "FROM node:24.22.1  # COUPLED:v: = (also .nvmrc)", "image: node:24.22.1  # COUPLED:v: ="
        )
        self.assertEqual([], check(group, {"v": [Source(".nvmrc", ".nvmrc", Value("24"))]}))
        problems = messages(check(group, {"v": [Source(".nvmrc", ".nvmrc", Value("22"))]}))
        self.assertEqual([".nvmrc Relation doesn't hold with 1.txt:1: 22 = 24.22.1"], problems)

    def test_an_unreadable_site_says_how_to_pick_its_value(self) -> None:
        problems = messages(
            check(sites("RUN mkdir /tmp/p \\  # COUPLED:x: =", "x = /tmp/p  # COUPLED:x: ="), {})
        )
        self.assertIn("1.txt:1 Can't read this site's value", " ".join(problems))
        self.assertIn("@/<regex>/", " ".join(problems))

    def test_an_unreadable_outside_source_is_reported(self) -> None:
        group = sites("X = 1  # COUPLED:x: = (also a.json#/x)", "Y = 1  # COUPLED:x: =")
        problems = messages(
            check(
                group,
                {"x": [Source("a.json#/x", "a.json#/x", Unreadable("it has nothing at #/x"))]},
            )
        )
        self.assertEqual(
            ["a.json#/x Can't read this site's value: it has nothing at #/x"], problems
        )


class Targets(unittest.TestCase):
    def test_a_relation_that_holds_is_clean_from_both_ends(self) -> None:
        group = sites(
            "client_max_body_size 10m;  # COUPLED:u: >= MAX_UPLOAD_MB",
            "MAX_UPLOAD_MB = 8  # COUPLED:u: <= client_max_body_size",
        )
        self.assertEqual([], check(group, {}))

    def test_a_relation_that_fails_is_reported_with_its_values(self) -> None:
        group = sites(
            "client_max_body_size 6m;  # COUPLED:u: >= MAX_UPLOAD_MB",
            "MAX_UPLOAD_MB = 8  # COUPLED:u: <= client_max_body_size",
        )
        self.assertEqual(
            [
                "1.txt:1 Relation doesn't hold with 2.txt:1: 6m >= 8",
                "2.txt:1 Relation doesn't hold with 1.txt:1: 8 <= 6m",
            ],
            messages(check(group, {})),
        )

    def test_a_formula_converts_units(self) -> None:
        group = sites(
            "server.keepAliveTimeout = 65_000;  // COUPLED:k: > Idle timeout * 1000",
            "Idle timeout: `60` s. COUPLED:k: < server.keepAliveTimeout / 1000",
        )
        self.assertEqual([], check(group, {}))

    def test_a_target_no_other_site_mentions_is_reported(self) -> None:
        group = sites("X = 1  # COUPLED:x: < Z", "Y = 2  # COUPLED:x: > X")
        self.assertIn(
            "1.txt:1 No other site in the group mentions Z", " ".join(messages(check(group, {})))
        )

    def test_a_target_matches_only_as_a_whole_name_with_its_case(self) -> None:
        group = sites("X = 1  # COUPLED:x: < X", "MAX_X = 2  # COUPLED:x: > x")
        problems = " ".join(messages(check(group, {})))
        self.assertIn("1.txt:1 No other site in the group mentions X", problems)
        self.assertIn("2.txt:1 No other site in the group mentions x", problems)

    def test_a_target_mentioned_at_several_sites_is_reported(self) -> None:
        group = sites(
            "A = 1  # COUPLED:x: < B", "B = 2  # COUPLED:x: > A", "C = B  # COUPLED:x: >= A"
        )
        self.assertIn(
            "1.txt:1 B is mentioned at several sites", " ".join(messages(check(group, {})))
        )

    def test_a_target_can_name_an_outside_source(self) -> None:
        group = sites("FROM php:8.5-fpm  # COUPLED:p: = .php-version (also .php-version)")
        self.assertEqual(
            [], check(group, {"p": [Source(".php-version", ".php-version", Value("8.5.1"))]})
        )

    def test_a_selector_picks_the_value_to_compare(self) -> None:
        group = sites(
            r"APP_URL=http://localhost:8080  # COUPLED:port: = HTTP_PORT @/:(\d+)$/",
            "HTTP_PORT=8080  # COUPLED:port: =",
        )
        self.assertEqual([], check(group, {}))


if __name__ == "__main__":
    unittest.main()
