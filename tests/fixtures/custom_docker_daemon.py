import os
import pytest
import re

from pathlib import Path

from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

pytest_temp_root = Path(os.environ["PYTEST_DEBUG_TEMPROOT"])
tests_resources_path = Path("tests/resources").resolve()


@pytest.fixture(scope="function")
def custom_docker_daemon(tmp_path):
    daemon_container = DockerContainer(
        "docker:29.3.1-dind",
        privileged=True,
        env={"DOCKER_TLS_CERTDIR": ""},
        volumes=[
            ("testcontainers-dind-temp", "/var/lib/docker/containerd", "rw"),
            ("pytest-tmp", str(pytest_temp_root), "rw"),
            (str(tests_resources_path), str(tests_resources_path), "ro"),
        ],
        ports=[2375, 443],
        command="--tls=false",
    )
    daemon_container.waiting_for(
        LogMessageWaitStrategy(re.compile(r".*API listen on \[::\]:2375.*"))
    )

    with daemon_container:
        docker_host = f"tcp://localhost:{daemon_container.get_exposed_port(2375)}"

        # Create a wrapper script that sets DOCKER_HOST and runs docker
        docker_compose_wrapper = (tmp_path / "test-containers-docker-compose").resolve()
        docker_compose_wrapper.write_text(
            f'#!/bin/bash\nDOCKER_HOST={docker_host} docker "$@"\n'
        )
        os.chmod(docker_compose_wrapper, 0o755)

        yield docker_host, daemon_container, docker_compose_wrapper
