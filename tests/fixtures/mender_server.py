import pytest
import re
import requests
import secrets
import shutil
import socket
import tarfile
import urllib.request

from pathlib import Path

from testcontainers.compose import DockerCompose
from testcontainers.core.wait_strategies import LogMessageWaitStrategy


MENDER_SERVER_VERSION = "v4.1.1"
MENDER_SERVER_TARBALL_URL = f"https://github.com/mendersoftware/mender-server/archive/refs/tags/{MENDER_SERVER_VERSION}.tar.gz"


def download_and_extract_mender_server(target_dir: Path) -> None:
    """Download and extract mender-server tarball to target directory."""
    tarball_name = "mender-server.tar.gz"
    tarball_path = target_dir.parent / tarball_name
    urllib.request.urlretrieve(MENDER_SERVER_TARBALL_URL, tarball_path)

    extract_dir = target_dir.parent / "mender-server-extract"

    with tarfile.open(tarball_path, "r:gz") as tar:
        tar.extractall(extract_dir, filter="data")

    extracted_root = extract_dir / f"mender-server-{MENDER_SERVER_VERSION.lstrip('v')}"
    shutil.copytree(extracted_root, target_dir, dirs_exist_ok=True)

    shutil.rmtree(extract_dir)
    tarball_path.unlink()


def patch_dns(hostmap, scope_socket):
    """Make specified hosts resolve to the given IPs within this process."""
    _original_getaddrinfo = scope_socket.getaddrinfo

    def custom_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if host in hostmap:
            ip, port = hostmap[host]
            return [
                (
                    scope_socket.AF_INET,
                    scope_socket.SOCK_STREAM,
                    scope_socket.IPPROTO_TCP,
                    "",
                    (ip, port),
                )
            ]
        return _original_getaddrinfo(host, port, family, type, proto, flags)

    scope_socket.getaddrinfo = custom_getaddrinfo


def patch_ca_bundle(ca_bundle_path, scope_requests):
    """Make requests use the specified CA bundle within this process."""
    _original_cert_verify = scope_requests.adapters.HTTPAdapter.cert_verify

    def custom_cert_verify(self, conn, url, verify, cert):
        verify = ca_bundle_path
        return _original_cert_verify(self, conn, url, verify, cert)

    scope_requests.adapters.HTTPAdapter.cert_verify = custom_cert_verify


@pytest.fixture(scope="session")
def mender_server_resources():
    """Download and extract mender-server resources."""
    target_dir = Path("tests/resources/mender-server")
    download_and_extract_mender_server(target_dir)
    (target_dir / ".env").write_text("MENDER_IMAGE_TAG=v4.1.0\n")


@pytest.fixture(scope="function")
def mender_server(custom_docker_daemon, mender_server_resources):
    _, daemon_container, docker_compose_wrapper = custom_docker_daemon

    mender_compose = DockerCompose(
        context=Path("tests/resources/mender-server"),
        compose_file_name=["docker-compose.yml"],
        docker_command_path=docker_compose_wrapper,
        wait=True,
        env_file=".env",
        keep_volumes=False,
    )
    mender_compose.waiting_for(
        {
            "useradm": LogMessageWaitStrategy(re.compile(r".*listening on :.*")),
            "deployments": LogMessageWaitStrategy(
                re.compile(r".*DB migrated to version.*")
            ),
        }
    )
    mender_host = "docker.mender.io"

    with mender_compose:
        # Prep authentication
        username = "testcontainers@docker.mender.io"
        password = secrets.token_urlsafe(16)
        mender_compose.exec_in_container(
            ["useradm", "create-user", "--username", username, "--password", password],
            service_name="useradm",
        )

        # Prep hosts and certs for use by direct Python API calls in the tests
        patch_dns(
            {mender_host: ("127.0.0.1", daemon_container.get_exposed_port(443))}, socket
        )
        patch_ca_bundle(
            str(
                Path("tests/resources/mender-server/compose/certs/mender.crt").resolve()
            ),
            requests,
        )

        response = requests.post(
            f"https://{mender_host}/api/management/v1/useradm/auth/login",
            auth=(username, password),
        )
        assert response.status_code == 200
        jwt = response.text

        yield (mender_host, jwt)
