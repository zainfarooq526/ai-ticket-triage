.PHONY: install run test lint docker sample

install:
	pip install -r requirements-dev.txt

run:
	uvicorn app.main:app --reload

test:
	pytest -q

lint:
	ruff check .

docker:
	docker compose up --build

sample:
	python scripts/send_webhook.py --all
