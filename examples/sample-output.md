== examples/clean.Dockerfile ==
OK — 1 file(s) checked, every FROM pins a tag.

== examples/flagged.Dockerfile ==
FAIL examples/flagged.Dockerfile: FROM line 2 'python' has no tag
FAIL examples/flagged.Dockerfile: FROM line 3 'node:latest' uses the :latest tag
FAIL examples/flagged.Dockerfile: FROM line 4 'alpine' has no tag
FAIL examples/flagged.Dockerfile: FROM line 5 'ubuntu:latest' uses the :latest tag
Checked 1 file(s), 4 FROM line(s) without a pinned tag in 1 file(s).

== examples/edge.Dockerfile ==
OK — 1 file(s) checked, every FROM pins a tag.

== examples/ : the whole folder ==
FAIL examples/flagged.Dockerfile: FROM line 2 'python' has no tag
FAIL examples/flagged.Dockerfile: FROM line 3 'node:latest' uses the :latest tag
FAIL examples/flagged.Dockerfile: FROM line 4 'alpine' has no tag
FAIL examples/flagged.Dockerfile: FROM line 5 'ubuntu:latest' uses the :latest tag
Checked 3 file(s), 4 FROM line(s) without a pinned tag in 1 file(s).
