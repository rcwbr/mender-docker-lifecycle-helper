from tests.fixtures.mender_server import mender_server
from tests.fixtures.mender_client import mender_client
from tests.utils.mender_server_api import apply_client_to_group
from tests.utils.prepare_repo import prepare_repo
from tests.utils.generate_and_validate_artifact import generate_and_validate_artifact
from tests.utils.docker_utils import verify_manifest_containers_running


class TestIntegrationOci:
    """Tests for OCI-based artifact creation and deployment"""

    def _build_oci_tar(self, tmp_path, dockerfile_content, image_ref, tag="test-oci"):
        """Build a Dockerfile and output as an OCI tar with proper annotations."""
        import json
        import subprocess

        build_dir = tmp_path / "oci-build"
        build_dir.mkdir(exist_ok=True)
        (build_dir / "Dockerfile").write_text(dockerfile_content)

        # Build the image using standard docker build
        result = subprocess.run(
            ["docker", "build", "-t", tag, str(build_dir)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"docker build failed: {result.stderr}")

        # Save the image as docker archive
        docker_tar_path = tmp_path / "docker-image.tar"
        result = subprocess.run(
            ["docker", "save", "-o", str(docker_tar_path), tag],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"docker save failed: {result.stderr}")

        # Convert to OCI layout using skopeo
        oci_dir = tmp_path / "oci-layout"
        oci_dir.mkdir(exist_ok=True)
        result = subprocess.run(
            [
                "skopeo",
                "copy",
                f"docker-archive:{docker_tar_path}",
                f"oci:{oci_dir}",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"skopeo copy failed: {result.stderr}")

        # Add io.containerd.image.name annotation to OCI index
        index_path = oci_dir / "index.json"
        with open(index_path, "r") as f:
            index = json.load(f)

        # Add annotation to the first manifest
        if "manifests" in index and len(index["manifests"]) > 0:
            if "annotations" not in index["manifests"][0]:
                index["manifests"][0]["annotations"] = {}
            index["manifests"][0]["annotations"]["io.containerd.image.name"] = image_ref

        with open(index_path, "w") as f:
            json.dump(index, f)

        # Create OCI tar from the layout directory
        oci_tar_path = tmp_path / "service-image.oci"
        result = subprocess.run(
            ["tar", "-cf", str(oci_tar_path), "-C", str(oci_dir), "."],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"tar failed: {result.stderr}")

        assert oci_tar_path.exists()
        return oci_tar_path

    def test_oci_upload_artifact(self, mender_server, tmp_path):
        """Test building a Dockerfile, saving as OCI tar, and uploading as service-file."""
        mender_host, jwt = mender_server
        repo_dir, repo = prepare_repo(tmp_path)

        # Build OCI tar from a simple Dockerfile
        dockerfile_content = """FROM busybox:1.37.0-musl
"""
        oci_tar_path = self._build_oci_tar(tmp_path, dockerfile_content, "myapp:1.0.0")

        # Use the OCI tar as a service file for prebuilt-service
        service_files = {"prebuilt-service": oci_tar_path}

        generate_and_validate_artifact(
            tmp_path,
            mender_host=mender_host,
            jwt=jwt,
            device_group=None,
            repo_dir=repo_dir,
            repo=repo,
            service_files=service_files,
        )

    def test_oci_deploy_artifact(
        self, custom_docker_daemon, mender_server, mender_client, tmp_path
    ):
        """Test building a Dockerfile, saving as OCI tar, and deploying via service-file."""
        docker_host, _, _ = custom_docker_daemon
        mender_host, jwt = mender_server
        mender_client_id = mender_client
        repo_dir, repo = prepare_repo(tmp_path)

        device_group = "testcontainers-clients"
        apply_client_to_group(mender_host, jwt, mender_client_id, device_group)

        # Build OCI tar from a simple Dockerfile
        dockerfile_content = """FROM busybox:1.37.0-musl
LABEL io.containerd.image.name=oci-app:1.0.0
"""
        oci_tar_path = self._build_oci_tar(
            tmp_path, dockerfile_content, "oci-app:1.0.0"
        )

        # Use the OCI tar as a service file for prebuilt-service
        service_files = {"prebuilt-service": oci_tar_path}
        manifest_file = repo_dir / "prebuilt" / "docker-compose.yaml"

        generate_and_validate_artifact(
            tmp_path,
            mender_host=mender_host,
            jwt=jwt,
            device_group=device_group,
            repo_dir=repo_dir,
            repo=repo,
            service_files=service_files,
            wait_for_deploy=True,
        )

        # Verify that the containers from the manifest are running in the custom Docker daemon
        verify_manifest_containers_running(
            docker_host, manifest_file, f"{repo_dir.name}-prebuilt"
        )
