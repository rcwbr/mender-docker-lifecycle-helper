import subprocess

from pathlib import Path

from tests.fixtures.mender_server import mender_server
from tests.fixtures.mender_client import mender_client
from tests.utils.mender_server_api import apply_client_to_group
from tests.utils.prepare_repo import prepare_repo
from tests.utils.generate_and_validate_artifact import generate_and_validate_artifact
from tests.utils.docker_utils import verify_manifest_containers_running


def _ensure_builder():
    """Ensure a buildx builder with docker-container driver exists."""

    # Check for existing builder with container driver
    result = subprocess.run(
        ["docker", "buildx", "ls", "--format", "{{.Name}} {{.Driver}}"],
        capture_output=True,
        text=True,
    )
    for line in result.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "docker-container":
            return parts[0]

    # Create a new builder with --use flag
    result = subprocess.run(
        [
            "docker",
            "buildx",
            "create",
            "--driver",
            "docker-container",
            "--name",
            "oci-builder",
            "--use",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        if "existing instance" in result.stderr:
            return "oci-builder"
        raise RuntimeError(f"Failed to create buildx builder: {result.stderr}")
    return "oci-builder"


def _build_oci_tar(
    tmp_path, dockerfile_content, tag="test-oci", bake_hcl=None, output_path=None
):
    """Build a Dockerfile and output as an OCI tar using docker buildx bake."""

    build_dir = tmp_path / "oci-build"
    build_dir.mkdir(exist_ok=True)

    (build_dir / "Dockerfile").write_text(dockerfile_content)

    oci_tar_path = output_path or tmp_path / "service-image.oci"
    builder = _ensure_builder()

    # Write the bake HCL file with values substituted
    if bake_hcl is None:
        bake_hcl = (
            'target "test-oci" {\n'
            f'  context    = "{build_dir}"\n'
            f'  dockerfile = "{build_dir}/Dockerfile"\n'
            f'  tags       = ["{tag}"]\n'
            f'  output     = ["type=oci,dest={oci_tar_path}"]\n'
            "}\n"
        )
    bake_file = tmp_path / "docker-bake.hcl"
    bake_file.write_text(bake_hcl)

    result = subprocess.run(
        [
            "docker",
            "buildx",
            "bake",
            "--builder",
            builder,
            "--allow",
            f"fs.read={build_dir}",
            "-f",
            str(bake_file),
            "test-oci",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker buildx bake failed: {result.stderr}")

    assert oci_tar_path.exists()
    return oci_tar_path


class TestIntegrationOCI:
    """Tests for OCI-based artifact creation and deployment"""

    def test_oci_upload_artifact(self, mender_server, tmp_path):
        """Test building a Dockerfile, saving as OCI tar, and uploading as service-file."""
        mender_host, jwt = mender_server
        repo_dir, repo = prepare_repo(tmp_path)

        # Build OCI tar from a simple Dockerfile
        dockerfile_content = (
            "FROM busybox:1.37.0-musl\n" "LABEL io.containerd.image.name=myapp:1.0.0\n"
        )
        oci_tar_path = _build_oci_tar(tmp_path, dockerfile_content)

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

    def test_oci_deploy_multiplatform_artifact(
        self, custom_docker_daemon, mender_server, mender_client, tmp_path
    ):
        """Test building a Dockerfile, saving as OCI tar, specified as multi-artifact, and deploying via service-file."""
        docker_host, _, _ = custom_docker_daemon
        mender_host, jwt = mender_server
        mender_client_id = mender_client
        repo_dir, repo = prepare_repo(tmp_path)

        device_group = "testcontainers-clients"
        apply_client_to_group(mender_host, jwt, mender_client_id, device_group)

        # Build OCI tar from a simple Dockerfile
        dockerfile_content = "FROM busybox:1.37.0-musl\n"
        build_dir = tmp_path / "oci-build"
        oci_tar_path = tmp_path / "multiplatform.oci"
        oci_tar_path = _build_oci_tar(
            tmp_path,
            dockerfile_content,
            output_path=oci_tar_path,
            bake_hcl='target "test-oci" {\n'
            f'  context    = "{build_dir}"\n'
            f'  dockerfile = "{build_dir}/Dockerfile"\n'
            "   args = {\n"
            "       BUILDKIT_MULTI_PLATFORM = 1\n"
            "   }\n"
            "   platforms = [\n"
            '       "linux/amd64"\n'
            "   ]\n"
            "   annotations = [\n"
            '       "index-descriptor:io.containerd.image.name=oci-app:1.0.0"\n'
            "   ]\n"
            f'  output     = ["type=oci,dest={oci_tar_path}"]\n'
            "}\n",
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
        dockerfile_content = (
            "FROM busybox:1.37.0-musl\n"
            "LABEL io.containerd.image.name=oci-app:1.0.0\n"
        )
        oci_tar_path = _build_oci_tar(tmp_path, dockerfile_content)

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

    def test_oci_deploy_delta_artifact(
        self, custom_docker_daemon, mender_server, mender_client, tmp_path
    ):
        """Test building OCI images and deploying a delta artifact after modification."""
        docker_host, _, _ = custom_docker_daemon
        mender_host, jwt = mender_server
        mender_client_id = mender_client
        repo_dir, repo = prepare_repo(tmp_path)

        device_group = "testcontainers-clients"
        apply_client_to_group(mender_host, jwt, mender_client_id, device_group)

        manifest_file = repo_dir / "prebuilt" / "docker-compose.yaml"

        # Step 1: Build and deploy base OCI image
        dockerfile_v1 = (
            "FROM busybox:1.37.0-musl\n"
            "RUN echo test1 > /test-file\n"
            "LABEL io.containerd.image.name=oci-app:1.0.0\n"
        )
        oci_tar_v1 = _build_oci_tar(tmp_path, dockerfile_v1)

        generate_and_validate_artifact(
            tmp_path,
            mender_host=mender_host,
            jwt=jwt,
            cache=True,
            device_group=device_group,
            repo_dir=repo_dir,
            repo=repo,
            service_files={"prebuilt-service": oci_tar_v1},
            wait_for_deploy=True,
        )

        # Verify containers are running after base deployment
        verify_manifest_containers_running(
            docker_host, manifest_file, f"{repo_dir.name}-prebuilt"
        )

        # Step 2: Modify the Dockerfile and build new OCI image
        dockerfile_v2 = (
            "FROM busybox:1.36.1-musl\n"
            "RUN echo test2 > /test-file\n"
            "LABEL io.containerd.image.name=oci-app:1.0.1\n"
        )
        oci_tar_v2 = _build_oci_tar(tmp_path, dockerfile_v2)

        # Create a new commit to generate a new version for delta
        (repo_dir / "VERSION").write_text("1.0.1")
        repo.index.add(repo_dir / "VERSION")
        repo.index.commit("update version")
        repo.create_tag("1.0.1")

        # Step 3: Generate and deploy delta artifact
        generate_and_validate_artifact(
            tmp_path,
            mender_host=mender_host,
            jwt=jwt,
            cache=True,
            delta=True,
            device_group=device_group,
            repo_dir=repo_dir,
            repo=repo,
            service_files={"prebuilt-service": oci_tar_v2},
            wait_for_deploy=True,
        )

        # Verify containers are running after delta deployment
        verify_manifest_containers_running(
            docker_host, manifest_file, f"{repo_dir.name}-prebuilt"
        )

    def test_oci_deploy_multiplatform_update_and_redeploy(
        self, custom_docker_daemon, mender_server, mender_client, tmp_path
    ):
        """Test multiplatform artifact deployment, update Dockerfile, and redeploy."""
        docker_host, _, _ = custom_docker_daemon
        mender_host, jwt = mender_server
        mender_client_id = mender_client
        repo_dir, repo = prepare_repo(tmp_path)

        device_group = "testcontainers-clients"
        apply_client_to_group(mender_host, jwt, mender_client_id, device_group)

        manifest_file = repo_dir / "prebuilt" / "docker-compose.yaml"
        build_dir = tmp_path / "oci-build"
        oci_tar_path = tmp_path / "multiplatform.oci"

        # Step 1: Build and deploy v1 multiplatform OCI image
        dockerfile_v1 = "FROM busybox:1.37.0-musl\n"
        oci_tar_v1 = _build_oci_tar(
            tmp_path,
            dockerfile_v1,
            output_path=oci_tar_path,
            bake_hcl='target "test-oci" {\n'
            f'  context    = "{build_dir}"\n'
            f'  dockerfile = "{build_dir}/Dockerfile"\n'
            "   args = {\n"
            "       BUILDKIT_MULTI_PLATFORM = 1\n"
            "   }\n"
            "   platforms = [\n"
            '       "linux/amd64"\n'
            "   ]\n"
            "   annotations = [\n"
            '       "index-descriptor:io.containerd.image.name=multiplatform-app:1.0.0"\n'
            "   ]\n"
            f'  output     = ["type=oci,dest={oci_tar_path}"]\n'
            "}\n",
        )

        generate_and_validate_artifact(
            tmp_path,
            mender_host=mender_host,
            jwt=jwt,
            cache=True,
            device_group=device_group,
            repo_dir=repo_dir,
            repo=repo,
            service_files={"prebuilt-service": oci_tar_v1},
            wait_for_deploy=True,
        )

        # Verify containers are running after base deployment
        verify_manifest_containers_running(
            docker_host, manifest_file, f"{repo_dir.name}-prebuilt"
        )

        # Step 2: Update the Dockerfile and build new multiplatform OCI image
        dockerfile_v2 = "FROM busybox:1.36.1-musl\n"
        oci_tar_v2 = _build_oci_tar(
            tmp_path,
            dockerfile_v2,
            output_path=oci_tar_path,
            bake_hcl='target "test-oci" {\n'
            f'  context    = "{build_dir}"\n'
            f'  dockerfile = "{build_dir}/Dockerfile"\n'
            "   args = {\n"
            "       BUILDKIT_MULTI_PLATFORM = 1\n"
            "   }\n"
            "   platforms = [\n"
            '       "linux/amd64"\n'
            "   ]\n"
            "   annotations = [\n"
            '       "index-descriptor:io.containerd.image.name=multiplatform-app:1.0.1"\n'
            "   ]\n"
            f'  output     = ["type=oci,dest={oci_tar_path}"]\n'
            "}\n",
        )

        # Create a new commit to generate a new version
        (repo_dir / "VERSION").write_text("1.0.1")
        repo.index.add([repo_dir / "VERSION"])
        repo.index.commit("update version")
        repo.create_tag("1.0.1")

        # Step 3: Generate and deploy updated multiplatform artifact
        generate_and_validate_artifact(
            tmp_path,
            mender_host=mender_host,
            jwt=jwt,
            cache=True,
            delta=True,
            device_group=device_group,
            repo_dir=repo_dir,
            repo=repo,
            service_files={"prebuilt-service": oci_tar_v2},
            platform="linux/amd64",
            wait_for_deploy=True,
        )

        # Verify containers are running after update deployment
        verify_manifest_containers_running(
            docker_host, manifest_file, f"{repo_dir.name}-prebuilt"
        )

    def test_oci_deploy_five_iterations_delta(
        self, custom_docker_daemon, mender_server, mender_client, tmp_path
    ):
        """Test deploying an OCI image and updating/redeploying it 5 times as delta artifacts."""
        docker_host, _, _ = custom_docker_daemon
        mender_host, jwt = mender_server
        mender_client_id = mender_client
        repo_dir, repo = prepare_repo(tmp_path)

        device_group = "testcontainers-clients"
        apply_client_to_group(mender_host, jwt, mender_client_id, device_group)

        manifest_file = repo_dir / "prebuilt" / "docker-compose.yaml"
        build_dir = tmp_path / "oci-build"
        oci_tar_path = tmp_path / "multiplatform.oci"

        # Step 1: Build and deploy initial multiplatform OCI image (v1.0.0)
        # Keep busybox version consistent so delta layers can be computed
        dockerfile_v1 = "FROM busybox:1.36.0-musl\n" "RUN echo test1 > /test-file\n"
        oci_tar_v1 = _build_oci_tar(
            tmp_path,
            dockerfile_v1,
            output_path=oci_tar_path,
            bake_hcl='target "test-oci" {\n'
            f'  context    = "{build_dir}"\n'
            f'  dockerfile = "{build_dir}/Dockerfile"\n'
            "   args = {\n"
            "       BUILDKIT_MULTI_PLATFORM = 1\n"
            "   }\n"
            "   platforms = [\n"
            '       "linux/amd64"\n'
            "   ]\n"
            "   annotations = [\n"
            '       "index-descriptor:io.containerd.image.name=five-iterations-app:1.0.0"\n'
            "   ]\n"
            f'  output     = ["type=oci,dest={oci_tar_path}"]\n'
            "}\n",
        )

        generate_and_validate_artifact(
            tmp_path,
            mender_host=mender_host,
            jwt=jwt,
            cache=True,
            device_group=device_group,
            repo_dir=repo_dir,
            repo=repo,
            service_files={"prebuilt-service": oci_tar_v1},
            wait_for_deploy=True,
        )

        verify_manifest_containers_running(
            docker_host, manifest_file, f"{repo_dir.name}-prebuilt"
        )

        # Steps 2-6: 5 iterations of update and redeploy as delta artifacts
        # Each iteration changes an existing layer and adds an ADDITIONAL new layer
        # Same base image (busybox:1.36.0) so delta computation can find common layers
        # v1.0.0 has 1 layer (test-file), v1.0.5 should have 4 more = 5 layers total
        versions = ["1.0.1", "1.0.2", "1.0.3", "1.0.4", "1.0.5"]
        modified_contents = [
            "modified2",
            "modified3",
            "modified4",
            "modified5",
            "modified6",
        ]

        for iteration, (version, mod_content) in enumerate(
            zip(versions, modified_contents), start=1
        ):
            # Build new multiplatform OCI image
            # Each iteration adds incrementally more layers than previous
            # v1.0.0: 1 layer, v1.0.1: 2 layers, v1.0.2: 3 layers, v1.0.3: 4 layers
            # v1.0.4: 5 layers, v1.0.5: stays at 5 layers (4 more than v1.0.0)
            dockerfile_lines = [
                "FROM busybox:1.36.0-musl",
                f"RUN echo {mod_content} > /test-file",  # Modified existing layer
            ]

            # Each iteration adds 'iteration' new layers, capped so v1.0.5 has 4 more than v1.0.0
            # v1.0.1: 1 layer, v1.0.2: 2, v1.0.3: 3, v1.0.4: 4, v1.0.5: 4 (capped)
            num_layers = min(iteration, 4)
            for i in range(1, num_layers + 1):
                dockerfile_lines.append(f"RUN echo layer{i}_v{version} > /layer{i}.txt")

            dockerfile = "\n".join(dockerfile_lines) + "\n"

            oci_tar = _build_oci_tar(
                tmp_path,
                dockerfile,
                output_path=oci_tar_path,
                bake_hcl='target "test-oci" {\n'
                f'  context    = "{build_dir}"\n'
                f'  dockerfile = "{build_dir}/Dockerfile"\n'
                "   args = {\n"
                "       BUILDKIT_MULTI_PLATFORM = 1\n"
                "   }\n"
                "   platforms = [\n"
                '       "linux/amd64"\n'
                "   ]\n"
                f"   annotations = [\n"
                f'       "index-descriptor:io.containerd.image.name=five-iterations-app:{version}"\n'
                "   ]\n"
                f'  output     = ["type=oci,dest={oci_tar_path}"]\n'
                "}\n",
            )

            # Update version in repo
            (repo_dir / "VERSION").write_text(version)
            repo.index.add([repo_dir / "VERSION"])
            repo.index.commit(f"update to {version}")
            repo.create_tag(version)

            # Deploy as delta artifact
            generate_and_validate_artifact(
                tmp_path,
                mender_host=mender_host,
                jwt=jwt,
                cache=True,
                delta=True,
                device_group=device_group,
                repo_dir=repo_dir,
                repo=repo,
                service_files={"prebuilt-service": oci_tar},
                platform="linux/amd64",
                wait_for_deploy=True,
            )

            verify_manifest_containers_running(
                docker_host, manifest_file, f"{repo_dir.name}-prebuilt"
            )
