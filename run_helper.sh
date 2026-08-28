#!/bin/sh
set -eu

plugin_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)

# The helper reports bounded, user-safe JSON on stdout. Discard dependency and
# library diagnostics at the process boundary so Quickshell never accumulates
# an unbounded stderr stream in its long-lived process.
exec uv run --locked "$plugin_dir/blink_helper.py" "$@" 2>/dev/null
