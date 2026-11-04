"""Behaviour of the coupled-tags-lint command, run as a program. The rules for tags and values
are tested in test_tags.py, test_values.py and test_check.py.

Each test writes its files into a fresh directory that isn't a git work tree, so the lint falls
back to grep, and gets its own empty directory of other checkouts.
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
        self.roots = root / "roots"
        self.repo.mkdir()
        self.roots.mkdir()

    def file(self, name: str, *lines: str) -> None:
        """Writes the lines to name in the repository."""
        _write(self.repo / name, lines)

    def other(self, repo: str, path: str, *lines: str) -> None:
        """Writes the lines to path in another checked-out repository."""
        (self.roots / repo / ".git").mkdir(parents=True, exist_ok=True)
        _write(self.roots / repo / path, lines)

    def run(self, *args: str, cwd: Path | None = None) -> Ran:
        env = {**os.environ, "COUPLED_TAGS_REPO_ROOTS": str(self.roots), "NO_COLOR": "1"}
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
        "app.py", "MAX_UPLOAD_MB = 8  # COUPLED:upload-size-limit: <= client_max_body_size"
    )
    sandbox.file(
        "nginx.conf", "client_max_body_size 10m;  # COUPLED:upload-size-limit: >= MAX_UPLOAD_MB"
    )
    ran = sandbox.lint()
    assert_clean(ran)
    assert ran.output == "➖ No problems in 1 COUPLED key.\n"


def test_a_relation_that_fails_is_reported_at_its_site(sandbox: Sandbox) -> None:
    sandbox.file(
        "app.py", "MAX_UPLOAD_MB = 12  # COUPLED:upload-size-limit: <= client_max_body_size"
    )
    sandbox.file(
        "nginx.conf", "client_max_body_size 10m;  # COUPLED:upload-size-limit: >= MAX_UPLOAD_MB"
    )
    assert_problem(sandbox.lint(), "app.py:1 Relation doesn't hold with nginx.conf:1: 12 <= 10m")


def test_problems_are_counted_in_the_status_line_before_them(sandbox: Sandbox) -> None:
    sandbox.file("a.py", "X = 1  # COUPLED:x-limit: =")
    sandbox.file("b.py", "Y = 1  # COUPLED:y-limit: =")
    ran = sandbox.lint()
    assert ran.status == 1
    assert ran.errors.splitlines()[0] == "⚠️ 2 problems in COUPLED tags."


def test_a_tag_on_a_comment_line_is_checked_against_the_line_below(sandbox: Sandbox) -> None:
    sandbox.file("Dockerfile", "# COUPLED:node-version: =", "FROM node:24.1-slim")
    sandbox.file("compose.yaml", "image: node:22.3-alpine  # COUPLED:node-version: =")
    assert_problem(
        sandbox.lint(), "compose.yaml:1 Relation doesn't hold with Dockerfile:1: 22.3 = 24.1"
    )


def test_in_a_git_work_tree_ignored_files_are_skipped(sandbox: Sandbox) -> None:
    sandbox.git_init()
    sandbox.file(".gitignore", "build/")
    sandbox.file("a.py", "X = 1  # COUPLED:x-limit: = (also other-repo: x.py)")
    sandbox.file("build/b.py", "X = 1  # COUPLED:x-limit: =")
    sandbox.file("build/c.py", "Y = 1  # COUPLED:y-limit: =")
    assert_clean(sandbox.lint())


def test_a_directory_given_by_a_relative_path_is_scanned(sandbox: Sandbox) -> None:
    sandbox.git_init()
    sandbox.file("a.py", "X = 1  # COUPLED:x-limit: =")
    assert_problem(sandbox.run("repo", cwd=sandbox.root), "a.py:1 Orphan key")


def test_an_excluded_path_is_skipped(sandbox: Sandbox) -> None:
    sandbox.file("a.py", "X = 1  # COUPLED:x-limit: = (also other-repo: x.py)")
    sandbox.file("docs/b.py", "X = 2  # COUPLED:x-limit: =")
    assert_clean(sandbox.lint("-x", "docs/"))


def test_list_prints_every_key_and_its_sites(sandbox: Sandbox) -> None:
    sandbox.file("a.py", "X = 1  # COUPLED:x-limit: =")
    sandbox.file("b.py", "X = 1  # COUPLED:x-limit: =")
    ran = sandbox.lint("-l")
    assert "x-limit (2)" in ran.output
    assert "    a.py:1" in ran.output


# --- Also notes


def test_a_one_line_file_an_also_note_names_is_checked(sandbox: Sandbox) -> None:
    sandbox.file("Dockerfile", "FROM node:24.22.1-alpine  # COUPLED:node-version: = (also .nvmrc)")
    sandbox.file(".nvmrc", "22")
    assert_problem(sandbox.lint(), ".nvmrc Relation doesn't hold with Dockerfile:1: 22 = 24.22.1")


def test_a_pointer_into_json_an_also_note_names_is_checked(sandbox: Sandbox) -> None:
    sandbox.file(
        "Dockerfile",
        "FROM node:24.22.1-alpine  # COUPLED:node-version: = (also package.json#/engines/node)",
    )
    sandbox.file("package.json", '{"engines": {"node": "24"}}')
    assert_clean(sandbox.lint())


def test_a_pointer_to_a_file_that_is_missing_is_reported(sandbox: Sandbox) -> None:
    sandbox.file(
        "Dockerfile",
        "FROM node:24.22.1-alpine  # COUPLED:node-version: = (also package.json#/engines/node)",
    )
    assert_problem(
        sandbox.lint(),
        "package.json#/engines/node Can't read this site's value: the file isn't there",
    )


def test_a_file_without_a_pointer_that_is_missing_is_only_listed(sandbox: Sandbox) -> None:
    sandbox.file("a.py", "X = 1  # COUPLED:x-limit: = (also .env)")
    assert_clean(sandbox.lint())


def test_a_tagged_site_in_another_checked_out_repository_is_checked(sandbox: Sandbox) -> None:
    sandbox.file(
        "a.go",
        'const CacheIgnore = "/cache/"'
        " // COUPLED:tool-cache-dir: = (also code-rulebook: rules/x.yaml)",
    )
    sandbox.other(
        "code-rulebook",
        "rules/x.yaml",
        "  # COUPLED:tool-cache-dir: = (also go-baseline: a.go)",
        "  ignore: '/caches/'",
    )
    assert_problem(
        sandbox.lint(),
        "code-rulebook: rules/x.yaml:1 Relation doesn't hold with a.go:1: `/caches/` = `/cache/`",
    )


def test_a_tag_in_another_repository_whose_value_cannot_be_read_is_left_to_that_repository(
    sandbox: Sandbox,
) -> None:
    sandbox.file(
        "a.go",
        'const CacheIgnore = "/cache/"'
        " // COUPLED:tool-cache-dir: = (also code-rulebook: rules/x.yaml)",
    )
    sandbox.other(
        "code-rulebook",
        "rules/x.yaml",
        "  # COUPLED:tool-cache-dir: = (also go-baseline: a.go)",
        "  - id: one two",
    )
    assert_clean(sandbox.lint())


def test_a_repository_under_another_owner_is_found_by_its_name(sandbox: Sandbox) -> None:
    sandbox.file(
        "a.py",
        "MAX_UPLOAD_MB = 8  # COUPLED:upload-size-limit: <= upload_limit_mb"
        " (also acme/infra: limits.json#/upload_limit_mb)",
    )
    sandbox.other("infra", "limits.json", '{"upload_limit_mb": 6}')
    assert_problem(
        sandbox.lint(),
        "a.py:1 Relation doesn't hold with acme/infra: limits.json#/upload_limit_mb: 8 <= 6",
    )


def test_a_repository_that_is_not_checked_out_is_skipped(sandbox: Sandbox) -> None:
    sandbox.file(
        "a.go",
        'const CacheIgnore = "/cache/"'
        " // COUPLED:tool-cache-dir: = (also code-rulebook: rules/x.yaml)",
    )
    assert_clean(sandbox.lint())


# --- Exit status


def test_a_directory_with_no_tags_exits_zero(sandbox: Sandbox) -> None:
    sandbox.file("a.py", "X = 1")
    ran = sandbox.lint()
    assert_clean(ran)
    assert ran.output == "➖ No COUPLED tags.\n"


def test_help_describes_the_options(sandbox: Sandbox) -> None:
    ran = sandbox.run("-h")
    assert ran.status == 0
    assert "usage: coupled-tags-lint [-h] [-l] [-x <path>] [<dir>]" in ran.output
    assert "exclude a path prefix" in ran.output
    assert "Exit status: 0 clean, 1 problems found, 2 usage error." in ran.output


def test_an_unknown_option_is_a_usage_error(sandbox: Sandbox) -> None:
    assert sandbox.lint("-q").status == 2


def test_a_directory_that_does_not_exist_is_a_usage_error(sandbox: Sandbox) -> None:
    assert sandbox.run(str(sandbox.root / "missing")).status == 2
