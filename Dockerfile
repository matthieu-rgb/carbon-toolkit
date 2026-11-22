# SPDX-License-Identifier: GPL-3.0-or-later
# CARBON - containerized automotive pentest toolkit.
# Multi-arch (linux/amd64 + linux/arm64) from the same source:
#   docker buildx build --platform linux/amd64,linux/arm64 -t carbon:0.3.0 .
FROM python:3.12-slim

LABEL org.opencontainers.image.title="CARBON" \
      org.opencontainers.image.description="Containerized automotive pentest toolkit" \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.version="0.3.0"

# can-utils: candump/cansend/canplayer; iproute2+kmod: vcan provisioning (needs NET_ADMIN).
RUN apt-get update \
    && apt-get install -y --no-install-recommends can-utils iproute2 kmod \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/carbon
COPY pyproject.toml LICENSE README.md ./
COPY carbon ./carbon
RUN pip install --no-cache-dir . \
    && mkdir -p /usr/share/doc/carbon \
    && cp LICENSE /usr/share/doc/carbon/copyright

COPY scripts ./scripts
COPY docker/entrypoint.sh /usr/local/bin/carbon-entrypoint
RUN chmod 0755 /usr/local/bin/carbon-entrypoint scripts/*.sh \
    && useradd --create-home --shell /usr/sbin/nologin carbon \
    && mkdir /work && chown carbon /work

# Unprivileged by default: no --privileged. Real hardware needs targeted flags (see README).
USER carbon
WORKDIR /work
ENTRYPOINT ["carbon-entrypoint"]
CMD ["--help"]
