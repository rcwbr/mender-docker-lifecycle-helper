import pytest
import re
import requests
import random

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from pathlib import Path

from testcontainers.compose import DockerCompose
from testcontainers.core.wait_strategies import LogMessageWaitStrategy


@pytest.fixture(scope="function")
def mender_client(custom_docker_daemon, mender_server, tmp_path):
    _, _, docker_compose_wrapper = custom_docker_daemon
    mender_host, jwt = mender_server

    # Generate a random MAC address to avoid conflicts with previous test runs
    mender_client_mac_address = f"7c:1e:{random.randint(0x00, 0xFF):02x}:{random.randint(0x00, 0xFF):02x}:{random.randint(0x00, 0xFF):02x}:{random.randint(0x00, 0xFF):02x}"

    # Preauthenticate the client
    mender_client_private_key = ed25519.Ed25519PrivateKey.generate()
    mender_client_public_key = (
        mender_client_private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    mender_client_key_file = (tmp_path / "mender-agent.pem").resolve()
    mender_client_key_file.write_text(
        mender_client_private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
    )

    mender_client_metadata = {
        "identity_data": {"mac": mender_client_mac_address},
        "pubkey": mender_client_public_key,
    }
    response = requests.post(
        f"https://{mender_host}/api/management/v2/devauth/devices",
        headers={"Accept": "application/json", "Authorization": f"Bearer {jwt}"},
        json=mender_client_metadata,
    )
    assert response.text == ""
    assert response.status_code == 201

    # Prepare client container
    mender_server_cert = Path(
        "tests/resources/mender-server/compose/certs/mender.crt"
    ).resolve()
    client_env_file = (tmp_path / "test-containers-mender-client.env").resolve()
    client_env_file.write_text(
        'DEVICE_TYPE="virtual"\n'
        f'CLIENT_MAC_ADDRESS="{mender_client_mac_address}"\n'
        f'MENDER_HOST="https://{mender_host}"\n'
        f'MENDER_HOST_CERT="{str(mender_server_cert)}"\n'
        f'TENANT_TOKEN="{jwt}"\n'
        f'MENDER_CLIENT_KEY="{mender_client_key_file}"'
    )
    mender_client = DockerCompose(
        context=Path("tests/resources/mender-client"),
        compose_file_name=["docker-compose.yaml"],
        docker_command_path=docker_compose_wrapper,
        wait=True,
        keep_volumes=False,
        env_file=[str(client_env_file)],
    )
    mender_client.waiting_for(
        {
            "mender-client": LogMessageWaitStrategy(
                re.compile(r".*Inventory data submitted successfully.*")
            )
        }
    )
    with mender_client:
        # Ensure successful client registration
        response = requests.get(
            f"https://{mender_host}/api/management/v2/devauth/devices",
            headers={"Authorization": f"Bearer {jwt}"},
        )
        assert response.status_code == 200
        assert (
            response.json()[0]["auth_sets"][0]["identity_data"]
            == mender_client_metadata["identity_data"]
        )
        assert (
            response.json()[0]["auth_sets"][0]["pubkey"]
            == mender_client_metadata["pubkey"]
        )
        assert (
            response.json()[0]["identity_data"]
            == mender_client_metadata["identity_data"]
        )
        assert response.json()[0]["status"] == "accepted"

        yield response.json()[0]["id"]

        # Print mender-client logs after every test for debugging
        try:
            stdout, stderr = mender_client.get_logs()
            print("\n=== MENDER-CLIENT LOGS ===")
            print(stdout)
            if stderr:
                print("\n=== MENDER-CLIENT STDERR ===")
                print(stderr)
        except Exception as e:
            print(f"\nFailed to capture mender-client logs: {e}")
