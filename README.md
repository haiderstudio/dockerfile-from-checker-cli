# dockerfile-from-checker-cli

Check every `FROM` in Dockerfiles pins a specific image tag — fail CI when one does not.

[![CI](https://github.com/haiderstudio/dockerfile-from-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/dockerfile-from-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`dockerfile_from_checker` reads each Dockerfile,
finds every `FROM` line, and reports each one
whose image has no tag or uses the `:latest` tag —
with the file and the line number. It exits 1 when
any `FROM` line is unpinned, so it can fail a CI
run. A file whose `FROM` lines all pin a tag
exits 0.

- An untagged or `:latest` base image makes builds
  unreproducible — the same Dockerfile builds a
  different image next month, and a breaking base
  change lands with no code change of your own.
  This names the exact line, and the fix is one
  word per line once found.
- A `FROM` line counts as pinned when its image
  carries a tag other than `latest`, or a digest
  (`image@sha256:...` pins an exact image, so a
  digest alone counts as pinned too). The special
  base image `scratch` has no tag by design and is
  never flagged. A tag that comes from a build
  argument (`FROM $BASE` or `FROM ${BASE:-alpine}`)
  is not flagged either — the tag is pinned
  elsewhere, in the `ARG`, and this tool cannot see
  it from the `FROM` line alone.
- A registry port is not a tag: in
  `registry.example.com:5000/team/app` the `:5000`
  belongs to the registry, and the image is
  untagged, so it is reported. In
  `registry.example.com:5000/team/app:2.0` the tag
  is `2.0`, so it passes.
- A file given directly on the command line is always
  checked, whatever its name. A folder is walked for
  files named `Dockerfile`, `Dockerfile.*` or
  `*.dockerfile` only, recursively by default
  (`--no-recursive` stops at the top level). `.git`
  folders are never walked, and directory links are
  never followed.
- `--json` prints the result as JSON, and `--stdin`
  checks one Dockerfile read from standard input.
- `FROM` lines are matched without regard to case,
  as Dockerfiles allow — `from python` is checked
  exactly like `FROM python`. A `FROM` line split
  across lines with a backslash is joined and
  reported on the line the `FROM` starts on.
  `FROM` written in a comment is not a `FROM` line.

## Who it is for

Every project that ships a Dockerfile — one
untagged base image and next month's build is a
different image from this month's, with nothing in
your own code having changed. This is the gate
that stops it at the pull request.

## What it does NOT do

- It does not lint Dockerfiles broadly. That is
  Hadolint — a full Dockerfile linter with hundreds
  of rules. This tool is one check only, as a
  zero-install standard-library CLI: does every
  `FROM` pin a tag.
- It does not check whether a pinned tag is the
  newest version, or whether the image exists on a
  registry — reaching the network is a different job.
- It does not check `ARG` values, so it cannot tell
  whether an argument-supplied tag is itself pinned.
- It never rewrites a file, and it never touches the
  network.

## How this differs

- A fresh search of GitHub on Nov 16, 2026 found 0
  results for `"dockerfile-from-checker-cli"` and 0
  results for `dockerfile from checker` — a
  completely empty field.
- Hadolint owns Dockerfile linting broadly; this is
  one check only, the same broad-vs-narrow pattern
  as repo #100 (shell-quote) against ShellCheck.

## Install

```sh
git clone https://github.com/haiderstudio/dockerfile-from-checker-cli.git
cd dockerfile-from-checker-cli
```

There is nothing else to install: Python 3.10 or newer,
standard library only, no dependencies.

## Usage

Check one Dockerfile:

```sh
python3 src/dockerfile_from_checker.py Dockerfile
```

A file whose `FROM` lines all pin a tag passes:

```sh
$ python3 src/dockerfile_from_checker.py examples/clean.Dockerfile
OK — 1 file(s) checked, every FROM pins a tag.
```

A file with unpinned base images fails, with the
file and line for each one:

```sh
$ python3 src/dockerfile_from_checker.py examples/flagged.Dockerfile
FAIL examples/flagged.Dockerfile: FROM line 2 'python' has no tag
FAIL examples/flagged.Dockerfile: FROM line 3 'node:latest' uses the :latest tag
FAIL examples/flagged.Dockerfile: FROM line 4 'alpine' has no tag
FAIL examples/flagged.Dockerfile: FROM line 5 'ubuntu:latest' uses the :latest tag
Checked 1 file(s), 4 FROM line(s) without a pinned tag in 1 file(s).
```

Check a whole folder (`Dockerfile`, `Dockerfile.*`,
`*.dockerfile` only):

```sh
$ python3 src/dockerfile_from_checker.py examples/
FAIL examples/flagged.Dockerfile: FROM line 2 'python' has no tag
FAIL examples/flagged.Dockerfile: FROM line 3 'node:latest' uses the :latest tag
FAIL examples/flagged.Dockerfile: FROM line 4 'alpine' has no tag
FAIL examples/flagged.Dockerfile: FROM line 5 'ubuntu:latest' uses the :latest tag
Checked 3 file(s), 4 FROM line(s) without a pinned tag in 1 file(s).
```

Check one Dockerfile from standard input:

```sh
$ printf 'FROM node:latest\n' | python3 src/dockerfile_from_checker.py --stdin
FAIL <stdin>: FROM line 1 'node:latest' uses the :latest tag
Checked 1 file(s), 1 FROM line(s) without a pinned tag in 1 file(s).
```

Machine-readable output:

```sh
$ python3 src/dockerfile_from_checker.py --json examples/flagged.Dockerfile
{
  "files": [
    {
      "path": "examples/flagged.Dockerfile",
      "findings": [
        {
          "line": 2,
          "image": "python",
          "reason": "has no tag"
        },
        {
          "line": 3,
          "image": "node:latest",
          "reason": "uses the :latest tag"
        },
        {
          "line": 4,
          "image": "alpine",
          "reason": "has no tag"
        },
        {
          "line": 5,
          "image": "ubuntu:latest",
          "reason": "uses the :latest tag"
        }
      ],
      "error": null
    }
  ],
  "checked": 1,
  "findings": 4
}
```

Exit codes: 0 when every `FROM` pins a tag, 1
when any `FROM` is unpinned or a file cannot be
read, 2 for a usage error (a missing path, a bad
flag, or no Dockerfiles found).

## Examples

A multi-stage file with pinned tags, a digest, a
`scratch` stage and an argument-supplied tag all
pass — `examples/clean.Dockerfile` holds them:

```sh
$ python3 src/dockerfile_from_checker.py examples/clean.Dockerfile
OK — 1 file(s) checked, every FROM pins a tag.
```

Lowercase `from`, a `--platform` flag, a registry
port, a digest-only image, an argument tag, a split
`FROM` line and a `FROM` in a comment are all
handled — `examples/edge.Dockerfile` has all of
them, and it passes:

```sh
$ python3 src/dockerfile_from_checker.py examples/edge.Dockerfile
OK — 1 file(s) checked, every FROM pins a tag.
```

A registry port is not a tag — the `:5000` belongs
to the registry, so the image is untagged:

```sh
$ printf 'FROM registry.example.com:5000/team/app\n' | python3 src/dockerfile_from_checker.py --stdin
FAIL <stdin>: FROM line 1 'registry.example.com:5000/team/app' has no tag
Checked 1 file(s), 1 FROM line(s) without a pinned tag in 1 file(s).
```

Run every bundled example at once with `sh
examples/run-example.sh` — the output is saved in
[examples/sample-output.md](examples/sample-output.md).

## How it is tested

```sh
python3 tests/test_dockerfile_from_checker.py
```

The tests cover `FROM` detection (a pinned tag
passes, an untagged `FROM` fails, `:latest` fails,
`:latest` with a stage fails, an untagged
multi-stage `FROM` fails, several `FROM` lines in
document order, lowercase and mixed-case `FROM`,
leading whitespace, a `--platform` flag skipped
and an untagged image behind it still failing, a
registry port not counting as a tag, a registry
port with a real tag passing, a digest-only image
passing, a tag plus a digest passing, `:latest`
with a digest passing, `scratch` passing with and
without a stage, an argument image, a braced
argument, an argument with a default, an argument
tag, a `FROM` with no image failing, a `FROM`
split across lines, a file with no `FROM` passing,
an empty document passing, `RUN` and `COPY` lines
ignored), skipping (a `FROM` in a comment, a
`FROM` in a comment after a real one, an indented
comment, the word `FROM` inside a `RUN` line), the
CLI (exit 0/1/2, folder walking for `Dockerfile`,
`Dockerfile.dev` and `*.dockerfile`, nested
folders, `--no-recursive`, `--exclude`, `.git`
skipped, a direct file checked whatever its name,
duplicate paths checked once, `--json` output,
`--stdin`, bad flags, missing paths, empty folders,
`--version`, a non-UTF-8 file reported, input files
left unchanged, the tool run from another folder
and under a changed HOME), the bundled examples
(sample output compared byte-for-byte against a
fresh run, and the README-quoted outputs checked
against it), and hygiene checks (no placeholder
text, no absolute paths, no real secrets outside
the tests and examples, stdlib imports only, no
network use in the source, `.env` first in
`.gitignore`, CI file runs the test file, README
names Hadolint).

## Contributing

Small, focused improvements are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The
idea of pinning base-image tags is not new, and
Hadolint already lints Dockerfiles broadly — but no
existing tool does this one job, checking that
every `FROM` in local Dockerfiles pins a specific
tag, as a tested command-line gate with a CI exit
code, as the search above shows — and every line of
code here is original, built on nothing but
Python's standard library.
