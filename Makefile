SHELL := /usr/bin/env bash
PYTHON ?= python3
PIP ?= $(PYTHON) -m pip

.PHONY: help bootstrap install-dev pre-commit-install up down monitoring-up monitoring-down reset health transform validate apply verify test coverage lint typecheck format shell-lint yaml-lint docs-lint docker-validate manifest-validate security ci

help:
	@printf "%s\n" \
	  "bootstrap         Create .env and local artifact directories" \
	  "install-dev       Install Python tooling and the parser package" \
	  "up                Start PostgreSQL and Mattermost" \
	  "down              Stop PostgreSQL and Mattermost" \
	  "monitoring-up     Start Prometheus, Grafana, Loki, and exporters" \
	  "monitoring-down   Stop monitoring services" \
	  "reset             Remove local state and generated artifacts" \
	  "health            Run platform health checks" \
	  "transform         Build a Mattermost JSONL import payload" \
	  "validate          Validate the generated import payload" \
	  "apply             Apply the import payload to Mattermost" \
	  "verify            Query PostgreSQL for migration verification data" \
	  "test              Run unit, integration, and repository contract tests" \
	  "coverage          Run tests with coverage reporting" \
	  "typecheck         Run strict mypy checks" \
	  "security          Run dependency security checks" \
	  "lint              Run Python, shell, markdown, YAML, and compose validation" \
	  "format            Auto-format Python and shell sources"

bootstrap:
	bash ./scripts/bootstrap/bootstrap-workspace.sh

install-dev:
	$(PIP) install -r requirements-dev.txt
	$(PIP) install -e apps/parser

pre-commit-install:
	$(PYTHON) -m pre_commit install

up:
	bash ./scripts/bootstrap/start-local-platform.sh

down:
	bash ./scripts/bootstrap/stop-local-platform.sh

monitoring-up:
	bash ./scripts/monitoring/start-monitoring.sh

monitoring-down:
	bash ./scripts/monitoring/stop-monitoring.sh

reset:
	bash ./scripts/cleanup/reset-local-state.sh --force

health:
	bash ./scripts/verification/check-platform-health.sh

transform:
	bash ./scripts/migration/transform-export.sh

validate:
	bash ./scripts/migration/validate-import.sh

apply:
	bash ./scripts/migration/apply-import.sh

verify:
	bash ./scripts/verification/verify-migration-state.sh

test:
	PYTHONPATH=apps/parser/src $(PYTHON) -m pytest --no-cov

coverage:
	PYTHONPATH=apps/parser/src $(PYTHON) -m pytest --cov=teams_mattermost_migration_parser --cov-report=term-missing --cov-report=html --cov-report=xml

typecheck:
	PYTHONPATH=apps/parser/src $(PYTHON) -m mypy apps/parser/src apps/parser/tests tests conftest.py

shell-lint:
	shellcheck $$(find scripts -type f -name '*.sh')

yaml-lint:
	yamllint .

docs-lint:
	npx markdownlint-cli README.md CONTRIBUTING.md docs apps

docker-validate:
	@if [[ -f .env ]]; then ENV_FILE=.env; else ENV_FILE=infrastructure/docker/.env.example; fi; \
	docker compose --env-file $$ENV_FILE -f infrastructure/docker/docker-compose.yml config >/dev/null && \
	docker compose --env-file $$ENV_FILE -f infrastructure/docker/docker-compose.monitoring.yml config >/dev/null

manifest-validate:
	@if command -v kustomize >/dev/null 2>&1; then \
	  kustomize build infrastructure/kubernetes/overlays/local >/dev/null; \
	  kustomize build infrastructure/kubernetes/overlays/staging >/dev/null; \
	else \
	  kubectl kustomize infrastructure/kubernetes/overlays/local >/dev/null; \
	  kubectl kustomize infrastructure/kubernetes/overlays/staging >/dev/null; \
	fi

security:
	$(PYTHON) -m pip_audit -r apps/parser/requirements.txt
	$(PYTHON) -m pip_audit -r requirements-dev.txt

lint:
	PYTHONPATH=apps/parser/src ruff check apps/parser/src apps/parser/tests tests
	PYTHONPATH=apps/parser/src ruff format --check apps/parser/src apps/parser/tests tests
	$(MAKE) typecheck
	$(MAKE) shell-lint
	$(MAKE) yaml-lint
	$(MAKE) docs-lint
	$(MAKE) docker-validate
	$(MAKE) manifest-validate

format:
	ruff format apps/parser/src apps/parser/tests tests
	shfmt -w scripts

ci: lint coverage security
