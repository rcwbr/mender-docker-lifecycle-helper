"""Unit tests for the LifecycleHelper class."""

import uuid
from unittest.mock import MagicMock, patch, mock_open

from pathlib import Path
from types import SimpleNamespace

import pytest

from mender_docker_lifecycle_helper.helper import LifecycleHelper
from mender_docker_lifecycle_helper.artifact_metadata import ArtifactMetadata


@pytest.fixture
def mock_context():
    """Create a mock LifecycleHelperContext."""
    return SimpleNamespace(
        manifest_name="test-manifest",
        artifact_filename=None,
        device_group=None,
        logger=MagicMock(),
        repo_version="1.0.0",
        previous_artifact_metadata=SimpleNamespace(
            version="0.9.0+abc123",
            to_dict=lambda: {"version": "0.9.0+abc123", "services": {}},
        ),
        commit_short_sha="abc1234",
        temp_dir=Path("/tmp/test"),
        cache_artifact_metadata_file=Path(
            "/tmp/test/cache/manifests/test-manifest/previous_artifact.json"
        ),
        cache=False,
    )


@pytest.fixture
def mock_artifact_metadata():
    """Create a mock ArtifactMetadata."""
    return ArtifactMetadata(
        "1.0.0+abc1234",
        services={"server": {"image": {"ref": "my-server:latest", "hash": "abc123"}}},
    )


class TestLifecycleHelperInit:
    """Tests for LifecycleHelper initialization."""

    def test_init_creates_context(self):
        """Test that __init__ creates a LifecycleHelperContext from args."""
        args = SimpleNamespace(
            artifact_filename=None,
            cache=False,
            cache_dir=None,
            delta=False,
            device_type="virtual",
            device_group=None,
            log_level="INFO",
            manifest_file=Path("docker-compose.yaml"),
            manifest_name="test",
            mender_host="https://hosted.mender.io",
            platform="platform",
            previous_version=None,
            release=False,
            service_files=None,
            service_images=None,
        )

        with patch(
            "mender_docker_lifecycle_helper.helper.LifecycleHelperContext"
        ) as mock_context_class:
            mock_context = MagicMock()
            mock_context_class.return_value = mock_context

            helper = LifecycleHelper(args)

            mock_context_class.assert_called_once_with(args)
            assert helper.context == mock_context


class TestCreateArtifact:
    """Tests for the create_artifact method."""

    def test_create_artifact_with_provided_filename(
        self, mock_context, mock_artifact_metadata
    ):
        """Test create_artifact uses provided artifact_filename."""
        mock_context.artifact_filename = "my-artifact.mender"
        mock_context.manifest_name = "test-manifest"

        helper = LifecycleHelper.__new__(LifecycleHelper)
        helper.context = mock_context

        with patch(
            "mender_docker_lifecycle_helper.helper.LifecycleHelperArtifact"
        ) as mock_artifact_class:
            mock_artifact = MagicMock()
            mock_artifact.name = "test-manifest-1.0.0+abc1234"
            mock_artifact.filename = Path("my-artifact.mender")
            mock_artifact_class.return_value = mock_artifact

            result = helper.create_artifact(mock_artifact_metadata)

            mock_artifact_class.assert_called_once_with(
                mock_context,
                "test-manifest-1.0.0+abc1234",
                mock_artifact_metadata,
                Path("my-artifact.mender").resolve(),
            )
            mock_artifact.gen_artifact_file.assert_called_once()
            assert result == mock_artifact

    def test_create_artifact_generates_filename(
        self, mock_context, mock_artifact_metadata
    ):
        """Test create_artifact generates filename when not provided."""
        mock_context.artifact_filename = None
        mock_context.manifest_name = "test-manifest"

        helper = LifecycleHelper.__new__(LifecycleHelper)
        helper.context = mock_context

        with patch(
            "mender_docker_lifecycle_helper.helper.LifecycleHelperArtifact"
        ) as mock_artifact_class:
            mock_artifact = MagicMock()
            mock_artifact.name = "test-manifest-1.0.0+abc1234"
            mock_artifact.filename = Path("test-manifest-1.0.0+abc1234.mender")
            mock_artifact_class.return_value = mock_artifact

            result = helper.create_artifact(mock_artifact_metadata)

            mock_artifact_class.assert_called_once_with(
                mock_context,
                "test-manifest-1.0.0+abc1234",
                mock_artifact_metadata,
                Path("test-manifest-1.0.0+abc1234.mender").resolve(),
            )
            mock_artifact.gen_artifact_file.assert_called_once()
            assert result == mock_artifact

    def test_create_artifact_logs_info(self, mock_context, mock_artifact_metadata):
        """Test create_artifact logs appropriate info messages."""
        mock_context.artifact_filename = "my-artifact.mender"
        mock_context.manifest_name = "test-manifest"
        mock_context.logger = MagicMock()

        helper = LifecycleHelper.__new__(LifecycleHelper)
        helper.context = mock_context

        with patch(
            "mender_docker_lifecycle_helper.helper.LifecycleHelperArtifact"
        ) as mock_artifact_class:
            mock_artifact = MagicMock()
            mock_artifact.name = "test-manifest-1.0.0+abc1234"
            mock_artifact.filename = Path("my-artifact.mender")
            mock_artifact_class.return_value = mock_artifact

            helper.create_artifact(mock_artifact_metadata)

            mock_context.logger.info.assert_any_call(
                f"Generating artifact file {Path('my-artifact.mender').resolve()}"
            )
            mock_context.logger.info.assert_any_call(
                "Artifact file generated successfully."
            )


class TestUploadArtifact:
    """Tests for the upload_artifact method."""

    def test_upload_artifact_calls_api(self, mock_context):
        """Test upload_artifact calls the Mender API with correct parameters."""
        mock_context.mender_host = "https://hosted.mender.io"
        mock_context.logger = MagicMock()

        artifact = MagicMock()
        artifact.filename = Path("/tmp/test-artifact.mender")
        artifact.name = "test-manifest-1.0.0"

        helper = LifecycleHelper.__new__(LifecycleHelper)
        helper.context = mock_context

        with patch(
            "mender_docker_lifecycle_helper.helper.call_mender_host_api"
        ) as mock_call_api:
            with patch("builtins.open", mock_open(read_data=b"fake artifact data")):
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value.st_size = 100

                    helper.upload_artifact(artifact)

                    assert mock_call_api.call_count == 1
                    call_args = mock_call_api.call_args
                    assert call_args[0][0] == mock_context
                    assert call_args[0][1] == "deployments/artifacts"
                    assert call_args[0][2]["data"]["size"] == 100
                    assert call_args[0][2]["data"]["description"] == "string"
                    assert "artifact" in call_args[0][2]["files"]

    def test_upload_artifact_logs_info(self, mock_context):
        """Test upload_artifact logs appropriate info message."""
        mock_context.logger = MagicMock()

        artifact = MagicMock()
        artifact.filename = Path("/tmp/test-artifact.mender")
        artifact.name = "test-manifest-1.0.0"

        helper = LifecycleHelper.__new__(LifecycleHelper)
        helper.context = mock_context

        with patch("mender_docker_lifecycle_helper.helper.call_mender_host_api"):
            with patch("builtins.open", mock_open(read_data=b"fake artifact data")):
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value.st_size = 100

                    helper.upload_artifact(artifact)

                    mock_context.logger.info.assert_called_once_with(
                        f"Uploaded artifact {artifact.filename}"
                    )


class TestDeployArtifact:
    """Tests for the deploy_artifact method."""

    def test_deploy_artifact_calls_api(self, mock_context):
        """Test deploy_artifact calls the Mender API with correct parameters."""
        mock_context.device_group = "test-group"
        mock_context.logger = MagicMock()

        artifact = MagicMock()
        artifact.name = "test-manifest-1.0.0"

        helper = LifecycleHelper.__new__(LifecycleHelper)
        helper.context = mock_context

        with patch(
            "mender_docker_lifecycle_helper.helper.call_mender_host_api"
        ) as mock_call_api:
            helper.deploy_artifact(artifact)

            assert mock_call_api.call_count == 1
            call_args = mock_call_api.call_args
            assert call_args[0][0] == mock_context
            assert call_args[0][1] == "deployments/deployments/group/test-group"
            assert call_args[0][2]["json"]["name"] == "test-manifest-1.0.0-test-group"
            assert call_args[0][2]["json"]["artifact_name"] == "test-manifest-1.0.0"

    def test_deploy_artifact_logs_info(self, mock_context):
        """Test deploy_artifact logs appropriate info and debug messages."""
        mock_context.device_group = "test-group"
        mock_context.logger = MagicMock()

        artifact = MagicMock()
        artifact.name = "test-manifest-1.0.0"

        helper = LifecycleHelper.__new__(LifecycleHelper)
        helper.context = mock_context

        with patch("mender_docker_lifecycle_helper.helper.call_mender_host_api"):
            helper.deploy_artifact(artifact)

            mock_context.logger.debug.assert_called_once_with(
                f"Creating deployment for artifact {artifact.name} to device group {mock_context.device_group}"
            )
            mock_context.logger.info.assert_called_once_with(
                f"Created deployment test-manifest-1.0.0-test-group"
            )

    def test_deploy_artifact_generates_correct_deployment_name(self, mock_context):
        """Test deploy_artifact generates correct deployment name from artifact name and device group."""
        mock_context.device_group = "production-devices"
        mock_context.logger = MagicMock()

        artifact = MagicMock()
        artifact.name = "my-app-2.0.0"

        helper = LifecycleHelper.__new__(LifecycleHelper)
        helper.context = mock_context

        with patch(
            "mender_docker_lifecycle_helper.helper.call_mender_host_api"
        ) as mock_call_api:
            helper.deploy_artifact(artifact)

            call_args = mock_call_api.call_args
            json_data = call_args[0][2]["json"]
            assert json_data["name"] == "my-app-2.0.0-production-devices"


class TestPrepArtifact:
    """Tests for the prep_artifact method."""

    def test_prep_artifact_release_version(self, mock_context):
        """Test prep_artifact uses repo version when release is True."""
        mock_context.release = True
        mock_context.repo_version = "1.0.0"
        mock_context.device_group = None
        mock_context.logger = MagicMock()

        helper = LifecycleHelper.__new__(LifecycleHelper)
        helper.context = mock_context

        with patch(
            "mender_docker_lifecycle_helper.helper.LifecycleHelperArtifact"
        ) as mock_artifact_class:
            mock_artifact = MagicMock()
            mock_artifact.name = "test-manifest-1.0.0"
            mock_artifact_class.return_value = mock_artifact

            with patch.object(helper, "create_artifact") as mock_create:
                mock_create.return_value = mock_artifact
                with patch.object(helper, "upload_artifact") as mock_upload:
                    with patch(
                        "mender_docker_lifecycle_helper.helper.ArtifactMetadata"
                    ) as mock_metadata_class:
                        mock_metadata = MagicMock()
                        mock_metadata_class.return_value = mock_metadata
                        mock_metadata.to_dict.return_value = {
                            "version": "1.0.0",
                            "services": {},
                        }

                        with patch.object(
                            mock_artifact_class,
                            "gen_artifact_services",
                            return_value={
                                "server": {"image": {"ref": "test", "hash": "123"}}
                            },
                        ):
                            helper.prep_artifact()

                            mock_context.logger.info.assert_any_call(
                                "Preparing an artifact for release, so using the repo version."
                            )
                            mock_context.logger.info.assert_any_call(
                                "Preparing an artifact with the version 1.0.0"
                            )

    def test_prep_artifact_non_release_version(self, mock_context):
        """Test prep_artifact generates version with SHA and UUID when release is False."""
        mock_context.release = False
        mock_context.repo_version = "1.0.0"
        mock_context.previous_artifact_metadata.version = "0.9.0+abc123"
        mock_context.device_group = None
        mock_context.commit_short_sha = "abc1234"
        mock_context.logger = MagicMock()

        helper = LifecycleHelper.__new__(LifecycleHelper)
        helper.context = mock_context

        with patch(
            "mender_docker_lifecycle_helper.helper.LifecycleHelperArtifact"
        ) as mock_artifact_class:
            mock_artifact = MagicMock()
            mock_artifact.name = "test-manifest-1.0.0+abc1234+uuid"
            mock_artifact_class.return_value = mock_artifact

            with patch.object(helper, "create_artifact") as mock_create:
                mock_create.return_value = mock_artifact
                with patch.object(helper, "upload_artifact") as mock_upload:
                    with patch(
                        "mender_docker_lifecycle_helper.helper.ArtifactMetadata"
                    ) as mock_metadata_class:
                        mock_metadata = MagicMock()
                        mock_metadata_class.return_value = mock_metadata
                        mock_metadata.to_dict.return_value = {
                            "version": "1.0.0+abc1234",
                            "services": {},
                        }

                        with patch.object(
                            mock_artifact_class,
                            "gen_artifact_services",
                            return_value={
                                "server": {"image": {"ref": "test", "hash": "123"}}
                            },
                        ):
                            with patch(
                                "uuid.uuid4",
                                return_value=uuid.UUID(
                                    "12345678-1234-5678-1234-567812345678"
                                ),
                            ):
                                helper.prep_artifact()

                                # Version should be: previous_version + commit_sha + uuid
                                mock_context.logger.info.assert_any_call(
                                    "Preparing an artifact with the version 1.0.0+abc1234+12345678-1234-5678-1234-567812345678"
                                )

    def test_prep_artifact_with_deployment(self, mock_context):
        """Test prep_artifact creates deployment when device_group is set."""
        mock_context.release = True
        mock_context.repo_version = "1.0.0"
        mock_context.device_group = "test-group"
        mock_context.logger = MagicMock()
        mock_context.cache = True

        helper = LifecycleHelper.__new__(LifecycleHelper)
        helper.context = mock_context

        with patch(
            "mender_docker_lifecycle_helper.helper.LifecycleHelperArtifact"
        ) as mock_artifact_class:
            mock_artifact = MagicMock()
            mock_artifact.name = "test-manifest-1.0.0"
            mock_artifact_class.return_value = mock_artifact

            with patch.object(helper, "create_artifact") as mock_create:
                mock_create.return_value = mock_artifact
                with patch.object(helper, "upload_artifact") as mock_upload:
                    with patch.object(helper, "deploy_artifact") as mock_deploy:
                        with patch(
                            "mender_docker_lifecycle_helper.helper.ArtifactMetadata"
                        ) as mock_metadata_class:
                            mock_metadata = MagicMock()
                            mock_metadata_class.return_value = mock_metadata
                            mock_metadata.to_dict.return_value = {
                                "version": "1.0.0",
                                "services": {},
                            }

                            with patch.object(
                                mock_artifact_class,
                                "gen_artifact_services",
                                return_value={
                                    "server": {"image": {"ref": "test", "hash": "123"}}
                                },
                            ):
                                with patch.object(
                                    mock_metadata, "to_file"
                                ) as mock_to_file:
                                    helper.prep_artifact()

                                    mock_deploy.assert_called_once_with(mock_artifact)
                                    mock_to_file.assert_called_once_with(
                                        mock_context.cache_artifact_metadata_file
                                    )
                                    mock_context.logger.info.assert_any_call(
                                        f"Artifact {mock_artifact.name} successfully processed!"
                                    )

    def test_prep_artifact_no_deployment_without_device_group(self, mock_context):
        """Test prep_artifact skips deployment when device_group is None."""
        mock_context.release = True
        mock_context.repo_version = "1.0.0"
        mock_context.device_group = None
        mock_context.logger = MagicMock()

        helper = LifecycleHelper.__new__(LifecycleHelper)
        helper.context = mock_context

        with patch(
            "mender_docker_lifecycle_helper.helper.LifecycleHelperArtifact"
        ) as mock_artifact_class:
            mock_artifact = MagicMock()
            mock_artifact.name = "test-manifest-1.0.0"
            mock_artifact_class.return_value = mock_artifact

            with patch.object(helper, "create_artifact") as mock_create:
                mock_create.return_value = mock_artifact
                with patch.object(helper, "upload_artifact") as mock_upload:
                    with patch.object(helper, "deploy_artifact") as mock_deploy:
                        with patch(
                            "mender_docker_lifecycle_helper.helper.ArtifactMetadata"
                        ) as mock_metadata_class:
                            mock_metadata = MagicMock()
                            mock_metadata_class.return_value = mock_metadata
                            mock_metadata.to_dict.return_value = {
                                "version": "1.0.0",
                                "services": {},
                            }

                            with patch.object(
                                mock_artifact_class,
                                "gen_artifact_services",
                                return_value={
                                    "server": {"image": {"ref": "test", "hash": "123"}}
                                },
                            ):
                                helper.prep_artifact()

                                mock_deploy.assert_not_called()
                                mock_context.logger.debug.assert_any_call(
                                    "No device group set; skipping deployment creation."
                                )
