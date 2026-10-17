# hadolint ignore=DL3006
FROM base_context

ARG TARGETARCH

# hadolint ignore=SC2034
RUN DEBIAN_FRONTEND=noninteractive \
    && apt-get update \
    && apt-get install --allow-unauthenticated --no-install-recommends -y \
        mender-artifact=3.9.0* \
        jq=1.6* \
        tree=2.1.0* \
        xdelta3=3.0.11* \
    && apt-get clean \
    && apt-get autoclean \
    && apt-get autoremove \
    && rm -rf /var/cache/debconf \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    case "$TARGETARCH" in \
        amd64) SKOPEO_BIN="skopeo-linux-amd64" ;; \
        arm64) SKOPEO_BIN="skopeo-linux-arm64" ;; \
        *) echo "Unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    wget -q "https://github.com/lework/skopeo-binary/releases/download/v1.22.0/${SKOPEO_BIN}" -O /usr/bin/skopeo \
    && chmod +x /usr/bin/skopeo

COPY <<EOF /etc/containers/policy.json
{
    "default": [
        {
            "type": "insecureAcceptAnything"
        }
    ],
    "transports":
        {
            "docker-daemon":
                {
                    "": [{"type":"insecureAcceptAnything"}]
                }
        }
}
EOF

RUN git config --system --add safe.directory "*"

COPY <<EOF /opt/mender-docker-lifecycle-helper/entrypoint
#!/bin/bash

set -e

mkdir -p /root/.docker
echo \"\${DOCKER_CONFIG_JSON}\" > /root/.docker/config.json
mender-docker-lifecycle-helper \"\$@\"
EOF

RUN chmod +x /opt/mender-docker-lifecycle-helper/entrypoint

ENTRYPOINT [ "/opt/mender-docker-lifecycle-helper/entrypoint" ]
