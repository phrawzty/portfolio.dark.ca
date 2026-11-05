#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
# Pages provisions the Zola version selected by ZOLA_VERSION.
if ! command -v uv >/dev/null 2>&1; then
  python3 -m venv .portfolio-build-env
  .portfolio-build-env/bin/python -m pip install --quiet uv
  PORTFOLIO_UV=.portfolio-build-env/bin/uv
else
  PORTFOLIO_UV=uv
fi
"$PORTFOLIO_UV" run --frozen portfolio assets fetch --production
"$PORTFOLIO_UV" run --frozen portfolio build
