import unittest

from coupled_tags_lint.core.check import (
    Content,
    FileRead,
    Missing,
    Problem,
    Site,
    check,
    file_sites,
    fixes,
    unchecked,
)


def sites(*files: str) -> list[Site]:
    """A site for each tag in files, each being the text of its own file `<n>.txt`."""
    return [
        site
        for number, text in enumerate(files, start=1)
        for site in file_sites(f"{number}.txt", text.splitlines())
    ]


def named(**files: str) -> list[Site]:
    """A site for each tag in files, by name, with `_` in a name read as `.`."""
    return [
        site
        for name, text in files.items()
        for site in file_sites(name.replace("_", "."), text.splitlines())
    ]


def messages(problems: list[Problem]) -> list[str]:
    return [f"{problem.where} {problem.message}" for problem in problems]


def fixed(group: list[Site], files: dict[str, FileRead]) -> dict[str, str]:
    """Each tag fixes rewrites, by `path:line`, as it would write it."""
    return {f"{fix.path}:{fix.line + 1}": fix.tag.relation() for fix in fixes(group, files)}


ONE = {name: Content("1") for name in (".nvmrc", "x.txt", "y.txt", ".env")}


class Closes(unittest.TestCase):
    def test_a_problem_with_an_end_is_reported_at_it(self) -> None:
        self.assertEqual(
            [
                "1.txt:3 Drop this END: the tag of COUPLED:x: on line 1 has a value op, so it "
                "describes only the line after it"
            ],
            messages(
                check(
                    sites("# COUPLED:x:[=]\nX = 1\n# COUPLED:x:END", "Y = 1  # COUPLED:x:[=]"), {}
                )
            ),
        )

    def test_an_end_is_not_a_site_of_its_group(self) -> None:
        self.assertEqual(
            ["1.txt:1 Orphan key with only one site"],
            messages(check(sites("# COUPLED:x:[same-as]\nf()\n# COUPLED:x:END"), {})),
        )


class Groups(unittest.TestCase):
    def test_a_key_with_two_agreeing_sites_is_clean(self) -> None:
        self.assertEqual([], check(sites("X = 1  # COUPLED:x:[=]", "x 1;  # COUPLED:x:[=]"), {}))

    def test_a_key_with_one_site_is_an_orphan(self) -> None:
        self.assertEqual(
            ["1.txt:1 Orphan key with only one site"],
            messages(check(sites("X = 1  # COUPLED:x:[=]"), {})),
        )

    def test_a_single_site_referring_to_another_repository_is_not_an_orphan(self) -> None:
        self.assertEqual([], check(sites("X = 1  # COUPLED:x:[=; //github.com/me/x/a.py]"), {}))

    def test_a_single_site_referring_to_a_file_is_not_an_orphan(self) -> None:
        self.assertEqual([], check(sites("X = 1  # COUPLED:x:[=; ./.nvmrc]"), ONE))

    def test_a_malformed_tag_is_reported(self) -> None:
        self.assertIn(
            "1.txt:1 Malformed tag", " ".join(messages(check(sites("# COUPLED:X:[=]"), {})))
        )

    def test_a_malformed_tag_says_what_a_key_is(self) -> None:
        self.assertIn(
            "lowercase letters and digits, in words joined by single hyphens",
            " ".join(messages(check(sites("# COUPLED:-x:[=]"), {}))),
        )

    def test_a_clause_problem_is_reported_at_its_tag(self) -> None:
        problems = messages(
            check(sites("# COUPLED:x:[equals Y]", "# COUPLED:x:[same-as]\ntype A struct {"), {})
        )
        self.assertIn(
            "1.txt:1 Start each clause with an op (= != < <= > >= same-as same-shape",
            " ".join(problems),
        )

    def test_a_group_without_an_op_is_reported(self) -> None:
        self.assertIn(
            "Give a tag of COUPLED:x: an op",
            " ".join(messages(check(sites("X = 1  # COUPLED:x:[]", "Y = 1  # COUPLED:x:[]"), {}))),
        )

    def test_a_bare_op_in_a_group_that_mixes_ops_is_reported(self) -> None:
        problems = messages(check(sites("X = 1  # COUPLED:x:[=]", "Y = 1  # COUPLED:x:[>= X]"), {}))
        self.assertIn(
            "1.txt:1 Name the other value after =: its group mixes ops", " ".join(problems)
        )

    def test_a_group_mixing_value_and_structural_ops_is_reported(self) -> None:
        problems = messages(
            check(sites("X = 1  # COUPLED:x:[=]", "# COUPLED:x:[same-as]\ntype A struct {"), {})
        )
        self.assertIn("2.txt:1 Use only value ops", " ".join(problems))

    def test_structural_groups_are_not_compared(self) -> None:
        lines = (
            "# COUPLED:x:[same-shape]\ntype A struct {",
            "# COUPLED:x:[same-shape]\ntype A struct {",
            "a = 1  # COUPLED:y:[subset-of c]",
            "c = 2  # COUPLED:y:[superset-of a]",
        )
        self.assertEqual([], check(sites(*lines), {}))


class BareEquals(unittest.TestCase):
    def test_bare_equal_sites_that_differ_are_reported_at_the_odd_one(self) -> None:
        problems = messages(
            check(
                sites(
                    "A = 'a'  # COUPLED:x:[=]",
                    "B = 'a'  # COUPLED:x:[=]",
                    "C = 'c'  # COUPLED:x:[=]",
                ),
                {},
            )
        )
        self.assertEqual(["3.txt:1 Relation doesn't hold with 1.txt:1: `c` = `a`"], problems)

    def test_a_file_joins_a_group_of_bare_equals(self) -> None:
        group = sites(
            "FROM node:24.22.1  # COUPLED:v:[=; ./.nvmrc]",
            "image: node:24.22.1  # COUPLED:v:[=; ./.nvmrc]",
        )
        self.assertEqual([], check(group, {".nvmrc": Content("24\n")}))
        problems = messages(check(group, {".nvmrc": Content("22\n")}))
        self.assertEqual(["./.nvmrc Relation doesn't hold with 1.txt:1: 22 = 24.22.1"], problems)

    def test_an_unreadable_site_says_how_to_pick_its_value(self) -> None:
        problems = messages(
            check(sites("RUN mkdir /tmp/p \\  # COUPLED:x:[=]", "x = /tmp/p  # COUPLED:x:[=]"), {})
        )
        self.assertIn("1.txt:1 Can't read this site's value", " ".join(problems))
        self.assertIn("@/<regex>/", " ".join(problems))

    def test_an_unreadable_file_is_reported(self) -> None:
        group = sites("X = 1  # COUPLED:x:[=; ./a.json#/x]", "Y = 1  # COUPLED:x:[=; ./a.json#/x]")
        problems = messages(check(group, {"a.json": Content('{"y": 1}')}))
        self.assertEqual(
            ["./a.json#/x Can't read this site's value: it has nothing at #/x"], problems
        )


class Equations(unittest.TestCase):
    def test_a_relation_that_holds_is_clean_from_both_ends(self) -> None:
        group = sites(
            "client_max_body_size 10m;  # COUPLED:u:[>= MAX_UPLOAD_MB]",
            "MAX_UPLOAD_MB = 8  # COUPLED:u:[<= client_max_body_size]",
        )
        self.assertEqual([], check(group, {}))

    def test_a_relation_that_fails_is_reported_with_its_values(self) -> None:
        group = sites(
            "client_max_body_size 6m;  # COUPLED:u:[>= MAX_UPLOAD_MB]",
            "MAX_UPLOAD_MB = 8  # COUPLED:u:[<= client_max_body_size]",
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
            "server.keepAliveTimeout = 65_000;  // COUPLED:k:[> Idle timeout * 1000]",
            "Idle timeout: `60` s. COUPLED:k:[< server.keepAliveTimeout / 1000]",
        )
        self.assertEqual([], check(group, {}))

    def test_a_tag_relates_several_sites_and_files(self) -> None:
        group = named(
            c_php="$c = 12; // COUPLED:example:[= $d - 1; = $e - 2; ./a.json#/a; ./b.json#/b]",
            d_php="$d = 13; // COUPLED:example:[= $c + 1; = $e - 1; ./a.json#/a; ./b.json#/b]",
            e_php="$e = 14; // COUPLED:example:[= $d + 1; = $c + 2; = ./b.json#/b + 3; "
            "= ./a.json#/a + 4]",
        )
        files: dict[str, FileRead] = {
            "a.json": Content('{"a": 10}'),
            "b.json": Content('{"b": 11}'),
        }
        self.assertEqual([], check(group, files))
        files["a.json"] = Content('{"a": 9}')
        self.assertEqual(
            ["e.php:1 Relation doesn't hold with ./a.json#/a: 14 = 9 + 4 (= 13)"],
            messages(check(group, files)),
        )

    def test_a_name_no_other_site_has_is_reported(self) -> None:
        group = sites("X = 1  # COUPLED:x:[< Z]", "Y = 2  # COUPLED:x:[> X]")
        self.assertIn(
            "1.txt:1 No other site of COUPLED:x: has `Z`", " ".join(messages(check(group, {})))
        )

    def test_a_name_matches_only_as_a_whole_name_with_its_case(self) -> None:
        group = sites("X = 1  # COUPLED:x:[< X]", "MAX_X = 2  # COUPLED:x:[> x]")
        problems = " ".join(messages(check(group, {})))
        self.assertIn("1.txt:1 No other site of COUPLED:x: has `X`", problems)
        self.assertIn("2.txt:1 No other site of COUPLED:x: has `x`", problems)

    def test_a_name_matches_the_site_declaring_it_before_one_mentioning_it(self) -> None:
        group = sites(
            "A = 1  # COUPLED:x:[< B; < C]",
            "B = 2  # COUPLED:x:[> A; = C - 1]",
            r"C = max(B, 3)  # COUPLED:x:[> A; = B + 1; @/(\d+)\)/]",
        )
        self.assertEqual([], check(group, {}))

    def test_an_equation_can_relate_a_file(self) -> None:
        group = sites("FROM php:8.5-fpm  # COUPLED:p:[= ./.php-version]")
        self.assertEqual([], check(group, {".php-version": Content("8.5.1")}))

    def test_a_selector_picks_the_value_to_compare(self) -> None:
        group = sites(
            r"APP_URL=http://localhost:8080  # COUPLED:port:[= HTTP_PORT; @/:(\d+)$/]",
            "HTTP_PORT=8080  # COUPLED:port:[= APP_URL]",
        )
        self.assertEqual([], check(group, {}))


class AmbiguousNames(unittest.TestCase):
    GROUP = (
        "$a = 1;  // COUPLED:x:[= $c - 2]",
        "$a = 2;  // COUPLED:x:[= $c - 1]",
    )

    def test_a_name_several_sites_declare_is_reported_with_how_to_say_which(self) -> None:
        group = sites(*self.GROUP, "$c = 3;  // COUPLED:x:[= $a + 1]")
        self.assertIn(
            "3.txt:1 `$a` names several sites: 1.txt:1, 2.txt:1. Say which with its file: "
            "`./1.txt#$a`",
            messages(check(group, {})),
        )

    def test_a_name_in_its_file_picks_out_one_site(self) -> None:
        group = sites(*self.GROUP, "$c = 3;  // COUPLED:x:[= ./2.txt#$a + 1; = ./1.txt#$a + 2]")
        self.assertEqual([], check(group, {}))

    def test_a_file_alone_picks_out_its_one_site(self) -> None:
        group = sites(*self.GROUP, "$c = 3;  // COUPLED:x:[= ./2.txt + 1; = ./1.txt + 2]")
        self.assertEqual([], check(group, {}))

    def test_a_file_holding_several_sites_needs_a_name(self) -> None:
        group = named(
            a_php="$a = 1;  // COUPLED:x:[= $c - 2]\n$b = 2;  // COUPLED:x:[= $c - 1]",
            c_php="$c = 3;  // COUPLED:x:[= ./a.php + 1]",
        )
        self.assertIn(
            "c.php:1 `./a.php` holds several tags of COUPLED:x:. Say which with the name of its "
            "value: `./a.php#<name>`",
            messages(check(group, {})),
        )

    def test_a_pointer_into_a_tagged_file_is_reported(self) -> None:
        group = sites("X = 1  # COUPLED:x:[= ./2.txt#/a]", "Y = 1  # COUPLED:x:[= X]")
        self.assertIn(
            "1.txt:1 Drop #/a: `./2.txt` holds tags of COUPLED:x:", messages(check(group, {}))[0]
        )

    def test_a_name_into_a_file_without_tags_is_reported(self) -> None:
        group = sites("X = 1  # COUPLED:x:[= ./a.json#a]")
        self.assertIn(
            "1.txt:1 Point into `./a.json` with a JSON Pointer",
            " ".join(messages(check(group, {"a.json": Content('{"a": 1}')}))),
        )


class Mirrors(unittest.TestCase):
    def test_an_equation_missing_at_its_other_site_is_reported_there(self) -> None:
        group = sites("$d = 13;  // COUPLED:x:[]", "$e = 14;  // COUPLED:x:[= $d + 1]")
        self.assertEqual(
            [
                "1.txt:1 Add `= $e - 1` to this tag, the mirror of `= $d + 1` at 2.txt:1: an "
                "equation is written at both its sites; --fix adds it"
            ],
            messages(check(group, {})),
        )

    def test_the_fix_adds_the_mirror(self) -> None:
        group = sites("$d = 13;  // COUPLED:x:[]", "$e = 14;  // COUPLED:x:[= $d + 1]")
        self.assertEqual({"1.txt:1": "= $e - 1"}, fixed(group, {}))

    def test_a_mirror_flips_the_op_and_undoes_the_formula(self) -> None:
        for stated, mirrored in (
            ("< $d * 2", "> $e / 2"),
            ("<= $d / 2", ">= $e * 2"),
            ("> $d - 3", "< $e + 3"),
            ("!= $d", "!= $e"),
        ):
            group = sites("$d = 1;  // COUPLED:x:[]", f"$e = 1;  // COUPLED:x:[{stated}]")
            self.assertEqual({"1.txt:1": mirrored}, fixed(group, {}), stated)

    def test_a_structural_mirror_swaps_subset_and_superset(self) -> None:
        group = sites("a = 1  # COUPLED:y:[subset-of c]", "c = 2  # COUPLED:y:[]")
        self.assertEqual({"2.txt:1": "superset-of a"}, fixed(group, {}))

    def test_a_bare_op_at_the_other_site_is_its_mirror(self) -> None:
        group = sites("X = 1  # COUPLED:x:[=]", "Y = 1  # COUPLED:x:[= X]")
        self.assertEqual([], check(group, {}))

    def test_two_equations_that_do_not_mirror_each_other_are_reported_once(self) -> None:
        group = sites("$d = 13;  // COUPLED:x:[= $e - 2]", "$e = 14;  // COUPLED:x:[= $d + 1]")
        problems = [
            message for message in messages(check(group, {})) if "doesn't hold" not in message
        ]
        self.assertEqual(
            [
                "1.txt:1 `= $e - 2` here and `= $d + 1` at 2.txt:1 don't mirror each other: that "
                "one would be `= $d + 2`. Change one to match the other"
            ],
            problems,
        )
        self.assertEqual({}, fixed(group, {}))

    def test_a_mirror_names_a_site_as_other_tags_already_do(self) -> None:
        group = named(
            a_php="$a = 1;  // COUPLED:x:[= $c - 2]",
            b_php="$a = 2;  // COUPLED:x:[= $c - 1]",
            c_php="$c = 3;  // COUPLED:x:[= ./b.php#$a + 1]",
        )
        self.assertEqual({"c.php:1": "= ./b.php#$a + 1; = ./a.php#$a + 2"}, fixed(group, {}))

    def test_a_mirror_is_not_added_to_a_tag_with_a_ref_that_does_not_resolve(self) -> None:
        group = named(
            a_php="$a = 1;  // COUPLED:x:[= $c - 2]",
            b_php="$a = 2;  // COUPLED:x:[= $c - 1]",
            c_php="$c = 3;  // COUPLED:x:[= $a + 1]",
        )
        self.assertEqual({}, fixed(group, {}))

    def test_a_site_nothing_relates_is_reported(self) -> None:
        group = sites("X = 1  # COUPLED:x:[=]", "Y = 1  # COUPLED:x:[=]", "Z = 1  # COUPLED:x:[]")
        self.assertIn("3.txt:1 Nothing relates this site", " ".join(messages(check(group, {}))))


class FilesTheGroupRefersTo(unittest.TestCase):
    def test_tags_referring_to_the_same_files_in_any_order_are_clean(self) -> None:
        group = sites(
            "X = 1  # COUPLED:x:[=; ./x.txt; ./.nvmrc?]",
            "x 1;  # COUPLED:x:[=; ./.nvmrc?; ./x.txt]",
        )
        self.assertEqual([], check(group, ONE))

    def test_a_tag_is_told_to_add_the_files_other_tags_refer_to(self) -> None:
        group = sites(
            "X = 1  # COUPLED:x:[=; ./x.txt; ./y.txt]",
            "x 1;  # COUPLED:x:[=; ./y.txt]",
        )
        self.assertEqual(
            [
                "2.txt:1 Add `./x.txt` to this tag: every tag of COUPLED:x: in a repository "
                "refers to the same files; --fix adds it"
            ],
            messages(check(group, ONE)),
        )
        self.assertEqual({"2.txt:1": "=; ./y.txt; ./x.txt"}, fixed(group, ONE))

    def test_a_file_an_equation_relates_counts_and_is_added_bare(self) -> None:
        group = sites(
            "X = 2  # COUPLED:x:[= ./x.txt + 1; = Y]",
            "Y = 2  # COUPLED:x:[= X]",
        )
        self.assertEqual({"2.txt:1": "= X; ./x.txt"}, fixed(group, ONE))

    def test_a_missing_file_is_not_added_to_other_tags(self) -> None:
        group = sites("X = 1  # COUPLED:x:[=; ./gone.txt]", "Y = 1  # COUPLED:x:[=]")
        self.assertEqual({}, fixed(group, {"gone.txt": Missing()}))

    def test_a_file_in_another_repository_is_added_to_other_tags(self) -> None:
        group = sites("X = 1  # COUPLED:x:[=; //github.com/a/b/c.py]", "Y = 1  # COUPLED:x:[=]")
        self.assertEqual({"2.txt:1": "=; //github.com/a/b/c.py"}, fixed(group, {}))

    def test_a_file_marked_differently_on_two_tags_is_reported_at_both(self) -> None:
        group = sites("X = 1  # COUPLED:x:[=; ./.env?]", "x 1;  # COUPLED:x:[=; ./.env]")
        self.assertEqual(
            [
                "1.txt:1 Write `./.env?` the same way on every tag of COUPLED:x:; another "
                "writes it `./.env`",
                "2.txt:1 Write `./.env` the same way on every tag of COUPLED:x:; another "
                "writes it `./.env?`",
            ],
            messages(check(group, ONE)),
        )

    def test_a_file_the_search_already_finds_is_reported(self) -> None:
        group = sites("X = 1  # COUPLED:x:[=; ./2.txt]", "x 1;  # COUPLED:x:[=]")
        self.assertEqual(
            ["1.txt:1 Drop `./2.txt`: the search already finds its tag of COUPLED:x:"],
            messages(check(group, {"2.txt": Content("x 1;")})),
        )

    def test_a_file_that_is_missing_is_reported(self) -> None:
        problems = messages(check(sites("X = 1  # COUPLED:x:[=; ./.nvmrc]"), {".nvmrc": Missing()}))
        self.assertEqual(1, len(problems))
        self.assertIn("./.nvmrc A tag of COUPLED:x: refers to this file", problems[0])
        self.assertIn("mark it optional: ./<path>?", problems[0])

    def test_an_optional_file_that_is_missing_is_not_reported(self) -> None:
        self.assertEqual([], check(sites("X = 1  # COUPLED:x:[=; ./.env?]"), {".env": Missing()}))

    def test_a_longer_file_without_a_tag_or_pointer_is_reported_in_a_value_group(self) -> None:
        problems = messages(
            check(sites("X = 1  # COUPLED:x:[=; ./x.yaml]"), {"x.yaml": Content("a: 1\nb: 2\n")})
        )
        self.assertEqual(1, len(problems))
        self.assertIn("it has no tag of COUPLED:x: and more than one line", problems[0])

    def test_a_file_nothing_relates_is_reported(self) -> None:
        group = sites("X = 1  # COUPLED:x:[< Y; ./x.txt]", "Y = 2  # COUPLED:x:[> X; ./x.txt]")
        self.assertEqual(
            [
                "./x.txt Nothing relates this file: give a tag of COUPLED:x: an equation to it, "
                "such as `= ./x.txt`"
            ],
            messages(check(group, ONE)),
        )

    def test_a_pointer_into_a_file_read_by_its_tags_is_reported(self) -> None:
        group = sites("X = 1  # COUPLED:x:[=; ./x.json#/a]")
        problems = messages(check(group, {"x.json": Content("x = 1  # COUPLED:x:[=]\n")}))
        self.assertEqual(1, len(problems))
        self.assertIn("./x.json#/a Drop #/a", problems[0])

    def test_a_pointer_in_a_structural_group_is_not_reported(self) -> None:
        group = sites("# COUPLED:s:[same-shape; ./x.json#/a]\ntype A struct {")
        self.assertEqual([], check(group, {"x.json": Content("# COUPLED:s:[same-shape]\nB\n")}))


class OtherRepositories(unittest.TestCase):
    def test_the_repositories_referred_to_are_left_unchecked(self) -> None:
        group = sites(
            "X = 1  # COUPLED:x:[=; //github.com/me/infra/a.tf; //github.com/me/edge/b.tf]",
            "x 1;  # COUPLED:x:[=; //github.com/me/infra/a.tf; //github.com/me/edge/b.tf]",
        )
        self.assertEqual([], check(group, {}))
        self.assertEqual(["github.com/me/infra", "github.com/me/edge"], unchecked(group))

    def test_a_name_no_site_here_has_is_left_unchecked_when_another_repository_is_named(
        self,
    ) -> None:
        group = sites(
            "X = 8  # COUPLED:x:[<= limit; //github.com/me/infra/a.tf]",
            "Y = 8  # COUPLED:x:[= X; //github.com/me/infra/a.tf]",
        )
        problems = messages(check(group, {}))
        self.assertNotIn("limit", " ".join(problems))

    def test_sites_here_are_still_compared_when_another_repository_is_named(self) -> None:
        group = sites(
            "X = 1  # COUPLED:x:[=; //github.com/me/infra/a.tf]",
            "x 2;  # COUPLED:x:[=; //github.com/me/infra/a.tf]",
        )
        self.assertEqual(
            ["2.txt:1 Relation doesn't hold with 1.txt:1: 2 = 1"], messages(check(group, {}))
        )


if __name__ == "__main__":
    unittest.main()
