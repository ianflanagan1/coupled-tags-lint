"""Behaviour of the coupled-tags-lint command, run as a program. The rules for tags and values
are tested in test_tags.py, test_values.py and test_check.py.

Each test writes its files into a fresh directory that isn't a git work tree, so the lint falls
back to grep. A test that checks relations
or reads the clean status line records the lock first, with --update, so the lock's own problems
don't join in.
"""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class Ran:
    status: int
    output: str
    errors: str


class Sandbox:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = root / "repo"
        self.repo.mkdir()

    def file(self, name: str, *lines: str) -> None:
        """Writes the lines to name in the repository."""
        _write(self.repo / name, lines)

    def run(self, *args: str, cwd: Path | None = None) -> Ran:
        env = {**os.environ, "NO_COLOR": "1"}
        env.pop("FORCE_COLOR", None)
        done = subprocess.run(
            [sys.executable, "-m", "coupled_tags_lint", *args],
            cwd=cwd or self.root,
            env=env,
            capture_output=True,
            text=True,
        )
        return Ran(done.returncode, done.stdout, done.stderr)

    def lint(self, *options: str) -> Ran:
        return self.run(*options, str(self.repo))

    def lock(self) -> None:
        """Records the groups as they are now in the lock."""
        self.lint("--update")

    def git_init(self) -> None:
        subprocess.run(["git", "init", "--quiet"], cwd=self.repo, check=True)


def _write(path: Path, lines: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(line + "\n" for line in lines))


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path.resolve())


def assert_clean(ran: Ran) -> None:
    assert ran.status == 0, f"unexpected problems: {ran.errors}"


def assert_problem(ran: Ran, text: str) -> None:
    assert ran.status == 1
    assert text in ran.errors


# --- Repositories


def test_a_group_whose_values_agree_across_files_is_clean(sandbox: Sandbox) -> None:
    sandbox.file(
        "app.py", "MAX_UPLOAD_MB = 8  # COUPLED:upload-size-limit:[<= client_max_body_size]"
    )
    sandbox.file(
        "nginx.conf", "client_max_body_size 10m;  # COUPLED:upload-size-limit:[>= MAX_UPLOAD_MB]"
    )
    sandbox.lock()
    ran = sandbox.lint()
    assert_clean(ran)
    assert ran.output == "➖ No problems in 1 COUPLED key.\n"


def test_a_relation_that_fails_is_reported_at_its_site(sandbox: Sandbox) -> None:
    sandbox.file(
        "app.py", "MAX_UPLOAD_MB = 12  # COUPLED:upload-size-limit:[<= client_max_body_size]"
    )
    sandbox.file(
        "nginx.conf", "client_max_body_size 10m;  # COUPLED:upload-size-limit:[>= MAX_UPLOAD_MB]"
    )
    assert_problem(sandbox.lint(), "app.py:1 Relation doesn't hold with nginx.conf:1: 12 <= 10m")


def test_problems_are_counted_in_the_status_line_before_them(sandbox: Sandbox) -> None:
    sandbox.file("a.py", "X = 1  # COUPLED:x-limit:[=]")
    sandbox.file("b.py", "Y = 1  # COUPLED:y-limit:[=]")
    sandbox.lock()
    ran = sandbox.lint()
    assert ran.status == 1
    assert ran.errors.splitlines()[0] == "⚠️ 2 problems in COUPLED tags."


def test_a_tag_on_a_comment_line_is_checked_against_the_line_below(sandbox: Sandbox) -> None:
    sandbox.file("Dockerfile", "# COUPLED:node-version:[=]", "FROM node:24.1-slim")
    sandbox.file("compose.yaml", "image: node:22.3-alpine  # COUPLED:node-version:[=]")
    assert_problem(
        sandbox.lint(), "compose.yaml:1 Relation doesn't hold with Dockerfile:1: 22.3 = 24.1"
    )


def test_in_a_git_work_tree_ignored_files_are_skipped(sandbox: Sandbox) -> None:
    sandbox.git_init()
    sandbox.file(".gitignore", "build/")
    sandbox.file("a.py", "X = 1  # COUPLED:x-limit:[=; //github.com/me/x/a.py]")
    sandbox.file("build/b.py", "X = 1  # COUPLED:x-limit:[=]")
    sandbox.file("build/c.py", "Y = 1  # COUPLED:y-limit:[=]")
    sandbox.lock()
    assert_clean(sandbox.lint())


def test_a_directory_given_by_a_relative_path_is_scanned(sandbox: Sandbox) -> None:
    sandbox.git_init()
    sandbox.file("a.py", "X = 1  # COUPLED:x-limit:[=]")
    assert_problem(sandbox.run("repo", cwd=sandbox.root), "a.py:1 Orphan key")


def test_an_excluded_path_is_skipped(sandbox: Sandbox) -> None:
    sandbox.file("a.py", "X = 1  # COUPLED:x-limit:[=; //github.com/me/x/a.py]")
    sandbox.file("docs/b.py", "X = 2  # COUPLED:x-limit:[=]")
    sandbox.lint("--update", "-x", "docs/")
    assert_clean(sandbox.lint("-x", "docs/"))


def test_list_prints_every_key_and_its_sites(sandbox: Sandbox) -> None:
    sandbox.file("a.py", "X = 1  # COUPLED:x-limit:[=]")
    sandbox.file("b.py", "X = 1  # COUPLED:x-limit:[=]")
    ran = sandbox.lint("-l")
    assert "x-limit (2)" in ran.output
    assert "    a.py:1" in ran.output


# --- Tags across lines


def test_a_tag_running_on_over_its_comment_lines_is_checked(sandbox: Sandbox) -> None:
    sandbox.file(
        "Dockerfile",
        "# The image the app is built on.",
        "# COUPLED:node-version:[=; ./.nvmrc;",
        "# ./package.json#/engines/node] Pinned for the build.",
        "# Slim keeps the image small.",
        "FROM node:24.22.1-slim",
    )
    sandbox.file(".nvmrc", "24.22.1")
    sandbox.file("package.json", '{"engines": {"node": "22"}}')
    sandbox.lock()
    assert_problem(
        sandbox.lint(), "./package.json#/engines/node Relation doesn't hold with Dockerfile:2"
    )


def test_a_trailing_tag_running_on_over_comment_lines_is_checked(sandbox: Sandbox) -> None:
    sandbox.file(
        "app.py",
        "MAX_UPLOAD_MB = 8  # COUPLED:upload-size-limit:[<=",
        "#   ./limits.json#/upload_limit_mb]",
        "TIMEOUT = 5",
    )
    sandbox.file("limits.json", '{"upload_limit_mb": 6}')
    sandbox.lock()
    assert_problem(
        sandbox.lint(), "app.py:1 Relation doesn't hold with ./limits.json#/upload_limit_mb"
    )


def test_a_tag_whose_comment_ends_before_its_bracket_is_reported(sandbox: Sandbox) -> None:
    sandbox.file("a.py", "# COUPLED:x-limit:[= Y", "X = 1")
    sandbox.file("b.py", "Y = 1  # COUPLED:x-limit:[=]")
    assert_problem(sandbox.lint(), "a.py:1 Close the tag with ] before the end of its comment")


def test_a_tag_with_a_blank_line_before_its_code_is_reported(sandbox: Sandbox) -> None:
    sandbox.file("a.py", "# COUPLED:x-limit:[=]", "", "X = 1")
    sandbox.file("b.py", "Y = 1  # COUPLED:x-limit:[=]")
    assert_problem(
        sandbox.lint(), "a.py:1 Put the line this tag describes directly after its comment"
    )


def test_a_tagged_file_that_is_not_utf8_is_reported(sandbox: Sandbox) -> None:
    (sandbox.repo / "a.txt").write_bytes(b"caf\xe9  # COUPLED:x-limit:[=]\n")
    assert_problem(sandbox.lint(), "a.txt Can't read this file as UTF-8")


# --- Files the tags refer to


def test_a_one_line_file_a_tag_refers_to_is_checked(sandbox: Sandbox) -> None:
    sandbox.file("Dockerfile", "FROM node:24.22.1-alpine  # COUPLED:node-version:[=; ./.nvmrc]")
    sandbox.file(".nvmrc", "22")
    assert_problem(sandbox.lint(), "./.nvmrc Relation doesn't hold with Dockerfile:1: 22 = 24.22.1")


def test_a_pointer_into_json_a_tag_refers_to_is_checked(sandbox: Sandbox) -> None:
    sandbox.file(
        "Dockerfile",
        "FROM node:24.22.1-alpine  # COUPLED:node-version:[= ./package.json#/engines/node]",
    )
    sandbox.file("package.json", '{"engines": {"node": "24"}}')
    sandbox.lock()
    assert_clean(sandbox.lint())


def test_a_pointer_to_a_file_that_is_missing_is_reported(sandbox: Sandbox) -> None:
    sandbox.file(
        "Dockerfile",
        "FROM node:24.22.1-alpine  # COUPLED:node-version:[= ./package.json#/engines/node]",
    )
    assert_problem(
        sandbox.lint(),
        "./package.json#/engines/node A tag of COUPLED:node-version: refers to this file, "
        "but it isn't there",
    )


def test_a_file_without_a_pointer_that_is_missing_is_reported(sandbox: Sandbox) -> None:
    sandbox.file("a.py", "X = 1  # COUPLED:x-limit:[=; ./.nvmrc]")
    sandbox.lock()
    assert_problem(sandbox.lint(), "./.nvmrc A tag of COUPLED:x-limit: refers to this file")


def test_an_optional_file_that_is_missing_is_skipped(sandbox: Sandbox) -> None:
    sandbox.file("a.py", "X = 1  # COUPLED:x-limit:[=; ./.env?]")
    sandbox.lock()
    assert_clean(sandbox.lint())


def test_other_repositories_are_named_as_not_checked(sandbox: Sandbox) -> None:
    sandbox.file(
        "a.go",
        'const CacheIgnore = "/cache/"'
        " // COUPLED:tool-cache-dir:[=; //github.com/me/code-rulebook/rules/caches.yaml]",
    )
    sandbox.lock()
    ran = sandbox.lint()
    assert_clean(ran)
    assert ran.output == (
        "➖ No problems in 1 COUPLED key. Not checked, as they're other repositories: "
        "github.com/me/code-rulebook.\n"
    )


# --- Fixing tags


def test_fix_writes_each_equation_at_both_its_sites_and_every_file_on_every_tag(
    sandbox: Sandbox,
) -> None:
    sandbox.file("a.json", '{"key_a": 10}')
    sandbox.file("b.json", '{"key_b": 11}')
    sandbox.file("c.php", "<?php", "// COUPLED:example:[]", "$c = 12;")
    sandbox.file("d.php", "<?php", "// COUPLED:example:[= $c + 1]", "$d = 13;")
    sandbox.file(
        "e.php",
        "<?php",
        "// COUPLED:example:[= $d + 1; = $c + 2; = ./b.json#/key_b + 3;",
        "//   = ./a.json#/key_a + 4]",
        "$e = 14;",
    )
    sandbox.lock()
    assert_problem(sandbox.lint(), "d.php:2 Add `= $e - 1` to this tag")
    ran = sandbox.lint("--fix", "--update")
    assert_clean(ran)
    assert ran.output.startswith("✅ Fixed tags in c.php, d.php. Updated .coupled-tags.lock.")
    assert (sandbox.repo / "c.php").read_text().splitlines()[1] == (
        "// COUPLED:example:[= $d - 1; = $e - 2; ./b.json#/key_b; ./a.json#/key_a]"
    )
    assert (sandbox.repo / "d.php").read_text().splitlines()[1] == (
        "// COUPLED:example:[= $c + 1; = $e - 1; ./b.json#/key_b; ./a.json#/key_a]"
    )


def test_fix_leaves_what_it_cannot_write_to_be_reported(sandbox: Sandbox) -> None:
    sandbox.file("a.php", "// COUPLED:x:[= $c - 2]", "$a = 1;")
    sandbox.file("b.php", "// COUPLED:x:[= $c - 1]", "$a = 2;")
    sandbox.file("c.php", "// COUPLED:x:[= $a + 1]", "$c = 3;")
    sandbox.lock()
    ran = sandbox.lint("--fix")
    assert_problem(ran, "c.php:1 `$a` names several sites: ")
    assert (sandbox.repo / "c.php").read_text() == "// COUPLED:x:[= $a + 1]\n$c = 3;\n"


# --- The lock


def test_update_records_the_groups_in_the_lock(sandbox: Sandbox) -> None:
    sandbox.file("a.py", "X = 1  # COUPLED:x-limit:[=]")
    sandbox.file("b.py", "Y = 1  # COUPLED:x-limit:[=]")
    ran = sandbox.lint("--update")
    assert_clean(ran)
    assert ran.output == "✅ Updated .coupled-tags.lock.\nNo problems in 1 COUPLED key.\n"
    assert '"path": "a.py", "relation": "="' in (sandbox.repo / ".coupled-tags.lock").read_text()
    assert sandbox.lint().output == "➖ No problems in 1 COUPLED key.\n"


def test_update_records_the_lock_even_when_relations_fail(sandbox: Sandbox) -> None:
    sandbox.file("a.py", "X = 1  # COUPLED:x-limit:[=]")
    sandbox.file("b.py", "Y = 2  # COUPLED:x-limit:[=]")
    ran = sandbox.lint("--update")
    assert ran.status == 1
    assert "🛑 Stopped." in ran.errors
    assert "Updated .coupled-tags.lock." in ran.errors
    assert "Relation doesn't hold" in ran.errors
    assert (sandbox.repo / ".coupled-tags.lock").exists()


def test_a_repository_with_tags_and_no_lock_is_reported(sandbox: Sandbox) -> None:
    sandbox.file("a.py", "X = 1  # COUPLED:x-limit:[=]")
    sandbox.file("b.py", "Y = 1  # COUPLED:x-limit:[=]")
    assert_problem(sandbox.lint(), ".coupled-tags.lock There's no lock.")


def test_an_edited_structural_block_fails_until_the_lock_is_updated(sandbox: Sandbox) -> None:
    end = "# COUPLED:vat:END"
    sandbox.file("a.py", "# COUPLED:vat:[same-as]", "def vat(net):", "    return net / 5", end)
    sandbox.file("b.py", "# COUPLED:vat:[same-as]", "def vat(net):", "    return net / 5", end)
    sandbox.lock()
    sandbox.file("b.py", "# COUPLED:vat:[same-as]", "def vat(net):", "    return net / 6", end)
    assert_problem(sandbox.lint(), "b.py:1 It has changed since .coupled-tags.lock")
    sandbox.lock()
    assert_clean(sandbox.lint())


def test_an_end_after_a_value_op_is_reported(sandbox: Sandbox) -> None:
    sandbox.file("a.py", "X = 1  # COUPLED:x-limit:[=]", "# COUPLED:x-limit:END")
    sandbox.file("b.py", "Y = 1  # COUPLED:x-limit:[=]")
    assert_problem(sandbox.lint(), "a.py:2 Drop this END")


# --- Exit status


def test_a_directory_with_no_tags_exits_zero(sandbox: Sandbox) -> None:
    sandbox.file("a.py", "X = 1")
    ran = sandbox.lint()
    assert_clean(ran)
    assert ran.output == "➖ No COUPLED tags.\n"


def test_help_describes_the_options(sandbox: Sandbox) -> None:
    ran = sandbox.run("-h")
    assert ran.status == 0
    assert "usage: coupled-tags-lint [-h] [-l] [-x <path>] [--fix] [--update] [<dir>]" in ran.output
    assert "exclude a path prefix" in ran.output
    assert "Exit status: 0 clean, 1 problems found, 2 usage error." in ran.output


def test_an_unknown_option_is_a_usage_error(sandbox: Sandbox) -> None:
    assert sandbox.lint("-q").status == 2


def test_a_directory_that_does_not_exist_is_a_usage_error(sandbox: Sandbox) -> None:
    assert sandbox.run(str(sandbox.root / "missing")).status == 2
