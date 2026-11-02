IMAGE ?= dg-intent-disambiguation:dev

.PHONY: install
install: ## Create the virtual environment and install the pre-commit hooks
	@echo "🚀 Creating virtual environment using uv"
	@uv sync
	@uv run pre-commit install

.PHONY: check
check: ## Check the lock file and run the linters
	@echo "🚀 Checking lock file consistency with 'pyproject.toml'"
	@uv lock --locked
	@echo "🚀 Linting code: Running pre-commit"
	@uv run pre-commit run -a

.PHONY: test
test: ## Run the unit tests (no network needed)
	@echo "🚀 Testing code: Running pytest"
	@uv run python -m pytest

.PHONY: test-live
test-live: ## Run the smoke tests against the real SCAYLE model (VPN, .env)
	@uv run --env-file .env python -m pytest -m live_llm

.PHONY: eval
eval: ## Measure accuracy on eval/queries.yaml against SCAYLE (VPN, .env)
	@uv run --env-file .env python eval/run_eval.py

.PHONY: benchmark
benchmark: ## Measure accuracy on the full benchmark, eval/benchmark/benchmark.jsonl (VPN, .env)
	@uv run --env-file .env python eval/run_eval.py --queries eval/benchmark/benchmark.jsonl --concurrency 6

.PHONY: run
run: ## Run the service locally on port 8000 with auto reload (.env)
	@uv run --env-file .env uvicorn intent_disambiguation.main:app --reload --port 8000

.PHONY: docs-openapi
docs-openapi: ## Export the OpenAPI document shown on the docs site
	@uv run python scripts/export_openapi.py

.PHONY: docs-test
docs-test: ## Test if documentation can be built without warnings or errors
	@uv run mkdocs build -s -f docs/mkdocs.yml -d ../site

.PHONY: docs
docs: ## Build and serve the documentation
	@uv run mkdocs serve -f docs/mkdocs.yml

.PHONY: docker-build
docker-build: ## Build the container image
	@docker build -t $(IMAGE) .

.PHONY: docker-run
docker-run: docker-build ## Build and run the container image with .env
	@docker run --rm -p 8000:8000 --env-file .env $(IMAGE)

.PHONY: help
help:
	@uv run python -c "import re; \
	[[print(f'\033[36m{m[0]:<20}\033[0m {m[1]}') for m in re.findall(r'^([a-zA-Z_-]+):.*?## (.*)$$', open(makefile).read(), re.M)] for makefile in ('$(MAKEFILE_LIST)').strip().split()]"

.DEFAULT_GOAL := help
