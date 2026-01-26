include .env
export

.PHONY: mock-up mock-down db-schema service-up service-down test lint

# Start mock services only (bank + ledger)
mock-up:
	docker compose up --build bank ledger

mock-down:
	docker compose down

# Start all services including the BNPL decision service
service-up:
	docker compose up --build

service-down:
	docker compose down -v

# Apply database schema (for local development without Docker)
db-schema:
	echo "Applying database schema to $$DATABASE_URL" && \
	psql $$DATABASE_URL -f db/schema.sql

# Run tests
test:
	cd service && python -m pytest ../tests -v

# Install dependencies locally
install:
	pip install -r service/requirements.txt
	pip install pytest pytest-asyncio

# Run service locally (requires mock services and DB running)
run-local:
	cd service && uvicorn main:app --reload --port 8000
