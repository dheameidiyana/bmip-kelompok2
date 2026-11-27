.DEFAULT_GOAL := help
SHELL := /bin/sh

COMPOSE_DEV := docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml --profile n1 --profile n2 --profile n3 --profile n4
COMPOSE_TWO := docker compose --env-file .env --env-file deploy/env/node1.env -f deploy/compose.base.yml -f deploy/compose.node1.yml -f deploy/compose.node2.yml --profile n1 --profile n2 --profile promtail
COMPOSE_NODE1 := docker compose --env-file .env --env-file deploy/env/node1.env -f deploy/compose.base.yml -f deploy/compose.node1.yml
COMPOSE_NODE2 := docker compose --env-file .env --env-file deploy/env/node2.env -f deploy/compose.base.yml -f deploy/compose.node2.yml
COMPOSE_NODE3 := docker compose --env-file .env --env-file deploy/env/node3.env -f deploy/compose.base.yml -f deploy/compose.node3.yml
COMPOSE_NODE4 := docker compose --env-file .env --env-file deploy/env/node4.env -f deploy/compose.base.yml -f deploy/compose.node4.yml
COMPOSE_CLUSTER := docker compose --env-file .env --env-file deploy/env/node1.env -f deploy/compose.base.yml
STREAM_GROUP ?= ohlcv-builder-replay
PREFECT_WORK_POOL ?= local-process
C3B_AS_OF ?= 2026-11-17T00:00:00Z

ifeq ($(OS),Windows_NT)
PYTHON := .venv/Scripts/python.exe
PYTHON_BOOT ?= python
else
PYTHON := .venv/bin/python
PYTHON_BOOT ?= python3.11
endif

.PHONY: help setup secrets dev-up dev-down reset doctor health bootstrap compose-config two-node-config node1-config node2-config node3-config node4-config three-node-config four-node-config node1-up node2-up node3-up node4-up node1-down node2-down node3-down node4-down two-node-local lint test ci ingest-once ingest-live replay evidence-cp2 evidence-cp3 stream stream-once stream-lag evidence-w1b-cp1 evidence-w1b-cp2 transform prefect-deploy prefect-worker quality gold evidence-w1c e2e-smoke smoke test-cov benchmark backup restore evidence serving serving-counts api-dev dashboard-dev evidence-api evidence-api-faults e2e-m1 reconcile openapi obs-up obs-down evidence-w2b drill-w2b reconcile-w2b metrics-check certs users governance governance-up catalog-dev evidence-w2c trace-w2c scan-w2c evidence-check c3a-roles c3a-services c3a-up c3a-chaos c3a-scan c3a-evidence c3a-circuit c3b-feast-build c3b-feast-apply c3b-parity c3b-drift c3b-per-symbol c3b-promotion c3b-feature-age c3b-evidence docs c3c-nodes c3c-acl c3c-loki c3c-migrate c3c-governance c3c-catalog c3c-lifecycle c3c-docs c3c-evidence

help:
	@echo "BMIP targets:"
	@echo "  setup        Create .venv and install dependencies"
	@echo "  secrets      Generate .env with random local secrets (once)"
	@echo "  dev-up       Start the dev profile and bootstrap storage"
	@echo "  dev-down     Stop the dev profile"
	@echo "  reset        Remove dev volumes and redeploy clean"
	@echo "  doctor       Check every service and write CP1 evidence"
	@echo "  health       Alias for doctor"
	@echo "  bootstrap    Create MinIO buckets/users and Lakekeeper namespaces"
	@echo "  compose-config  Validate dev compose and write evidence"
	@echo "  two-node-config Validate the two-node overlay"
	@echo "  node1-up     Start N1 (edge, storage, query)"
	@echo "  node2-up     Start N2 (processing, orchestration, ML)"
	@echo "  node3-up     Start N3 (governance, UI, docs)"
	@echo "  node4-up     Start N4 (observability, security)"
	@echo "  three-node-config / four-node-config  Validate a composed cluster"
	@echo "  two-node-local  Run N1+N2 on one host for the C3-C live check"
	@echo "  c3c-acl      Validate the final Tailscale ACL matrix (C3-C)"
	@echo "  c3c-loki     Write Loki/Promtail evidence (C3-C)"
	@echo "  c3c-migrate  Apply the C3-C catalog search/governance migration"
	@echo "  c3c-catalog  Write catalog view and search evidence (C3-C)"
	@echo "  c3c-governance  Run the governance workflow and metadata test"
	@echo "  c3c-lifecycle   Compact, expire, and enforce retention (C3-C)"
	@echo "  c3c-docs     Build and host dbt/GX docs (C3-C)"
	@echo "  lint         Run ruff and sqlfluff"
	@echo "  test         Run unit and contract tests"
	@echo "  ci           Local mirror of the CI gate"
	@echo "  ingest-once  Replay one trade batch and one post batch, then write CP2 evidence"
	@echo "  ingest-live  Read a few trades and posts from the live sources"
	@echo "  replay       Run the same replay without writing evidence"
	@echo "  evidence-cp2 Refresh CP2 evidence from existing bronze and ledger rows"
	@echo "  evidence-cp3 Replay twice and write T-26 idempotence evidence"
	@echo "  stream       Run the market stream processor until stopped"
	@echo "  stream-once  Drain market.trades and exit (W1-B)"
	@echo "  stream-lag   Print committed offsets and consumer lag"
	@echo "  evidence-w1b-cp1 Write lag and restart evidence for W1-B"
	@echo "  evidence-w1b-cp2 Write T04/T06/T07/T08 evidence for W1-B"
	@echo "  transform    Run dbt silver and gold (W1-B)"
	@echo "  prefect-deploy  Create work pool and deploy Prefect flows"
	@echo "  prefect-worker  Start the local Prefect worker (foreground)"
	@echo "  quality      Run GX checkpoint and write evidence/dq/dq_report.json (W1-C)"
	@echo "  gold         Build gold marts, enforce gates, publish to Iceberg (W1-C)"
	@echo "  evidence-w1c Write T03/T09/T10/T11/T12/T31/T32/T33 evidence (W1-C)"
	@echo "  e2e-smoke    W1-A smoke: health + replay + bronze + ledger"
	@echo "  evidence     Collect the health evidence file"
	@echo "  evidence-check Verify manifest, links, and tracked evidence (CI)"
	@echo "  c3a-roles    Create the read-only API replica role (C3-A)"
	@echo "  c3a-services Render the Traefik API replica list (C3-A)"
	@echo "  c3a-up       Recreate api and api-2 (C3-A)"
	@echo "  c3a-chaos    Start Toxiproxy for the circuit-breaker drill"
	@echo "  c3a-scan     Trivy, port, rate-limit, TLS, and audit evidence"
	@echo "  c3a-evidence T-16/T-17 replica evidence"
	@echo "  c3a-circuit  T-18 circuit-breaker evidence"
	@echo "  c3b-feast-build Build Feast offline sources"
	@echo "  c3b-feast-apply Apply and materialize Feast"
	@echo "  c3b-parity   Verify Feast point-in-time parity"
	@echo "  c3b-drift    Persist drift metrics and trigger status"
	@echo "  c3b-per-symbol Compare pooled vs per-symbol models"
	@echo "  serving      Load gold into the serving schema (W1-D)"
	@echo "  serving-counts  Print serving table counts"
	@echo "  api-dev      Run the Query API on the host (uvicorn, port 8000)"
	@echo "  dashboard-dev   Run Streamlit on the host (port 8501)"
	@echo "  evidence-api    CP1/CP2 API evidence: smoke, routes, T-13, T-34, T-36"
	@echo "  evidence-api-faults  T-14/T-15/T-37/Idempotence (stops MinIO briefly)"
	@echo "  e2e-m1       M1 gate: bronze -> silver -> gold -> serving -> API -> dashboard"
	@echo "  reconcile    T-37 draft: API vs serving SQL vs Iceberg"
	@echo "  openapi      Write contracts/openapi.json from the running API"
	@echo "  obs-up       Start Prometheus, Alertmanager, Grafana, exporters (W2-B)"
	@echo "  obs-down     Stop the observability services"
	@echo "  metrics-check  Check scrape targets and the nine pipeline metrics"
	@echo "  evidence-w2b CP1/CP2 evidence: targets, dashboards, rules, log sample"
	@echo "  drill-w2b    T-39: three alert classes fire -> deliver -> resolve"
	@echo "  reconcile-w2b  T-37 final: dashboard vs API vs SQL for 24h and 7d"
	@echo "  certs        Create the local CA and wildcard Traefik certificate"
	@echo "  users        Write Traefik users.htpasswd from BMIP_UI_USERS"
	@echo "  governance   Apply ops schema, seed the registry, and seed RBAC keys"
	@echo "  governance-up  Start postgres-gov, Marquez API, and Marquez web"
	@echo "  catalog-dev  Run the catalog portal on port 8502"
	@echo "  evidence-w2c CP1/CP2 lineage and catalog evidence"
	@echo "  trace-w2c    T-30 trace one payload hash through every layer"
	@echo "  scan-w2c     PII, port, gitleaks, TLS, RBAC, and ACL evidence"
	@echo "  backup       Back up PostgreSQL databases and write a recovery manifest"
	@echo "  restore      Run the T-19 restore drill from the latest manifest"

$(PYTHON):
	$(PYTHON_BOOT) -m venv .venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev,ml,dashboard]"

setup: $(PYTHON)

secrets: $(PYTHON)
	@$(PYTHON) scripts/gen_env.py --merge

certs: $(PYTHON)
	@$(PYTHON) scripts/gen_certs.py

users: $(PYTHON)
	@$(PYTHON) scripts/gen_htpasswd.py

governance: $(PYTHON)
	@$(PYTHON) scripts/w2c_migrate.py
	@$(PYTHON) scripts/w2c_seed_registry.py
	@$(PYTHON) scripts/w2c_seed_keys.py
	@$(PYTHON) scripts/c3c_migrate.py

governance-up: certs users
	$(COMPOSE_DEV) --profile governance up -d postgres-gov marquez marquez-web

catalog-dev: $(PYTHON)
	$(PYTHON) -m streamlit run src/bmip/catalog/app.py --server.port 8502

evidence-w2c: $(PYTHON)
	$(PYTHON) scripts/w2c_evidence.py

trace-w2c: $(PYTHON)
	$(PYTHON) scripts/w2c_trace.py

scan-w2c: $(PYTHON)
	$(PYTHON) scripts/w2c_scan.py

dev-up: secrets certs users
	$(COMPOSE_DEV) up -d --build
	$(PYTHON) scripts/doctor.py --wait --services-only --timeout 300
	$(MAKE) bootstrap
	$(PYTHON) scripts/doctor.py --evidence

dev-down:
	$(COMPOSE_DEV) down --remove-orphans

reset:
	$(COMPOSE_DEV) down -v --remove-orphans
	$(MAKE) dev-up

doctor: $(PYTHON)
	@$(PYTHON) scripts/doctor.py --evidence

health: doctor

bootstrap:
	$(COMPOSE_DEV) --profile bootstrap run --rm minio-init
	$(COMPOSE_DEV) --profile bootstrap run --rm lakekeeper-bootstrap

compose-config: secrets
	@mkdir -p evidence/deploy; \
	ts=$$(date -u +%Y%m%dT%H%M); sha=$$(git rev-parse --short HEAD 2>/dev/null || echo nogit); \
	$(COMPOSE_DEV) config --no-interpolate > "evidence/deploy/compose-config_$${ts}_$${sha}.yml"; \
	echo "dev compose config valid"

two-node-config: secrets
	@$(COMPOSE_TWO) config --quiet
	@echo "two-node compose config valid"

node1-config: secrets
	@$(COMPOSE_NODE1) --profile n1 --profile promtail config --quiet
	@echo "node1 compose config valid"

node2-config: secrets
	@$(COMPOSE_NODE2) --profile n2 --profile promtail config --quiet
	@echo "node2 compose config valid"

node3-config: secrets
	@$(COMPOSE_NODE3) --profile n3 --profile governance --profile docs --profile promtail config --quiet
	@echo "node3 compose config valid"

node4-config: secrets
	@$(COMPOSE_NODE4) --profile n4 --profile loki --profile promtail config --quiet
	@echo "node4 compose config valid"

three-node-config: secrets
	@BMIP_BIND_ADDRESS=127.0.0.1 BMIP_EDGE_BIND_ADDRESS=127.0.0.1 \
		$(COMPOSE_CLUSTER) -f deploy/compose.node1.yml -f deploy/compose.node2.yml \
		-f deploy/compose.node3.yml --profile n1 --profile n2 --profile n3 \
		--profile governance --profile docs --profile promtail config --quiet
	@echo "three-node compose config valid"

four-node-config: secrets
	@BMIP_BIND_ADDRESS=127.0.0.1 BMIP_EDGE_BIND_ADDRESS=127.0.0.1 \
		$(COMPOSE_CLUSTER) -f deploy/compose.node1.yml -f deploy/compose.node2.yml \
		-f deploy/compose.node3.yml -f deploy/compose.node4.yml \
		--profile n1 --profile n2 --profile n3 --profile n4 \
		--profile governance --profile docs --profile loki --profile promtail config --quiet
	@echo "four-node compose config valid"

node1-up: node1-config
	$(COMPOSE_NODE1) --profile n1 --profile promtail --profile bootstrap up -d

node2-up: node2-config
	$(COMPOSE_NODE2) --profile n2 --profile promtail up -d

node3-up: node3-config
	$(COMPOSE_NODE3) --profile n3 --profile governance --profile docs --profile promtail up -d

node4-up: node4-config
	$(COMPOSE_NODE4) --profile n4 --profile loki --profile promtail up -d

node1-down:
	$(COMPOSE_NODE1) --profile n1 --profile promtail --profile bootstrap down --remove-orphans

node2-down:
	$(COMPOSE_NODE2) --profile n2 --profile promtail down --remove-orphans

node3-down:
	$(COMPOSE_NODE3) --profile n3 --profile governance --profile docs --profile promtail down --remove-orphans

node4-down:
	$(COMPOSE_NODE4) --profile n4 --profile loki --profile promtail down --remove-orphans

# Live C3-C check: N1+N2 on one host. This proves the role split and the
# cross-node env wiring, not a real two-laptop network; the handoff says so.
two-node-local: secrets
	BMIP_BIND_ADDRESS=127.0.0.1 BMIP_EDGE_BIND_ADDRESS=127.0.0.1 \
	BMIP_N1_HOST=127.0.0.1 BMIP_N2_HOST=127.0.0.1 \
	BMIP_N3_HOST=127.0.0.1 BMIP_N4_HOST=127.0.0.1 \
	BMIP_API_2_HOST_PORT=8001 BMIP_PG_ML_PORT=5434 \
		$(COMPOSE_TWO) --profile bootstrap up -d

two-node-local-down:
	BMIP_BIND_ADDRESS=127.0.0.1 BMIP_EDGE_BIND_ADDRESS=127.0.0.1 \
	BMIP_N1_HOST=127.0.0.1 BMIP_N2_HOST=127.0.0.1 \
	BMIP_N3_HOST=127.0.0.1 BMIP_N4_HOST=127.0.0.1 \
	BMIP_API_2_HOST_PORT=8001 BMIP_PG_ML_PORT=5434 \
		$(COMPOSE_TWO) --profile bootstrap down --remove-orphans

lint: $(PYTHON)
	$(PYTHON) -m ruff check src scripts tests deploy
	@files=$$(find dbt -name '*.sql' -not -path 'dbt/target/*' 2>/dev/null); \
	if [ -n "$$files" ]; then \
		$(PYTHON) -m sqlfluff lint $$files --dialect duckdb; \
	else \
		echo "sqlfluff: no SQL files yet"; \
	fi

test: $(PYTHON)
	$(PYTHON) -m pytest

ci: compose-config two-node-config lint test

ingest-once: $(PYTHON)
	$(PYTHON) -m bmip.ingestion.cli market --replay tests/fixtures/binance_agg_trades.jsonl
	$(PYTHON) -m bmip.ingestion.cli social --replay tests/fixtures/bluesky_posts.json
	$(PYTHON) scripts/cp2_evidence.py

ingest-live: $(PYTHON)
	$(PYTHON) -m bmip.ingestion.cli market --live --max-records 5
	$(PYTHON) -m bmip.ingestion.cli social --live --max-pages 1

replay: $(PYTHON)
	$(PYTHON) -m bmip.ingestion.cli market --replay tests/fixtures/binance_agg_trades.jsonl
	$(PYTHON) -m bmip.ingestion.cli social --replay tests/fixtures/bluesky_posts.json

evidence-cp2: $(PYTHON)
	$(PYTHON) scripts/cp2_evidence.py

evidence-cp3: $(PYTHON)
	$(PYTHON) scripts/cp3_evidence.py

stream: $(PYTHON)
	$(PYTHON) -m bmip.transform.cli stream --follow

stream-once: $(PYTHON)
	$(PYTHON) -m bmip.transform.cli stream --once --group $(STREAM_GROUP)

stream-lag: $(PYTHON)
	$(PYTHON) -m bmip.transform.cli lag --group $(STREAM_GROUP)

evidence-w1b-cp1: $(PYTHON)
	$(PYTHON) scripts/stream_evidence_cp1.py

evidence-w1b-cp2: $(PYTHON)
	$(PYTHON) scripts/cp2_market_evidence.py

transform: $(PYTHON)
	$(PYTHON) scripts/run_dbt.py

prefect-deploy: $(PYTHON)
	$(PYTHON) scripts/prefect_bootstrap.py

prefect-worker: $(PYTHON)
	$(PYTHON) -m prefect worker start -p $(PREFECT_WORK_POOL)

quality: $(PYTHON)
	$(PYTHON) scripts/quality.py

gold: $(PYTHON)
	$(PYTHON) scripts/build_gold.py

evidence-w1c: $(PYTHON)
	$(PYTHON) scripts/w1c_evidence.py

e2e-smoke: $(PYTHON)
	$(PYTHON) scripts/e2e_smoke.py

smoke: e2e-smoke

serving: $(PYTHON)
	$(PYTHON) scripts/serve_load.py

serving-counts: $(PYTHON)
	$(PYTHON) scripts/serve_load.py --counts

api-dev: $(PYTHON)
	$(PYTHON) -m uvicorn bmip.api.main:create_app --factory --host 0.0.0.0 --port 8000

dashboard-dev: $(PYTHON)
	$(PYTHON) -m streamlit run src/bmip/dashboard/app.py --server.port 8501 --server.headless true

evidence-api: $(PYTHON)
	$(PYTHON) scripts/api_evidence.py --steps smoke,routes,auth,invalid,predict

evidence-api-faults: $(PYTHON)
	$(PYTHON) scripts/api_evidence.py --steps pagination,stale,idempotence,reconcile --with-faults

e2e-m1: $(PYTHON)
	$(PYTHON) scripts/m1_smoke.py

reconcile: $(PYTHON)
	$(PYTHON) scripts/reconciliation.py

openapi: $(PYTHON)
	$(PYTHON) scripts/api_evidence.py --steps routes

test-cov: $(PYTHON)
	@mkdir -p evidence/tests
	$(PYTHON) -m pytest --cov=bmip --cov-report=term --cov-report=json:evidence/tests/coverage.json --cov-fail-under=40

benchmark: $(PYTHON)
	$(PYTHON) scripts/w2d_benchmark.py

backup: $(PYTHON)
	$(PYTHON) scripts/w2d_backup.py

restore: $(PYTHON)
	$(PYTHON) scripts/w2d_restore.py

evidence: doctor
	$(PYTHON) scripts/w2d_evidence_check.py

evidence-check: $(PYTHON)
	$(PYTHON) scripts/w2d_evidence_check.py --check

c3a-roles: $(PYTHON)
	$(PYTHON) scripts/c3a_roles.py

c3a-services: $(PYTHON)
	$(PYTHON) scripts/c3a_render_services.py

c3a-up: c3a-services
	$(COMPOSE_DEV) up -d api api-2 traefik

c3a-chaos:
	docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml -f deploy/compose.chaos.yml --profile chaos up -d toxiproxy

c3a-scan: $(PYTHON)
	$(PYTHON) scripts/c3a_scan.py

c3a-evidence: $(PYTHON)
	$(PYTHON) scripts/c3a_evidence.py --steps lb,failover,summary

c3a-circuit: $(PYTHON)
	$(PYTHON) scripts/c3a_circuit.py

c3b-feast-build: $(PYTHON)
	$(PYTHON) scripts/c3b_feast_build.py

c3b-feast-apply: $(PYTHON)
	$(PYTHON) scripts/c3b_feast.py

c3b-parity: $(PYTHON)
	$(PYTHON) scripts/c3b_parity.py

c3b-drift: $(PYTHON)
	$(PYTHON) scripts/c3b_drift.py

c3b-per-symbol: $(PYTHON)
	$(PYTHON) scripts/c3b_per_symbol.py

c3b-promotion: $(PYTHON)
	$(PYTHON) scripts/c3b_promotion_check.py

c3b-feature-age: $(PYTHON)
	$(PYTHON) scripts/c3b_feature_age.py --as-of $(C3B_AS_OF)

c3b-evidence: c3b-feast-build c3b-feast-apply c3b-parity c3b-drift c3b-per-symbol c3b-promotion c3b-feature-age
	@echo "C3-B evidence refreshed"

OBS_SERVICES := prometheus alertmanager pushgateway postgres-exporter cadvisor notify grafana

obs-up:
	$(COMPOSE_DEV) up -d $(OBS_SERVICES)

obs-down:
	$(COMPOSE_DEV) stop $(OBS_SERVICES)

metrics-check: $(PYTHON)
	$(PYTHON) scripts/w2b_metrics_check.py

evidence-w2b: $(PYTHON)
	$(PYTHON) scripts/w2b_evidence.py --steps cp1,cp2,logerror

drill-w2b: $(PYTHON)
	$(PYTHON) scripts/w2b_evidence.py --steps drill

reconcile-w2b: $(PYTHON)
	$(PYTHON) scripts/w2b_evidence.py --steps reconcile

c3c-nodes: $(PYTHON)
	$(PYTHON) scripts/c3c_nodes.py

c3c-nodes-live: $(PYTHON)
	$(PYTHON) scripts/c3c_nodes.py --live

c3c-acl: $(PYTHON)
	$(PYTHON) scripts/c3c_acl.py

c3c-loki: $(PYTHON)
	$(PYTHON) scripts/c3c_loki.py

c3c-migrate: $(PYTHON)
	$(PYTHON) scripts/c3c_migrate.py

c3c-governance: $(PYTHON)
	$(PYTHON) scripts/c3c_governance.py workflow
	$(PYTHON) scripts/c3c_governance.py metadata-test

c3c-catalog: $(PYTHON)
	$(PYTHON) scripts/c3c_catalog.py

c3c-lifecycle: $(PYTHON)
	$(PYTHON) scripts/c3c_lifecycle.py

docs: c3c-docs

c3c-docs: $(PYTHON)
	$(PYTHON) scripts/c3c_docs.py --serve

c3c-evidence: c3c-nodes c3c-acl c3c-loki c3c-migrate c3c-governance c3c-catalog c3c-lifecycle c3c-docs
	@echo "C3-C evidence refreshed"
