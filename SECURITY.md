# Security policy

## Reporting a vulnerability

Please do not open a public issue for vulnerabilities involving credentials,
authentication tokens, local file permissions, or exposure of camera media.

Use GitHub's **Security → Report a vulnerability** flow for this repository.
Include the affected version, reproduction steps, and any relevant logs after
removing account identifiers and tokens.

## Sensitive files

The plugin stores runtime authentication under `~/.local/state/omarchy-blink/`.
Never attach that directory, `credentials.json`, or unredacted debug traffic to
an issue or pull request.
