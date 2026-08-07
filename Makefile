# FRIDAY. Arch Linux, systemd, uv.
#
# Spec section 11 creates the install root. This repo is a normal Python project that
# installs into it:
#
#   this repo        ->  /srv/friday/.venv       (code, via uv)
#   install/tree.sh  ->  /srv/friday/{vault,db,agent,loops,ingest,work,eval,logs}
#
# So `make tree` reproduces exactly the mkdir in spec section 11, and the spec's command
# still describes reality.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

ROOT   ?= /srv/friday
REPO   ?= $(CURDIR)
VENV   ?= $(ROOT)/.venv
UV     ?= uv
UNITS   = $(notdir $(wildcard systemd/*.service))
TIMERS  = $(notdir $(wildcard systemd/*.timer))
STAMP  := $(shell date +%Y%m%d-%H%M%S)

.PHONY: help preflight tree install models services start stop status logs eval test lint backup rollback known-good

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

preflight: ## Verify the box before any week: GPU, VRAM, disk, ports, users, core perms, sops
	@bash install/preflight.sh

tree: ## Create the spec section 11 install root under $(ROOT)
	@sudo bash install/tree.sh

install: preflight tree ## Packages, users, tree, and the Python env (root; touches the network)
	@sudo bash install/00-arch-packages.sh
	@sudo bash install/01-users.sh
	@sudo bash install/02-python-env.sh
	@echo "Next: make models, then make services."

models: ## Download weights into $(ROOT)/models (network, large)
	@sudo bash install/03-models.sh

services: ## Install systemd units and enable the week-1 set
	@sudo bash install/04-services.sh

start: ## Start every friday-* unit and timer
	@sudo systemctl start $(UNITS) $(TIMERS)
	@$(MAKE) --no-print-directory status

stop: ## Stop every friday-* unit and timer, leaving them enabled
	@sudo systemctl stop $(UNITS) $(TIMERS) || true

status: ## One line per friday-* unit
	@systemctl list-units 'friday-*' --all --no-pager --no-legend \
		| awk '{printf "%-40s %-10s %-10s %s\n", $$1, $$3, $$4, $$5}' \
		|| echo "no friday-* units installed yet; run 'make services'"

logs: ## Follow logs across every friday-* unit
	@journalctl -f -n 200 $(foreach u,$(UNITS),-u $(u))

eval: ## Retrieval eval. Gate for week 2-3, and the gate on the known-good tag.
	@if [[ -f eval/questions.yaml ]]; then \
		$(UV) run python eval/run_eval.py --questions eval/questions.yaml; \
	else \
		echo "eval/questions.yaml not found."; \
		echo ""; \
		echo "Spec section 7: build the eval set BEFORE the ingestion. 25 questions about"; \
		echo "your own life with known answers. Copy eval/questions.example.yaml and"; \
		echo "replace every question. The example set does not gate anything."; \
		exit 1; \
	fi

test: ## Run the test suite
	@$(UV) run pytest

lint: ## ruff check, ruff format --check, mypy
	@$(UV) run ruff check .
	@$(UV) run ruff format --check .
	@$(UV) run mypy friday scrutiny supervisor

known-good: eval ## Advance the known-good tag. Spec section 9: only after a full eval pass.
	@echo "Eval passed. Advancing known-good."
	@git tag -f known-good HEAD
	@echo "known-good -> $$(git rev-parse --short HEAD)"
	@echo "The supervisor reverts here after three consecutive health-check failures."

backup: ## Snapshot vault, db, and config
	@sudo install -d -m 0750 -o friday -g friday $(ROOT)/backups
	@sudo systemctl stop friday-hermes friday-openjarvis 2>/dev/null || true
	@sudo tar --exclude='*.db-wal' --exclude='*.db-shm' \
		-czf $(ROOT)/backups/friday-$(STAMP).tar.gz -C $(ROOT) vault db
	@sudo systemctl start friday-hermes friday-openjarvis 2>/dev/null || true
	@sudo ln -sfn $(ROOT)/backups/friday-$(STAMP).tar.gz $(ROOT)/backups/last.tar.gz
	@echo "Wrote $(ROOT)/backups/friday-$(STAMP).tar.gz"

rollback: ## Restore the last snapshot. Destructive; asks first.
	@test -e $(ROOT)/backups/last.tar.gz \
		|| { echo "No snapshot in $(ROOT)/backups. Nothing to roll back to."; exit 1; }
	@echo "This overwrites vault/ and db/ under $(ROOT) from:"
	@readlink -f $(ROOT)/backups/last.tar.gz
	@read -rp "Type 'rollback' to proceed: " ans; [[ "$$ans" == "rollback" ]] || { echo "Aborted."; exit 1; }
	@$(MAKE) --no-print-directory stop
	@sudo tar -xzf $(ROOT)/backups/last.tar.gz -C $(ROOT)
	@$(MAKE) --no-print-directory start
	@echo "Restored. Verify with 'make eval' before trusting retrieval."
