.DEFAULT_GOAL := help
SHELL := /bin/sh

COMPOSE_DEV := docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml
COMPOSE_TWO := $(COMPOSE_DEV) -f deploy/compose.two-node.yml

ifeq ($(OS),Windows_NT)
PYTHON := .venv/Scripts/python.exe
PYTHON_BOOT ?= py -3.11
else
PYTHON := .venv/bin/python
PYTHON_BOOT ?= python3.11
endif

.PHONY: help setup secrets dev-up dev-down reset doctor health bootstrap compose-config two-node-config lint test ci ingest-once transform quality e2e-smoke smoke test-cov benchmark backup restore evidence

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
	@echo "  ingest-once  Run one harvest and one producer replay (W1-A Tahap 2)"
	@echo "  transform    Run dbt silver and gold (W1-B)"
	@echo "  quality      Run GX checkpoint (W1-C)"
	@echo "  e2e-smoke    End-to-end smoke test (W1-A Tahap 3)"
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

ingest-once:
	@echo "[stub] ingest-once: implemented in W1-A Tahap 2"
	@exit 1

transform:
	@echo "[stub] transform: implemented in W1-B"
	@exit 1

quality:
	@echo "[stub] quality: implemented in W1-C"
	@exit 1

e2e-smoke:
	@echo "[stub] e2e-smoke: implemented in W1-A Tahap 3 and expanded later"
	@exit 1

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
