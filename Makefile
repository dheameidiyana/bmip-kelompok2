.DEFAULT_GOAL := help
SHELL := /bin/sh

COMPOSE_DEV := docker compose -f deploy/compose.base.yml -f deploy/compose.dev.yml

.PHONY: help dev-up dev-down reset doctor health bootstrap ingest-once transform quality e2e-smoke smoke test test-cov benchmark backup restore evidence

help:
	@echo "BMIP targets:"
	@echo "  dev-up       Start the dev profile"
	@echo "  dev-down     Stop the dev profile"
	@echo "  reset        Remove dev volumes and redeploy clean"
	@echo "  doctor       Show health of every service"
	@echo "  health       Alias for doctor"
	@echo "  bootstrap    Create MinIO buckets, Lakekeeper namespaces, Postgres schemas"
	@echo "  ingest-once  Run one harvest and one producer replay"
	@echo "  transform    Run dbt silver and gold"
	@echo "  quality      Run GX checkpoint and write dq_report.json"
	@echo "  e2e-smoke    Check bronze -> silver -> gold -> API -> dashboard"
	@echo "  smoke        Alias for e2e-smoke"
	@echo "  test         Run unit and contract tests"
	@echo "  test-cov     Run tests with coverage gate"
	@echo "  benchmark    Run benchmark matrix"
	@echo "  backup       Backup PostgreSQL"
	@echo "  restore      Restore PostgreSQL"
	@echo "  evidence     Collect evidence manifest and list missing files"

dev-up:
	@echo "[stub] dev-up: implemented in W1-A Tahap 1"
	@exit 1

dev-down:
	@echo "[stub] dev-down: implemented in W1-A Tahap 1"
	@exit 1

reset:
	@echo "[stub] reset: implemented in W1-A Tahap 1"
	@exit 1

doctor:
	@echo "[stub] doctor: implemented in W1-A Tahap 1"
	@exit 1

health: doctor

bootstrap:
	@echo "[stub] bootstrap: implemented in W1-A Tahap 1"
	@exit 1

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

test:
	@echo "[stub] test: venv and pytest wired in W1-A Tahap 2"
	@exit 1

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

evidence:
	@echo "[stub] evidence: implemented in W2-D"
	@exit 1
