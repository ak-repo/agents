PY   := .venv/bin/python
PIP  := .venv/bin/pip
PORT ?= 8000

.DEFAULT_GOAL := help
.PHONY: help setup chat verbose web dev test models db clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-9s %s\n", $$1, $$2}'

# Stamp file: (re)installs dependencies whenever requirements.txt changes.
.venv/.installed: requirements.txt
	test -x $(PY) || python3 -m venv .venv
	$(PIP) install -q -r requirements.txt
	touch $@

.env:
	cp .env.example .env
	@echo "Created .env. Put your OPENROUTER_API_KEY in it, then run again."

setup: .venv/.installed .env ## Create .venv, install dependencies, create .env if missing

chat: .venv/.installed .env ## Terminal chat
	$(PY) main.py

verbose: .venv/.installed .env ## Terminal chat, print every tool call
	$(PY) main.py --verbose

web: .venv/.installed .env ## Web chat at http://127.0.0.1:8000 (PORT=9000 to change)
	$(PY) -m uvicorn api:app --port $(PORT)

dev: .venv/.installed .env ## Web chat with auto-reload on code changes
	$(PY) -m uvicorn api:app --port $(PORT) --reload

test: .venv/.installed .env ## Run the 10 live-model test cases (TEST_RUNS=3 make test)
	$(PY) tests.py

models: .venv/.installed ## List free OpenRouter models that support tool calling
	@$(PY) -c "import json,urllib.request as u; d=json.load(u.urlopen('https://openrouter.ai/api/v1/models'))['data']; [print(m['id']) for m in d if m['id'].endswith(':free') and 'tools' in (m.get('supported_parameters') or [])]"

db: .venv/.installed ## Print all rows in the expenses database
	@$(PY) -c "import db; db.init_db(); rows=db.list_expenses(3650, 1000); print('id  amount  category  date  note'); [print(r['id'], r['amount'], r['category'], r['spent_on'], r['note'] or '', sep='  ') for r in rows]; print(len(rows), 'rows')"

clean: ## Remove caches (keeps .venv, .env and expenses.db)
	rm -rf __pycache__ .venv/.installed
