#!/usr/bin/env python3
"""Check Dockerfiles pin a specific image tag.

Run: python3 src/dockerfile_from_checker.py Dockerfile
     python3 src/dockerfile_from_checker.py project/
     python3 src/dockerfile_from_checker.py --stdin < Dockerfile

An untagged or :latest base image makes builds
unreproducible — the same Dockerfile builds a
different image next month, and a breaking base
change lands with no code change of your own.
This tool reads each Dockerfile, finds every
FROM line, and reports each one whose image has
no tag or uses the :latest tag, with the file and
the line number. It exits 1 when any FROM line
is unpinned, so it can fail a CI run. A file
whose FROM lines all pin a tag exits 0.

A FROM line counts as pinned when its image
carries a tag other than latest, or a digest
(image@sha256:... pins an exact image, so a
digest alone counts as pinned too). The special
base image "scratch" has no tag by design and
is never flagged. A tag that comes from a build
argument (FROM $BASE or FROM ${BASE:-alpine})
is not flagged either — the tag is pinned
elsewhere, in the ARG, and this tool cannot see
it from the FROM line alone.

A file given directly on the command line is
always checked, whatever its name. A folder is
walked for files named Dockerfile, Dockerfile.*
or *.dockerfile only, recursively by default
(--no-recursive stops at the top level). .git
folders are never walked, and directory links
are never followed.

It never rewrites a file, never touches the
network, and reads only the files and folders
you point it at.
"""

import argparse
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

__version__ = "1.0.0"

FROM_RE = re.compile(r"^FROM(?:\s+(.*))?$", re.IGNORECASE)


def _parse_image(ref):
    """Decide what a FROM image reference is.

    Returns (image, status) where status is one of
    "pinned", "no-tag", "latest", "arg" or "scratch".
    """
    if ref.lower() == "scratch":
        return ref, "scratch"
    if "$" in ref:
        # A build argument supplies the tag (FROM $BASE
        # or FROM ${BASE:-alpine}); the pin lives in
        # the ARG, so this line is not flagged.
        return ref, "arg"
    if "@" in ref:
        # A digest pins an exact image, with or
        # without a tag beside it.
        return ref, "pinned"
    last = ref.rsplit("/", 1)[-1]
    if ":" not in last:
        return ref, "no-tag"
    tag = last.rsplit(":", 1)[-1]
    if tag == "latest":
        return ref, "latest"
    return ref, "pinned"


def _from_lines(text):
    """Yield (line_number, image_ref) for each FROM line.

    Comment lines are skipped, and a FROM line that
    ends in a backslash is joined with the lines
    that follow it, reporting the line the FROM
    starts on.
    """
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        start = index + 1
        chunk = lines[index]
        index += 1
        while chunk.rstrip().endswith("\\") and index < len(lines):
            chunk = chunk.rstrip()[:-1] + " " + lines[index]
            index += 1
        stripped = chunk.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = FROM_RE.match(stripped)
        if not match:
            continue
        rest = (match.group(1) or "").strip()
        tokens = [tok for tok in rest.split() if not tok.startswith("--")]
        if not tokens:
            yield start, "", "no-image"
            continue
        image = tokens[0]
        yield start, image, _parse_image(image)[1]


def check_text(text):
    """Check one document's text.

    Returns a list of findings, each {"line": int,
    "image": str, "reason": str}, in document order.
    """
    findings = []
    for line, image, status in _from_lines(text):
        if status == "no-tag":
            findings.append({
                "line": line,
                "image": image,
                "reason": "has no tag",
            })
        elif status == "latest":
            findings.append({
                "line": line,
                "image": image,
                "reason": "uses the :latest tag",
            })
        elif status == "no-image":
            findings.append({
                "line": line,
                "image": image,
                "reason": "has no image",
            })
    return findings


def check_file(path):
    """Check one file. Returns (findings, error)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [], "not valid UTF-8"
    except OSError as exc:
        return [], str(exc)
    try:
        return check_text(text), None
    except Exception as exc:  # malformed text the scan rejects
        return [], "could not be checked: %s" % exc


def _is_dockerfile(path):
    name = Path(path).name.lower()
    return (name == "dockerfile"
            or name.startswith("dockerfile.")
            or name.endswith(".dockerfile"))


def collect_files(paths, recursive=True, exclude=None):
    """Expand CLI paths into a sorted list of Dockerfiles.

    A file given directly is always checked, whatever
    its name. A folder is walked for files named
    Dockerfile, Dockerfile.* or *.dockerfile only.
    .git folders are never walked, and directory
    links are never followed.
    """
    exclude = exclude or []
    found = []
    for raw in paths:
        path = Path(raw)
        if path.is_file():
            found.append(str(path))
        elif path.is_dir():
            for dirpath, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = [
                    d for d in dirs
                    if d != ".git"
                    and not any(fnmatch.fnmatch(d, pat) for pat in exclude)
                ]
                for name in files:
                    candidate = Path(dirpath) / name
                    if not _is_dockerfile(candidate):
                        continue
                    if any(
                        fnmatch.fnmatch(str(candidate), pat)
                        or fnmatch.fnmatch(name, pat)
                        for pat in exclude
                    ):
                        continue
                    found.append(str(candidate))
                if not recursive:
                    break
        else:
            raise FileNotFoundError("no such file or folder: %s" % raw)
    seen = set()
    unique = []
    for item in found:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return sorted(unique)


def format_finding(path, finding):
    """One human-readable line for one unpinned FROM."""
    if finding["image"]:
        return ("FAIL %s: FROM line %d '%s' %s"
                % (path, finding["line"], finding["image"],
                   finding["reason"]))
    return ("FAIL %s: FROM line %d %s"
            % (path, finding["line"], finding["reason"]))


def run(paths, recursive=True, exclude=None, as_json=False):
    """Check paths, print the report, return the exit code."""
    try:
        files = collect_files(paths, recursive=recursive, exclude=exclude)
    except FileNotFoundError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    if not files:
        print("error: no Dockerfiles found", file=sys.stderr)
        return 2
    results = []
    findings = 0
    files_with_findings = 0
    for path in files:
        bad, error = check_file(path)
        count = len(bad) + (1 if error else 0)
        if count:
            findings += count
            files_with_findings += 1
        results.append({"path": path, "findings": bad, "error": error})
    if as_json:
        print(json.dumps(
            {"files": results, "checked": len(files),
             "findings": findings},
            indent=2))
    else:
        for result in results:
            if result["error"]:
                print("FAIL %s: %s" % (result["path"], result["error"]))
            for finding in result["findings"]:
                print(format_finding(result["path"], finding))
        if findings:
            print("Checked %d file(s), %d FROM line(s) without a "
                  "pinned tag in %d file(s)."
                  % (len(files), findings, files_with_findings))
        else:
            print("OK — %d file(s) checked, every FROM pins a tag."
                  % len(files))
    return 1 if findings else 0


def run_stdin(as_json=False):
    """Check one Dockerfile read from standard input."""
    text = sys.stdin.read()
    bad = check_text(text)
    findings = len(bad)
    if as_json:
        print(json.dumps(
            {"files": [{"path": "<stdin>", "findings": bad,
                        "error": None}],
             "checked": 1, "findings": findings},
            indent=2))
    else:
        for finding in bad:
            print(format_finding("<stdin>", finding))
        if findings:
            print("Checked 1 file(s), %d FROM line(s) without a "
                  "pinned tag in 1 file(s)." % findings)
        else:
            print("OK — 1 file(s) checked, every FROM pins a tag.")
    return 1 if findings else 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="dockerfile_from_checker",
        description="Check Dockerfiles pin a specific image "
                    "tag, fail CI when one does not.")
    parser.add_argument("paths", nargs="*",
                        help="Dockerfiles or folders to walk")
    parser.add_argument("--no-recursive", action="store_true",
                        help="do not walk into subfolders")
    parser.add_argument("--exclude", action="append", default=[],
                        help="skip files or folders matching this pattern "
                             "(repeatable)")
    parser.add_argument("--json", action="store_true",
                        help="print the result as JSON")
    parser.add_argument("--stdin", action="store_true",
                        help="check one Dockerfile from standard input")
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + __version__)
    args = parser.parse_args(argv)
    if args.stdin:
        if args.paths:
            parser.error("--stdin takes no file or folder arguments")
        return run_stdin(as_json=args.json)
    if not args.paths:
        parser.error("give at least one Dockerfile or folder")
    return run(args.paths, recursive=not args.no_recursive,
               exclude=args.exclude, as_json=args.json)


if __name__ == "__main__":
    sys.exit(main())
