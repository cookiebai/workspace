run:
	@if [ -z "$$ADDR" ] || [ -z "$$PORT" ]; then \
		echo "Please export ADDR and PORT before running the B4 configurator"; \
		exit 1; \
	fi; \
	ADDR=$$ADDR PORT=$$PORT python3 main.py
