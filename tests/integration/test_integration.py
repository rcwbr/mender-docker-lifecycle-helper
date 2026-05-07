import yaml

from tests.fixtures.mender_server import mender_server
from tests.fixtures.mender_client import mender_client
from tests.utils.mender_server_api import apply_client_to_group
from tests.utils.prepare_repo import prepare_repo
from tests.utils.generate_and_validate_artifact import generate_and_validate_artifact
from tests.utils.docker_utils import verify_manifest_containers_running


class TestIntegrationUploadArtifact:
    """Tests for full mender-docker-lifecycle-helper upload to a Mender server"""

    def test_prebuilt_upload_artifact(self, mender_server, tmp_path):
        mender_host, jwt = mender_server
        repo_dir, repo = prepare_repo(tmp_path)

        generate_and_validate_artifact(
            tmp_path,
            mender_host=mender_host,
            jwt=jwt,
            device_group=None,
            repo_dir=repo_dir,
            repo=repo,
        )

    def test_prebuilt_deploy_artifact(
        self, custom_docker_daemon, mender_server, mender_client, tmp_path
    ):
        docker_host, _, _ = custom_docker_daemon
        mender_host, jwt = mender_server
        mender_client_id = mender_client
        repo_dir, repo = prepare_repo(tmp_path)

        device_group = "testcontainers-clients"
        apply_client_to_group(mender_host, jwt, mender_client_id, device_group)

        generate_and_validate_artifact(
            tmp_path,
            mender_host=mender_host,
            jwt=jwt,
            device_group=device_group,
            repo_dir=repo_dir,
            repo=repo,
            wait_for_deploy=True,
        )

        # Verify that the containers from the manifest are running in the custom Docker daemon
        manifest_file = repo_dir / "prebuilt" / "docker-compose.yaml"
        verify_manifest_containers_running(
            docker_host, manifest_file, f"{repo_dir.name}-prebuilt"
        )

    def test_prebuilt_deploy_delta_artifact(
        self, custom_docker_daemon, mender_server, mender_client, tmp_path
    ):
        docker_host, _, _ = custom_docker_daemon
        mender_host, jwt = mender_server
        mender_client_id = mender_client
        repo_dir, repo = prepare_repo(tmp_path)

        device_group = "testcontainers-clients"
        apply_client_to_group(mender_host, jwt, mender_client_id, device_group)

        manifest_file = repo_dir / "prebuilt" / "docker-compose.yaml"

        # Base artifact
        generate_and_validate_artifact(
            tmp_path,
            mender_host=mender_host,
            jwt=jwt,
            cache=True,
            device_group=device_group,
            repo_dir=repo_dir,
            repo=repo,
            wait_for_deploy=True,
        )

        # Verify containers are running after base deployment
        verify_manifest_containers_running(
            docker_host, manifest_file, f"{repo_dir.name}-prebuilt"
        )

        # Create a new commit to generate a new version for delta
        (repo_dir / "VERSION").write_text("1.0.1")
        repo.index.add(repo_dir / "VERSION")
        repo.index.commit("update version")
        repo.create_tag("1.0.1")

        # Delta artifact
        generate_and_validate_artifact(
            tmp_path,
            mender_host=mender_host,
            jwt=jwt,
            cache=True,
            delta=True,
            device_group=device_group,
            repo_dir=repo_dir,
            repo=repo,
            wait_for_deploy=True,
        )

        # Verify containers are running after delta deployment
        verify_manifest_containers_running(
            docker_host, manifest_file, f"{repo_dir.name}-prebuilt"
        )

    def test_prebuilt_update_image(
        self, custom_docker_daemon, mender_server, mender_client, tmp_path
    ):
        """Test updating the image in the artifact's manifest and generating a new artifact."""
        docker_host, _, _ = custom_docker_daemon
        mender_host, jwt = mender_server
        mender_client_id = mender_client
        repo_dir, repo = prepare_repo(tmp_path)

        device_group = "testcontainers-clients"
        apply_client_to_group(mender_host, jwt, mender_client_id, device_group)

        manifest_file = repo_dir / "prebuilt" / "docker-compose.yaml"

        # Step 1: Generate initial artifact with original image
        initial_artifact = generate_and_validate_artifact(
            tmp_path,
            mender_host=mender_host,
            jwt=jwt,
            device_group=device_group,
            repo_dir=repo_dir,
            repo=repo,
            wait_for_deploy=True,
        )
        # Verify containers are running after initial deployment
        verify_manifest_containers_running(
            docker_host, manifest_file, f"{repo_dir.name}-prebuilt"
        )

        initial_image_hashes = initial_artifact["updates"][0]["metadata"]["images"]
        assert len(initial_image_hashes) == 1
        initial_image_hash = initial_image_hashes[0]
        # Verify initial image hash matches the known busybox:1.37.0-musl hash
        assert (
            initial_image_hash
            == "19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138"
        )

        # Step 2: Update the image in the manifest to a new version
        new_image_ref = "busybox:1.36.1-musl"
        manifest_path = repo_dir / "prebuilt" / "docker-compose.yaml"
        with open(manifest_path, "r") as f:
            compose_config = yaml.safe_load(f)
        compose_config["services"]["prebuilt-service"]["image"] = new_image_ref
        with open(manifest_path, "w") as f:
            yaml.dump(compose_config, f)
        repo.index.add(manifest_path)
        repo.index.commit("Update prebuilt-service image to busybox:1.36.1-musl")

        # Step 3: Generate new artifact with updated image
        updated_artifact = generate_and_validate_artifact(
            tmp_path,
            mender_host=mender_host,
            jwt=jwt,
            device_group=device_group,
            repo_dir=repo_dir,
            repo=repo,
            wait_for_deploy=True,
        )
        # Verify containers are running after updated deployment
        verify_manifest_containers_running(
            docker_host, manifest_file, f"{repo_dir.name}-prebuilt"
        )

        updated_image_hashes = updated_artifact["updates"][0]["metadata"]["images"]
        assert len(updated_image_hashes) == 1
        updated_image_hash = updated_image_hashes[0]
        assert updated_image_hash != initial_image_hash
        # Verify the new image hash is valid (non-empty and different from initial)
        assert isinstance(updated_image_hash, str) and len(updated_image_hash) > 0
