# syntax=docker/dockerfile:1.7

FROM python:3.12-slim@sha256:d8c0b296afed684f826359df3ad871891b97ad89495fc9f63567761019623259 AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

COPY apps/parser /build/apps/parser

RUN python -m pip install --upgrade pip build && \
    python -m build /build/apps/parser --wheel --outdir /build/dist

FROM python:3.12-slim@sha256:d8c0b296afed684f826359df3ad871891b97ad89495fc9f63567761019623259 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 65532 parser && \
    useradd --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin parser

WORKDIR /workspace

COPY --from=builder /build/dist/*.whl /tmp/parser.whl

RUN python -m pip install --no-cache-dir /tmp/parser.whl && \
    rm -f /tmp/parser.whl

USER 65532:65532

ENTRYPOINT ["tmmp-parser"]
