PY   := .venv/bin/python
PIP  := .venv/bin/pip

.DEFAULT_GOAL := help
.PHONY: help setup run test clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-9s %s\n", $$1, $$2}'

# Stamp file: (re)installs dependencies whenever requirements.txt changes.
.venv/.installed: requirements.txt
	test -x $(PY) || python3 -m venv .venv
	$(PIP) install -q -r requirements.txt
	touch $@

.env:
	cp .env.example .env
	@echo "Created .env. Fill in any keys, then run again."

setup: .venv/.installed .env ## Create .venv, install dependencies, create .env if missing

run: .venv/.installed .env ## Run the agent
	$(PY) main.py

test: .venv/.installed ## Run the tests (use fakes; no paid API calls)
	$(PY) -m unittest discover -s . -p "test*.py"

clean: ## Remove caches (keeps .venv and .env)
	rm -rf __pycache__ .venv/.installed
