import docker
import time
import yaml
from pathlib import Path


def get_expected_container_names(
    manifest_file: Path, application_name: str
) -> list[str]:
    """Parse a docker-compose manifest and return expected container names."""
    with open(manifest_file, "r") as f:
        compose = yaml.safe_load(f)
    services = compose.get("services", {})
    container_names = []
    for service_name, config in services.items():
        # Use container_name if specified, otherwise use service_name
        container_name = config.get(
            "container_name", f"{application_name}-{service_name}-1"
        )
        container_names.append(container_name)
    return container_names


def check_containers_running(
    docker_host: str, expected_containers: list[str]
) -> dict[str, bool]:
    """Check if the expected containers are running in the Docker daemon.

    Args:
        docker_host: The Docker daemon host (e.g., tcp://localhost:2375)
        expected_containers: List of expected container names

    Returns:
        Dict mapping container names to a boolean indicating if they are running
    """
    client = docker.DockerClient(base_url=docker_host)
    running_containers = client.containers.list(filters={"status": "running"})
    running_names = set()
    for container in running_containers:
        # Container names have a leading '/' in the name
        name = container.name.lstrip("/")
        running_names.add(name)

    result = {}
    for container_name in expected_containers:
        result[container_name] = container_name in running_names

    return result


def verify_manifest_containers_running(
    docker_host: str, manifest_file: Path, application_name: str, timeout: int = 60
) -> None:
    """Verify that all containers from the manifest are running in the Docker daemon.

    Args:
        docker_host: The Docker daemon host (e.g., tcp://localhost:2375)
        manifest_file: Path to the docker-compose manifest file
        timeout: Maximum time in seconds to wait for containers to be running

    Raises:
        AssertionError: If any expected container is not running within the timeout
    """
    expected_containers = get_expected_container_names(manifest_file, application_name)
    assert (
        len(expected_containers) > 0
    ), f"No containers found in manifest {manifest_file}"

    start_time = time.time()
    while time.time() - start_time < timeout:
        container_status = check_containers_running(docker_host, expected_containers)
        all_running = all(container_status.values())
        if all_running:
            return

        time.sleep(2)

    # Final check with assertion error if still not running
    container_status = check_containers_running(docker_host, expected_containers)
    for container_name, is_running in container_status.items():
        assert is_running, (
            f"Container '{container_name}' from manifest {manifest_file} "
            f"is not running in the Docker daemon after {timeout} seconds"
        )
