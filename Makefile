# SAM Makefile build — copies shared source files + installs Lambda-only deps.
# Called by `sam build` with ARTIFACTS_DIR set to the staging directory.

SHARED_PY   = tools.py prompts.py sources.py tracker.py
HANDLER_PY  = fn_orchestrator.py fn_worker.py fn_coordinator.py
LAMBDA_REQS = lambda_requirements.txt

.PHONY: build-OrchestratorFunction build-WorkerFunction build-CoordinatorFunction

build-OrchestratorFunction build-WorkerFunction build-CoordinatorFunction:
	# Pure-Python packages: install normally (none-any wheels work on any platform)
	pip3 install feedparser boto3 -t $(ARTIFACTS_DIR) --quiet --upgrade
	# C-extension packages: force Linux ARM64 wheels so Lambda can load them
	pip3 install google-genai -t $(ARTIFACTS_DIR) --quiet --upgrade \
		--platform manylinux2014_aarch64 \
		--only-binary=:all: \
		--python-version 3.12 \
		--implementation cp
	cp $(SHARED_PY) $(HANDLER_PY) $(ARTIFACTS_DIR)/
