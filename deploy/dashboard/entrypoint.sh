#!/bin/sh
set -eu
PACKAGE="${BMIP_APP_PACKAGE:-bmip.dashboard}"
APP="$(python -c "import os, importlib; print(os.path.join(os.path.dirname(importlib.import_module('$PACKAGE').__file__), 'app.py'))")"
exec python -m streamlit run "$APP" \
    --server.port "${STREAMLIT_PORT:-8501}" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
