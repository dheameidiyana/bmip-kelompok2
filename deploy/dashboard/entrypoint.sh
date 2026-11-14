#!/bin/sh
# Resolve the installed dashboard module instead of hardcoding a site-packages path.
set -eu
APP="$(python -c 'import os, bmip.dashboard; print(os.path.join(os.path.dirname(bmip.dashboard.__file__), "app.py"))')"
exec python -m streamlit run "$APP" \
    --server.port "${STREAMLIT_PORT:-8501}" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
