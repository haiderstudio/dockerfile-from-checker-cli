# Security Policy

This tool runs locally, collects no data, sends nothing anywhere, and needs no API key or secret. It only reads the Dockerfiles you point it at, and it never rewrites a file and never changes anything. It writes nothing except the report on standard output (and usage errors on standard error). It never fetches a URL: an image reference is checked for a tag, not pulled.

It only checks that a FROM line pins a tag. It never builds an image, never pulls an image, never runs a container, and never runs a Dockerfile instruction.

If you find a case where the tool rewrites a file, opens a URL, or reports a pass for a Dockerfile with an unpinned FROM line, please open an issue describing the exact commands and input. Do not include any real secret in the report.
