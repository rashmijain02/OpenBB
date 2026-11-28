# Local, never-pushed comparison image for the Nautilus worker (#1355, L2).
# Build context is this directory. BASE_IMAGE_DIGEST must be supplied
# (e.g. sha256:...); an empty value makes the FROM line invalid, so the build fails closed.
ARG BASE_IMAGE_DIGEST
FROM python:3.12-slim-bookworm@${BASE_IMAGE_DIGEST}

COPY requirements-linux_x86_64-cp312.lock /tmp/requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes --no-deps -r /tmp/requirements.lock \
    && rm /tmp/requirements.lock

COPY openbb_nautilus_worker /opt/worker/openbb_nautilus_worker
ENV PYTHONPATH=/opt/worker PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --no-create-home --uid 10001 worker
USER 10001

# No listener. Run with: --network none --read-only --cap-drop ALL
ENTRYPOINT ["python", "-I", "-m", "openbb_nautilus_worker"]
