# hadolint ignore=DL3006
FROM base_context

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
