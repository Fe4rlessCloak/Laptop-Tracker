# OLX Pakistan laptop scraper — Release 1.0.0 image.
#
# Build:    docker build -t laptop-tracker:dev .
# Verify:   docker run --rm -v laptop-tracker-data:/app/data laptop-tracker:dev --hours 1
#
# The image is intentionally small. We use python:3.11-slim (Debian, no
# build tools), copy only what the scraper needs to run, and install the
# production dependencies declared in pyproject.toml. There is no `uv` in
# the image; the host uses `uv` for dev convenience, but at runtime `pip`
# is enough and saves ~50 MB of layer space.

FROM python:3.11-slim

# Set the working directory inside the container. /app is conventional
# for Python images and matches what docker-compose.yml mounts.
WORKDIR /app

# Copy dependency metadata first so the pip install layer is cached when
# only source code changes (better build performance).
COPY pyproject.toml ./
COPY scraper ./scraper

# Install the package and its runtime dependencies. ``--no-cache-dir``
# keeps the layer small. ``.`` installs the current project (declared
# in pyproject.toml) plus its ``dependencies`` list.
RUN pip install --no-cache-dir .

# The data volume is mounted at /app/data by docker-compose.yml. The
# scraper writes its SQLite DB and CSV/JSON exports here by default.
RUN mkdir -p /app/data
VOLUME ["/app/data"]

# Default entrypoint. ``docker run --rm <image> --hours 24 --export csv json``
# works the same as the local ``uv run python -m scraper --hours 24 ...``
# invocation. The runner honors every existing CLI flag.
ENTRYPOINT ["python", "-m", "scraper"]

# No CMD — callers always pass their own flags (e.g. ``--hours``, ``--export``).
# If you run the image without flags, the scraper prints its argparse help
# and exits 2, which is the intended behavior.
