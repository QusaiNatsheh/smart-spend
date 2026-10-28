PY ?= .venv/bin/python

.PHONY: setup run demo test lint format coverage docker screenshots

setup:            ## virtualenv + dev dependencies + database
	python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
	$(PY) manage.py migrate

run:
	$(PY) manage.py runserver

demo:             ## reset the demo account (demo@smartspend.app / demo1234)
	$(PY) manage.py migrate && $(PY) manage.py seed_demo

test:
	$(PY) manage.py test

coverage:
	$(PY) -m coverage run manage.py test && $(PY) -m coverage report

lint:
	$(PY) -m ruff check . && $(PY) -m ruff format --check .

format:
	$(PY) -m ruff check . --fix && $(PY) -m ruff format .

docker:
	docker compose up --build

screenshots:      ## needs the app running with the demo seeded, plus Playwright
	$(PY) scripts/screenshots.py
