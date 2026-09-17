#!/bin/sh
set -eu
export PYTHONPATH="$(pwd)"

pip install --no-cache-dir ruff==0.16.3 pytest==8.4.2 pytest-asyncio==1.4.0 >/dev/null
ruff check app tests
pytest -q -p no:cacheprovider
