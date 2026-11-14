# Atticus – Python regression test runner
# Runs the offline test suite (no macOS, no AI calls, no network).
# The Swift app and any macOS-only tests are automatically skipped on Linux.
#
# Build:  docker build -t atticus-tests .
# Run:    docker run --rm atticus-tests
# Single test module:
#         docker run --rm atticus-tests python3 -m pytest tests/test_atticus.py -v

FROM python:3.13-slim

# --- system deps -----------------------------------------------------------------
# No third-party PyPI packages are required; atticus.py uses stdlib only.
# Node is installed so the embedded JS syntax check (atticus.py --selftest) works.
RUN apt-get update && apt-get install -y --no-install-recommends \
        nodejs \
    && rm -rf /var/lib/apt/lists/*

# --- source ----------------------------------------------------------------------
WORKDIR /app
COPY atticus.py ./
COPY tests/     ./tests/
COPY ui/        ./ui/
COPY VERSION    ./

# --- runtime env -----------------------------------------------------------------
ENV ATTICUS_DIR=/tmp/atticus-test-config \
    ATTICUS_POSTHOG_KEY="" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# --- smoke-check: Python can parse atticus.py ------------------------------------
RUN python3 -c "import py_compile; py_compile.compile('atticus.py', doraise=True)" \
    && echo "atticus.py syntax OK"

# --- default command: run all offline regressions --------------------------------
CMD ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]
