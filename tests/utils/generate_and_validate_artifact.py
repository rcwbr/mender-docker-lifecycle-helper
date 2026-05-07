import os
import requests

from types import SimpleNamespace

from mender_docker_lifecycle_helper.helper import LifecycleHelper


def generate_and_validate_artifact(
    tmp_path,
    mender_host,
    jwt,
    device_group,
    repo_dir,
    repo,
    release=False,
    manifest_file=None,
    platform="linux/amd64",
    device_type="virtual",
    previous_version="1.0.0",
    manifest_name="prebuilt",
    cache=False,
    delta=False,
    repo_name="repo",
    service_files=None,
    service_images=None,
    wait_for_deploy=False,
):
    """Generate an artifact using LifecycleHelper and validate it via the Mender API.

    Args:
        mender_host: The Mender server host (e.g., "docker.mender.io")
        jwt: JWT token for Mender API authentication
        device_group: Device group for the deployment, or None
        repo_dir: Path to the prepared git repository
        repo: The git.Repo object for the repository
        release: Whether to create a release after uploading
        manifest_file: Path to the manifest file (auto-derived if None)
        platform: Target platform for the artifact
        device_type: Device type for the artifact
        previous_version: Previous version for delta calculation
        manifest_name: Name of the manifest (auto-derived if None)
        cache: Whether to use caching
        delta: Whether to generate delta artifacts
        repo_name: Name of the repo for artifact naming
        service_files: Additional service files to include
        service_images: Additional service images to include

    Returns:
        The artifact dict from the Mender API
    """
    if service_files is None:
        service_files = {}
    if service_images is None:
        service_images = {}

    response = requests.get(
        f"https://{mender_host}/api/management/v1/deployments/deployments",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert response.status_code == 200

    if manifest_file is None:
        manifest_file = repo_dir / manifest_name / "docker-compose.yaml"

    application_name = f"{repo_name}-{manifest_name}"
    artifact_filename = (
        repo_dir / f"{application_name}-1.0.0+{repo.head.commit.hexsha[:7]}.mender"
    )
    os.environ["MENDER_PAT"] = jwt
    LifecycleHelper(
        SimpleNamespace(
            artifact_filename=artifact_filename,
            cache=cache,
            cache_dir=tmp_path / "mdlh-cache",
            delta=delta,
            device_type=device_type,
            device_group=device_group,
            log_level="INFO",
            manifest_name=None,
            mender_host=f"https://{mender_host}",
            platform=platform,
            previous_version=previous_version,
            release=release,
            service_files=service_files,
            service_images=service_images,
            manifest_file=manifest_file,
            wait_for_deploy=wait_for_deploy,
        )
    ).prep_artifact()
    assert artifact_filename.exists()

    response = requests.get(
        f"https://{mender_host}/api/management/v1/deployments/artifacts?release_name={application_name}&device_type={device_type}",
        headers={"Accept": "application/json", "Authorization": f"Bearer {jwt}"},
    )
    assert response.status_code == 200
    artifacts = response.json()
    # Find the artifact that matches the expected version pattern
    # The artifact name includes repo_version+commit_short_sha as prefix
    commit_short_sha = repo.head.commit.hexsha[:7]
    repo_version = (repo_dir / "VERSION").read_text().strip()
    expected_prefix = f"{application_name}-{repo_version}+{commit_short_sha}"
    matching_artifacts = [a for a in artifacts if a["name"].startswith(expected_prefix)]
    assert (
        len(matching_artifacts) == 1
    ), f"Expected 1 artifact starting with {expected_prefix}, found {len(matching_artifacts)}: {[a['name'] for a in artifacts]}"
    artifact = matching_artifacts[0]

    # Check artifact_depends - delta artifacts have an additional dependency
    assert artifact["artifact_depends"]["device_type"] == [device_type]
    assert artifact["clears_artifact_provides"] == [
        f"rootfs-image.{application_name}.*"
    ]
    assert artifact["description"] == "string"
    assert artifact["device_types_compatible"] == [device_type]
    assert artifact["info"] == {"format": "mender", "version": 3}
    assert artifact["signed"] is False
    assert (
        artifact["updates"][0]["metadata"]["application_name"] == f"{application_name}"
    )
    assert artifact["updates"][0]["metadata"]["orchestrator"] == "docker-compose"
    assert artifact["updates"][0]["metadata"]["platform"] == platform
    assert artifact["updates"][0]["type_info"] == {"type": "app"}
    assert f"{application_name}-{repo_version}" in artifact["name"]
    assert (
        f"{application_name}-{repo_version}"
        in artifact["artifact_provides"]["artifact_name"]
    )
    assert (
        repo_version
        in artifact["artifact_provides"][f"rootfs-image.{application_name}.version"]
    )
    assert isinstance(artifact["size"], int) and artifact["size"] > 0
    files = artifact["updates"][0]["files"]
    assert len(files) == 2
    file_names = {f["name"] for f in files}
    assert file_names == {"images.tar.gz", "manifests.tar.gz"}
    metadata = artifact["updates"][0]["metadata"]
    assert len(metadata["images"]) == 1
    assert repo_version in metadata["version"]

    return artifact
