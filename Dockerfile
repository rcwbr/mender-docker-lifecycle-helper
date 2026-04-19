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

RUN wget https://github.com/lework/skopeo-binary/releases/download/v1.22.0/skopeo-linux-amd64 -O /usr/bin/skopeo
RUN chmod +x /usr/bin/skopeo
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
