#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

uv sync --locked --inexact  # keep optional extras such as embed installed
uv run ruff check
uv run ruff format --check
uv run pytest
echo "==> ALL GATES GREEN"
