#!/usr/bin/env python3
"""Tests for dockerfile_from_checker — stdlib unittest only.

Every Dockerfile in this file is made up for testing.
No real secret appears anywhere in this file.
"""

import ast
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import dockerfile_from_checker as checker

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src/dockerfile_from_checker.py"
DIGEST = "sha256:" + "a" * 64


def run_cli(argv):
    """Run main(argv), capture stdout/stderr, return (code, out, err)."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = checker.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def write(tmp, name, text, encoding="utf-8"):
    path = Path(tmp) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding=encoding)
    return str(path)


def findings_of(text):
    return checker.check_text(text)


class TestFromDetection(unittest.TestCase):
    def test_pinned_tag_passes(self):
        self.assertEqual(findings_of("FROM python:3.12-slim\n"), [])

    def test_untagged_from_fails(self):
        bad = findings_of("FROM python\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["line"], 1)
        self.assertEqual(bad[0]["image"], "python")
        self.assertEqual(bad[0]["reason"], "has no tag")

    def test_latest_fails(self):
        bad = findings_of("FROM node:latest\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["reason"], "uses the :latest tag")

    def test_latest_with_stage_fails(self):
        bad = findings_of("FROM ubuntu:latest AS builder\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["line"], 1)

    def test_untagged_multi_stage_fails(self):
        bad = findings_of(
            "FROM golang:1.22 AS builder\nFROM alpine AS base\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["line"], 2)
        self.assertEqual(bad[0]["image"], "alpine")

    def test_several_from_lines_in_document_order(self):
        bad = findings_of(
            "FROM python\nFROM node:latest\nFROM alpine\n")
        self.assertEqual([item["line"] for item in bad], [1, 2, 3])

    def test_lowercase_from_checked(self):
        bad = findings_of("from python\n")
        self.assertEqual(len(bad), 1)

    def test_mixed_case_from_checked(self):
        bad = findings_of("From python\n")
        self.assertEqual(len(bad), 1)

    def test_leading_whitespace_ok(self):
        bad = findings_of("  FROM python\n")
        self.assertEqual(len(bad), 1)

    def test_platform_flag_skipped(self):
        self.assertEqual(
            findings_of("FROM --platform=linux/amd64 nginx:1.25\n"), [])

    def test_platform_flag_untagged_still_fails(self):
        bad = findings_of("FROM --platform=linux/amd64 nginx\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["image"], "nginx")

    def test_registry_port_is_not_a_tag(self):
        bad = findings_of("FROM registry.example.com:5000/team/app\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["image"],
                         "registry.example.com:5000/team/app")

    def test_registry_port_with_tag_passes(self):
        self.assertEqual(
            findings_of("FROM registry.example.com:5000/team/app:2.0\n"),
            [])

    def test_digest_only_passes(self):
        self.assertEqual(
            findings_of("FROM redis@" + DIGEST + "\n"), [])

    def test_tag_and_digest_passes(self):
        self.assertEqual(
            findings_of("FROM redis:7.2@" + DIGEST + "\n"), [])

    def test_latest_with_digest_passes(self):
        # The digest pins an exact image, so :latest beside
        # it no longer makes the build unreproducible.
        self.assertEqual(
            findings_of("FROM redis:latest@" + DIGEST + "\n"), [])

    def test_scratch_passes(self):
        self.assertEqual(findings_of("FROM scratch\n"), [])

    def test_scratch_with_stage_passes(self):
        self.assertEqual(findings_of("FROM scratch AS final\n"), [])

    def test_arg_image_not_flagged(self):
        self.assertEqual(findings_of("FROM $BASE_IMAGE\n"), [])

    def test_arg_braced_not_flagged(self):
        self.assertEqual(findings_of("FROM ${BASE_IMAGE}\n"), [])

    def test_arg_with_default_not_flagged(self):
        self.assertEqual(
            findings_of("FROM ${BASE_IMAGE:-alpine}\n"), [])

    def test_arg_tag_not_flagged(self):
        self.assertEqual(findings_of("FROM myimage:$TAG\n"), [])

    def test_from_with_no_image_fails(self):
        bad = findings_of("FROM\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["reason"], "has no image")

    def test_from_split_across_lines(self):
        bad = findings_of("FROM python:3.12-slim \\\n  AS base\n")
        self.assertEqual(bad, [])
        bad = findings_of("FROM python \\\n  AS base\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["line"], 1)

    def test_file_with_no_from_passes(self):
        self.assertEqual(
            findings_of("# just a comment\nRUN echo hello\n"), [])

    def test_empty_document_passes(self):
        self.assertEqual(findings_of(""), [])

    def test_run_and_copy_lines_ignored(self):
        self.assertEqual(
            findings_of("FROM python:3.12\nRUN pip install x\n"
                        "COPY . /app\n"),
            [])


class TestSkipping(unittest.TestCase):
    def test_from_in_comment_not_flagged(self):
        self.assertEqual(findings_of("# FROM busybox\n"), [])

    def test_from_in_comment_after_real_from(self):
        bad = findings_of("FROM python\n# FROM busybox\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["line"], 1)

    def test_indented_comment_skipped(self):
        self.assertEqual(findings_of("   # FROM busybox\n"), [])

    def test_word_from_inside_run_not_flagged(self):
        self.assertEqual(
            findings_of("RUN echo FROM python\n"), [])


class TestCLI(unittest.TestCase):
    def test_exit_0_on_clean_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "Dockerfile", "FROM python:3.12-slim\n")
            code, out, _err = run_cli([path])
            self.assertEqual(code, 0)
            self.assertIn("OK", out)

    def test_exit_1_on_flagged_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "Dockerfile", "FROM python\n")
            code, out, _err = run_cli([path])
            self.assertEqual(code, 1)
            self.assertIn("has no tag", out)

    def test_exit_2_on_missing_path(self):
        code, _out, err = run_cli(["no-such-file"])
        self.assertEqual(code, 2)
        self.assertIn("error", err)

    def test_exit_2_on_no_paths(self):
        code, _out, err = run_cli([])
        self.assertEqual(code, 2)

    def test_exit_2_on_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _out, err = run_cli([tmp])
            self.assertEqual(code, 2)
            self.assertIn("no Dockerfiles found", err)

    def test_exit_2_on_bad_flag(self):
        code, _out, _err = run_cli(["--nope"])
        self.assertEqual(code, 2)

    def test_folder_walking(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "Dockerfile", "FROM python:3.12\n")
            write(tmp, "sub/Dockerfile.dev", "FROM node\n")
            write(tmp, "sub/app.dockerfile", "FROM alpine:latest\n")
            write(tmp, "sub/notes.txt", "FROM python\n")
            code, out, _err = run_cli([tmp])
            self.assertEqual(code, 1)
            self.assertIn("FROM line 1 'node' has no tag", out)
            self.assertIn("uses the :latest tag", out)
            self.assertNotIn("notes.txt", out)
            self.assertIn("Checked 3 file(s)", out)

    def test_nested_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a/b/Dockerfile", "FROM python\n")
            code, out, _err = run_cli([tmp])
            self.assertEqual(code, 1)
            self.assertIn("Checked 1 file(s)", out)

    def test_no_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "Dockerfile", "FROM python:3.12\n")
            write(tmp, "sub/Dockerfile", "FROM python\n")
            code, out, _err = run_cli(["--no-recursive", tmp])
            self.assertEqual(code, 0)
            self.assertIn("1 file(s) checked", out)

    def test_exclude(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "Dockerfile", "FROM python\n")
            write(tmp, "skip/Dockerfile", "FROM python\n")
            code, out, _err = run_cli(["--exclude", "skip", tmp])
            self.assertEqual(code, 1)
            self.assertIn("Checked 1 file(s)", out)

    def test_git_folder_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "Dockerfile", "FROM python:3.12\n")
            write(tmp, ".git/Dockerfile", "FROM python\n")
            code, out, _err = run_cli([tmp])
            self.assertEqual(code, 0)
            self.assertIn("1 file(s) checked", out)

    def test_direct_file_checked_whatever_its_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "weird-name.txt", "FROM python\n")
            code, out, _err = run_cli([path])
            self.assertEqual(code, 1)
            self.assertIn("has no tag", out)

    def test_duplicate_paths_checked_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "Dockerfile", "FROM python:3.12\n")
            code, out, _err = run_cli([path, path])
            self.assertEqual(code, 0)
            self.assertIn("1 file(s) checked", out)

    def test_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "Dockerfile", "FROM python\n")
            code, out, _err = run_cli(["--json", path])
            self.assertEqual(code, 1)
            data = json.loads(out)
            self.assertEqual(data["checked"], 1)
            self.assertEqual(data["findings"], 1)
            self.assertEqual(data["files"][0]["findings"][0]["line"], 1)

    def test_stdin(self):
        old_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO("FROM python\n")
            code, out, _err = run_cli(["--stdin"])
        finally:
            sys.stdin = old_stdin
        self.assertEqual(code, 1)
        self.assertIn("has no tag", out)

    def test_stdin_clean(self):
        old_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO("FROM python:3.12\n")
            code, out, _err = run_cli(["--stdin"])
        finally:
            sys.stdin = old_stdin
        self.assertEqual(code, 0)
        self.assertIn("OK", out)

    def test_stdin_via_subprocess(self):
        result = subprocess.run(
            [sys.executable, str(SRC), "--stdin"],
            input="FROM python\n", capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("has no tag", result.stdout)

    def test_stdin_clean_via_subprocess(self):
        result = subprocess.run(
            [sys.executable, str(SRC), "--stdin"],
            input="FROM python:3.12\n", capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("OK", result.stdout)

    def test_version(self):
        code, out, _err = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("dockerfile_from_checker 1.0.0", out)

    def test_non_utf8_file_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "Dockerfile", b"FROM python:\xff\n")
            code, out, _err = run_cli([path])
            self.assertEqual(code, 1)
            self.assertIn("not valid UTF-8", out)

    def test_input_files_left_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "Dockerfile", "FROM python\n")
            before = Path(path).read_text()
            run_cli([path])
            self.assertEqual(Path(path).read_text(), before)

    def test_run_from_another_folder_and_changed_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "fakehome"
            home.mkdir()
            work = Path(tmp) / "work"
            work.mkdir()
            target = write(str(work), "Dockerfile", "FROM python\n")
            env = dict(os.environ)
            env["HOME"] = str(home)
            result = subprocess.run(
                [sys.executable, str(SRC), target],
                cwd=str(work), env=env,
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("has no tag", result.stdout)


class TestExamples(unittest.TestCase):
    def test_run_example_output_matches_sample(self):
        result = subprocess.run(
            ["sh", "examples/run-example.sh"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        expected = (REPO / "examples/sample-output.md").read_text()
        self.assertEqual(result.stdout, expected)

    def test_readme_quotes_match_real_runs(self):
        readme = (REPO / "README.md").read_text()
        clean = subprocess.run(
            [sys.executable, "src/dockerfile_from_checker.py",
             "examples/clean.Dockerfile"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(clean.returncode, 0)
        self.assertIn(clean.stdout.strip(), readme)
        flagged = subprocess.run(
            [sys.executable, "src/dockerfile_from_checker.py",
             "examples/flagged.Dockerfile"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(flagged.returncode, 1)
        self.assertIn(flagged.stdout.strip(), readme)
        folder = subprocess.run(
            [sys.executable, "src/dockerfile_from_checker.py",
             "examples/"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(folder.returncode, 1)
        self.assertIn("Checked 3 file(s), 4 FROM line(s) without a "
                      "pinned tag in 1 file(s).", folder.stdout)
        self.assertIn("Checked 3 file(s), 4 FROM line(s) without a "
                      "pinned tag in 1 file(s).", readme)
        edge = subprocess.run(
            [sys.executable, "src/dockerfile_from_checker.py",
             "examples/edge.Dockerfile"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(edge.returncode, 0)
        self.assertIn(edge.stdout.strip(), readme)
        js = subprocess.run(
            [sys.executable, "src/dockerfile_from_checker.py",
             "--json", "examples/flagged.Dockerfile"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(js.returncode, 1)
        self.assertIn(js.stdout.strip(), readme)


class TestHygiene(unittest.TestCase):
    def _repo_files(self, skip_tests=True, skip_examples=True):
        for root, dirs, files in os.walk(REPO):
            dirs[:] = [d for d in dirs
                       if d not in (".git", "__pycache__")
                       and not (skip_tests and d == "tests")
                       and not (skip_examples and d == "examples")]
            for name in files:
                if name.endswith(".pyc"):
                    continue
                yield Path(root) / name

    def test_no_placeholder_text(self):
        banned = ["TODO", "coming soon", "lorem", "FIXME", "XXX"]
        hits = []
        for path in self._repo_files(skip_tests=True,
                                     skip_examples=False):
            text = path.read_text(errors="ignore")
            for word in banned:
                if word in text:
                    hits.append("%s: %s" % (path.name, word))
        self.assertEqual(hits, [])

    def test_no_absolute_paths(self):
        hits = []
        for path in self._repo_files(skip_tests=True,
                                     skip_examples=False):
            text = path.read_text(errors="ignore")
            for marker in ("/home/", "/Users/", "C:\\"):
                if marker in text:
                    hits.append("%s: %s" % (path.name, marker))
        self.assertEqual(hits, [])

    def test_no_real_secrets_outside_tests_and_examples(self):
        # The source holds no key values at all; the tests
        # and examples hold fake values only, so they are
        # excluded from this scan.
        patterns = [
            re.compile(r"AKIA[0-9A-Z]{16}"),
            re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
            re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
            re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
            re.compile(r"AIza[0-9A-Za-z_-]{35}"),
            re.compile(r"[rs]k_(?:live|test)_[A-Za-z0-9]{16,}"),
            re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
            re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ"),
        ]
        hits = []
        for path in self._repo_files():
            text = path.read_text(errors="ignore")
            for pattern in patterns:
                if pattern.search(text):
                    hits.append("%s: %s" % (path.name, pattern.pattern))
        self.assertEqual(hits, [])

    def test_stdlib_imports_only(self):
        stdlib = set(sys.stdlib_module_names)
        for target in (REPO / "src/dockerfile_from_checker.py",
                       REPO / "tests/test_dockerfile_from_checker.py"):
            tree = ast.parse(target.read_text())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name.split(".")[0]
                                    for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertFalse(
                imported - stdlib - {"dockerfile_from_checker"},
                (target.name, imported))
            self.assertNotIn("yaml", imported)

    def test_no_network_use_in_src(self):
        src = (REPO / "src/dockerfile_from_checker.py").read_text()
        for marker in ("urllib.request", "requests", "socket",
                       "http.client", "urlopen", "urlretrieve"):
            self.assertNotIn(marker, src, marker)

    def test_gitignore_lists_env_first(self):
        lines = (REPO / ".gitignore").read_text().splitlines()
        self.assertEqual(lines[0], ".env")

    def test_ci_runs_this_test_file(self):
        ci = (REPO / ".github/workflows/ci.yml").read_text()
        self.assertIn("tests/test_dockerfile_from_checker.py", ci)
        self.assertIn("ubuntu-latest", ci)
        self.assertIn("3.12", ci)
        self.assertIn("actions/checkout", ci)
        self.assertIn("setup-python", ci)
        self.assertIn("push", ci)
        self.assertIn("pull_request", ci)

    def test_readme_names_hadolint(self):
        readme = (REPO / "README.md").read_text()
        self.assertIn("Hadolint", readme)


if __name__ == "__main__":
    unittest.main()
