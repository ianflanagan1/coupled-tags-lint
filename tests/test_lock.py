import unittest

from coupled_tags_lint.core import lock as lock_module
from coupled_tags_lint.core.check import Content, FileRead, Problem, Site, file_sites
from coupled_tags_lint.core.lock import (
    LOCK_FILE,
    UPDATE,
    Current,
    Lock,
    LockedSite,
    Unparseable,
    current,
    parse,
    render,
    updated,
)

Files = dict[str, list[str]]


def sites(files: Files) -> list[Site]:
    """A site for each tag in files, as the lint finds them."""
    return [site for path, lines in files.items() for site in file_sites(path, lines)]


def now(files: Files, read: dict[str, FileRead]) -> Current:
    return current(sites(files), read)


def locked(files: Files, read: dict[str, FileRead]) -> Lock:
    return updated(None, now(files, read), [])


def compare(old: Lock | Unparseable | None, now: Current, excludes: list[str]) -> list[Problem]:
    """compare, naming coupled-tags-lint's own lock and how to update it."""
    return lock_module.compare(old, now, excludes, LOCK_FILE, UPDATE)


def messages(problems: list[Problem]) -> list[str]:
    return [f"{problem.where} {problem.message}" for problem in problems]


UPLOAD: Files = {
    "app.py": ["MAX_UPLOAD_MB = 8  # COUPLED:upload:[<= client_max_body_size]"],
    "nginx.conf": ["client_max_body_size 10m;  # COUPLED:upload:[>= MAX_UPLOAD_MB]"],
}

VAT: Files = {
    "a.py": ["# COUPLED:vat:[same-as]", "def vat(net):", "    return net / 5", "# COUPLED:vat:END"],
    "b.py": ["# COUPLED:vat:[same-as]", "def vat(net):", "    return net / 5", "# COUPLED:vat:END"],
}


class Recording(unittest.TestCase):
    def test_a_lock_records_each_site_with_its_relation_and_unit(self) -> None:
        self.assertEqual(
            {
                "upload": [
                    LockedSite("app.py", "<= client_max_body_size", None, None),
                    LockedSite("nginx.conf", ">= MAX_UPLOAD_MB", "m", None),
                ]
            },
            locked(UPLOAD, {}),
        )

    def test_a_structural_site_is_recorded_with_its_block_s_fingerprint(self) -> None:
        lock = locked(VAT, {})
        self.assertEqual(2, len(lock["vat"]))
        self.assertIsNotNone(lock["vat"][0].block)
        self.assertEqual(lock["vat"][0].block, lock["vat"][1].block)

    def test_a_lock_reads_back_as_it_was_written(self) -> None:
        lock = locked({**UPLOAD, **VAT}, {})
        self.assertEqual(lock, parse(render(lock)))

    def test_a_lock_puts_each_site_on_its_own_line(self) -> None:
        text = render(locked(UPLOAD, {}))
        self.assertIn(
            '\n      {"path": "nginx.conf", "relation": ">= MAX_UPLOAD_MB", "unit": "m"}\n', text
        )

    def test_a_lock_that_is_not_a_lock_is_unparseable(self) -> None:
        for text in ("nope", "{}", '{"version": 1, "keys": {"x": [{"relation": "="}]}}'):
            with self.subTest(text=text):
                self.assertIsInstance(parse(text), Unparseable)


class Comparing(unittest.TestCase):
    def test_sites_as_the_lock_records_them_are_clean(self) -> None:
        files = {**UPLOAD, **VAT}
        self.assertEqual([], compare(locked(files, {}), now(files, {}), []))

    def test_a_value_change_is_left_to_the_relations(self) -> None:
        changed = {
            **UPLOAD,
            "app.py": ["MAX_UPLOAD_MB = 9  # COUPLED:upload:[<= client_max_body_size]"],
        }
        self.assertEqual([], compare(locked(UPLOAD, {}), now(changed, {}), []))

    def test_no_lock_is_reported_when_there_are_tags(self) -> None:
        self.assertIn("There's no lock", messages(compare(None, now(UPLOAD, {}), []))[0])
        self.assertEqual([], compare(None, now({}, {}), []))

    def test_an_unparseable_lock_is_reported(self) -> None:
        self.assertIn(
            ".coupled-tags.lock Can't read the lock: it has no `keys` object",
            messages(compare(Unparseable("it has no `keys` object"), now(UPLOAD, {}), []))[0],
        )

    def test_a_key_not_in_the_lock_is_reported_at_its_first_site(self) -> None:
        self.assertEqual(
            [
                "a.py:1 COUPLED:vat: isn't in .coupled-tags.lock. Check that its group holds, "
                "then rerun with --update to record it"
            ],
            messages(compare(locked(UPLOAD, {}), now({**UPLOAD, **VAT}, {}), [])),
        )

    def test_a_key_with_no_sites_left_is_reported(self) -> None:
        self.assertIn(
            ".coupled-tags.lock COUPLED:vat: has no sites now",
            messages(compare(locked({**UPLOAD, **VAT}, {}), now(UPLOAD, {}), []))[0],
        )

    def test_a_site_removed_from_a_group_is_reported_even_when_two_remain(self) -> None:
        three = {**VAT, "c.py": VAT["a.py"]}
        self.assertEqual(
            [
                "c.py A site of COUPLED:vat: that .coupled-tags.lock records here is gone. "
                "If removing it was intended, rerun with --update"
            ],
            messages(compare(locked(three, {}), now(VAT, {}), [])),
        )

    def test_a_site_added_to_a_group_is_reported(self) -> None:
        three = {**VAT, "c.py": VAT["a.py"]}
        self.assertIn(
            "c.py:1 This site of COUPLED:vat: isn't in .coupled-tags.lock",
            messages(compare(locked(VAT, {}), now(three, {}), []))[0],
        )

    def test_a_rewritten_relation_is_reported(self) -> None:
        relaxed = {
            **UPLOAD,
            "app.py": ["MAX_UPLOAD_MB = 8  # COUPLED:upload:[!= client_max_body_size]"],
        }
        self.assertIn(
            "app.py:1 Its relation has changed from `<= client_max_body_size`",
            messages(compare(locked(UPLOAD, {}), now(relaxed, {}), []))[0],
        )

    def test_a_changed_unit_is_reported(self) -> None:
        kilobytes = {
            **UPLOAD,
            "nginx.conf": ["client_max_body_size 10k;  # COUPLED:upload:[>= MAX_UPLOAD_MB]"],
        }
        problems = messages(compare(locked(UPLOAD, {}), now(kilobytes, {}), []))
        self.assertEqual(1, len(problems))
        self.assertIn("nginx.conf:1 Its unit has changed from `m` to `k`", problems[0])

    def test_an_edited_structural_block_is_reported_with_the_other_sites(self) -> None:
        edited = {
            **VAT,
            "b.py": [
                "# COUPLED:vat:[same-as]",
                "def vat(net):",
                "    return net / 6",
                "# COUPLED:vat:END",
            ],
        }
        self.assertEqual(
            [
                "b.py:1 It has changed since .coupled-tags.lock. Read every site of COUPLED:vat: "
                "(a.py:1, and the files its tags refer to), change them together so the "
                "group holds, then rerun with --update"
            ],
            messages(compare(locked(VAT, {}), now(edited, {}), [])),
        )

    def test_reindenting_a_structural_block_is_not_a_change(self) -> None:
        reindented = {
            **VAT,
            "b.py": [
                "# COUPLED:vat:[same-as]",
                "def vat(net):",
                "  return net / 5",
                "",
                "# COUPLED:vat:END",
            ],
        }
        self.assertEqual([], compare(locked(VAT, {}), now(reindented, {}), []))

    def test_rewording_a_tag_inside_a_structural_block_is_not_a_change(self) -> None:
        def nested(relation: str) -> list[str]:
            return [
                "# COUPLED:vat:[same-as]",
                "def vat(net):",
                f"    rate = 5  # COUPLED:rate:[{relation}]",
                "    return net / rate",
                "# COUPLED:vat:END",
            ]

        before = {"a.py": nested("= RATE"), "b.py": nested("= RATE")}
        after = {"a.py": nested("= RATE; ./rates.txt"), "b.py": nested("= RATE")}
        self.assertEqual(locked(before, {})["vat"], locked(after, {})["vat"])

    def test_an_edited_file_a_structural_tag_refers_to_is_reported(self) -> None:
        files: Files = {
            "a.go": ["// COUPLED:shape:[same-shape; ./schema.json]", "type listing struct {"]
        }
        lock = locked(files, {"schema.json": Content('{"a": 1}')})
        self.assertEqual([], compare(lock, now(files, {"schema.json": Content('{"a": 1}')}), []))
        self.assertIn(
            "./schema.json It has changed since .coupled-tags.lock",
            messages(compare(lock, now(files, {"schema.json": Content('{"b": 1}')}), []))[0],
        )


class Unseen(unittest.TestCase):
    def test_another_repository_is_not_recorded(self) -> None:
        files: Files = {
            "a.go": [
                "// COUPLED:shape:[same-shape; //github.com/me/infra/shape.json]",
                "type listing struct {",
            ]
        }
        self.assertEqual(["a.go"], [site.path for site in locked(files, {})["shape"]])

    def test_an_excluded_site_is_kept_and_not_compared(self) -> None:
        lock = locked(VAT, {})
        self.assertEqual([], compare(lock, now({"a.py": VAT["a.py"]}, {}), ["b.py"]))
        self.assertEqual(
            lock["vat"],
            sorted(
                updated(lock, now({"a.py": VAT["a.py"]}, {}), ["b.py"])["vat"], key=lambda s: s.path
            ),
        )
