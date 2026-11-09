# Requires just and uv; uses just's default shell.

# --- Help ---

# List available recipes.
[default]
help:
    just "--list"

# --- Setup ---

# Install the editable package and test extra into a local virtual environment.
install:
    uv sync --extra test

# --- Tests ---

# For expressions containing spaces, pass shell quotes: just test -k '"plugin and not live"'.
# Run both offline suites without installing the project; append pytest options.
test *args:
    uv run --no-project --with pytest python -m pytest tests experiments/tests {{ args }}

# Run the package and plugin tests; live CLI tests remain opt-in.
test-unit *args:
    uv run --no-project --with pytest python -m pytest tests {{ args }}

# Run the offline experiment tests.
test-experiments *args:
    uv run --no-project --with pytest python -m pytest experiments/tests {{ args }}

# Run all offline checks (no linter or type checker is configured).
check: test

# --- Builds ---

# Build the Python source distribution and wheel in dist/.
build:
    uv build

# Package the local te CLI and its dependencies as dist/te.pyz (requires Python to run).
shiv:
    mkdir -p dist
    uv run --no-project --with shiv --with pip shiv -c te -o dist/te.pyz .

# Build the self-contained plugin bundle; accepts --out and --zip.
build-plugin *args:
    uv run --no-project python scripts/build_plugin.py {{ args }}

# --- Maintenance ---

# Report unused definitions without deleting them.
dead-code:
    uv run --no-project python scripts/dead_code.py
