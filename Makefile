# One-command workflow. Windows users without make: see README for the plain commands.
PY := .venv/bin/python
MONTH ?=

.PHONY: setup db refresh demo test verify reset down data app help

help:
	@echo "make setup                 install, start MySQL, load September (first run)"
	@echo "make refresh               load the next month waiting in data/raw (e.g. October)"
	@echo "make refresh MONTH=2026-10 load or reload a specific month"
	@echo "make demo                  clean slate, then load every month"
	@echo "make test                  unit tests"
	@echo "make verify                data checks against the loaded database"
	@echo "make down                  stop MySQL"
	@echo "make app                   Refresh Console: run and watch the monthly refresh"

.venv:
	python3 -m venv .venv
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -r requirements.txt

.env:
	cp .env.example .env

db:
	docker compose up -d --wait

setup: .venv .env db
	$(PY) -m pipeline.run --month 2026-09

refresh: .venv .env db
	$(PY) -m pipeline.run $(if $(MONTH),--month $(MONTH),)

demo: .venv .env db
	$(PY) -m pipeline.run --reset
	$(PY) -m pipeline.run --all

test: .venv
	$(PY) -m pytest -q

verify: .venv .env
	$(PY) scripts/verify.py

reset: .venv .env
	$(PY) -m pipeline.run --reset

down:
	docker compose down

data: .venv
	$(PY) scripts/generate_mock_data.py

app: .venv .env
	$(PY) app.py
