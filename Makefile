.DEFAULT_GOAL := help
SHELL := /bin/sh

COMPOSE_DEV := docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml
COMPOSE_TWO := $(COMPOSE_DEV) -f deploy/compose.two-node.yml
STREAM_GROUP ?= ohlcv-builder-replay
PREFECT_WORK_POOL ?= local-process

ifeq ($(OS),Windows_NT)
PYTHON := .venv/Scripts/python.exe
PYTHON_BOOT ?= python
else
PYTHON := .venv/bin/python
PYTHON_BOOT ?= python3.11
endif

.PHONY: help setup secrets dev-up dev-down reset doctor health bootstrap compose-config two-node-config lint test ci ingest-once ingest-live replay evidence-cp2 evidence-cp3 stream stream-once stream-lag evidence-w1b-cp1 evidence-w1b-cp2 transform prefect-deploy prefect-worker quality gold evidence-w1c e2e-smoke smoke test-cov benchmark backup restore evidence

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

$(PYTHON):
	$(PYTHON_BOOT) -m venv .venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

setup: $(PYTHON)

secrets: $(PYTHON)
	@$(PYTHON) scripts/gen_env.py

dev-up: secrets
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
	@$(COMPOSE_TWO) --profile two-node config --quiet
	@echo "two-node compose config valid"

lint: $(PYTHON)
	$(PYTHON) -m ruff check src scripts tests deploy
	@files=$$(find dbt -name '*.sql' 2>/dev/null); \
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

test-cov:
	@echo "[stub] test-cov: implemented in W2-D"
	@exit 1

benchmark:
	@echo "[stub] benchmark: implemented in W2-D"
	@exit 1

backup:
	@echo "[stub] backup: implemented in W2-D"
	@exit 1

restore:
	@echo "[stub] restore: implemented in W2-D"
	@exit 1

evidence: doctor
