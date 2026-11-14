# Requires just and uv; recipes other than shiv use just's default shell.
# shiv requires just >=1.44, or >=1.32 with --unstable.

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

# Package the te CLI as dist/te.pyz and a Windows PE launcher dist/te.exe.
[script("uv", "run", "--no-project", "--with", "shiv", "--with", "pip", "python")]
shiv:
    from importlib.resources import files
    from pathlib import Path
    import subprocess
    import sys

    dist = Path("dist")
    dist.mkdir(exist_ok=True)
    pyz = dist / "te.pyz"
    subprocess.run(
        [sys.executable, "-m", "shiv", "-c", "te", "-o", "dist/te.pyz", "."],
        check=True,
    )
    # The offset calculation is directly related to the position of the shebang:
    # zipapp includes the shebang in the .pyz archive's reported central-directory
    # offset (eocd - (cd_size + cd_offset) == 0), so concatenating distlib's t64.exe
    # shifts eocd_offset by len(launcher) and makes eocd - (cd_size + cd_offset)
    # match the launcher's length, pointing directly to the shebang's start (#!).
    launcher = files("pip._vendor.distlib").joinpath("t64.exe").read_bytes()
    (dist / "te.exe").write_bytes(launcher + pyz.read_bytes())

# Build the self-contained plugin bundle; accepts --out and --zip.
build-plugin *args:
    uv run --no-project python scripts/build_plugin.py {{ args }}

# --- Maintenance ---

# Report unused definitions without deleting them.
dead-code:
    uv run --no-project python scripts/dead_code.py
