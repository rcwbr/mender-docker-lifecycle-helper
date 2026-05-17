import json
import logging
import pytest
import tarfile
import time
import yaml

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mender_docker_lifecycle_helper.artifact import (
    LifecycleHelperArtifact,
    ManifestContentException,
)
from mender_docker_lifecycle_helper.utils.deep_delta import ImageDeltaException
from mender_docker_lifecycle_helper.utils.image_cache import ImageCache

logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)


example_artifact_metadata = SimpleNamespace(
    services={"service": {"image": {"ref": "busybox", "hash": "abcd1234"}}},
    to_dict=lambda: "none",
)


class LifecycleHelperContextMock:
    def __init__(self, cache_path):
        self.logger = logger

        self.manifest_name = "app"
        self.platform = "linux/amd64"
        self.image_cache = ImageCache(cache_path / "images", platform=self.platform)
        self.mender_host = "https://hosted.mender.io"
        self.previous_artifact_metadata = SimpleNamespace(
            services={
                "serviceA": {
                    "image": {
                        "ref": "busybox:1.37.0-glibc",
                        "hash": "3f9777e7e82e8591542f72b965ec7db7e8b3bdb59692976af1bb9b2850b05a4e",
                    }
                }
            },
            version="0.1.0",
        )
        self.version = "1.0.0"
        self.delta = True


class TestPrepDeltaImage:
    """Tests for the prep_delta_image function."""

    def test_prep_delta_image_integration(self, tmp_path):
        """Test that prep_delta_image works against real image refs and without mocking."""
        context_mock = LifecycleHelperContextMock(tmp_path / "cache")
        helper_artifact = LifecycleHelperArtifact(
            context_mock,
            "test",
            example_artifact_metadata,
            tmp_path / "artifact.mender",
        )
        artifact_image_path = tmp_path / "artifact" / "image"
        artifact_image_path.mkdir(parents=True)
        helper_artifact.prep_delta_image(
            "serviceA",
            {
                "ref": "busybox:1.37.0-musl",
                "hash": "19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138",
            },
            artifact_image_path,
        )
        assert (artifact_image_path / "deep_delta").exists()
        assert (
            artifact_image_path / "sums-current.txt"
        ).read_text() == "3f9777e7e82e8591542f72b965ec7db7e8b3bdb59692976af1bb9b2850b05a4e"
        assert (
            artifact_image_path / "url-current.txt"
        ).read_text() == "busybox:1.37.0-glibc"
        assert (artifact_image_path / "image.img").exists()
        image_extract_path = artifact_image_path / "image-extract"
        with tarfile.open(artifact_image_path / "image.img", "r") as tar:
            tar.extractall(image_extract_path, filter="tar")
        assert (image_extract_path / "index.json").exists()
        assert (image_extract_path / "oci-layout").exists()
        # TODO examine more of the tar contents


class TestPrepImage:
    """Tests for the prep_image function."""

    def test_prep_image_integration(self, tmp_path):
        """Test that prep_image works against real image refs and without mocking."""
        context_mock = LifecycleHelperContextMock(tmp_path / "cache")
        helper_artifact = LifecycleHelperArtifact(
            context_mock,
            "test",
            example_artifact_metadata,
            tmp_path / "artifact.mender",
        )
        artifact_images_path = tmp_path / "artifact"
        artifact_images_path.mkdir()
        helper_artifact.prep_image(
            "serviceA",
            {
                "ref": "busybox:1.37.0-musl",
                "hash": "19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138",
            },
            artifact_images_path,
        )
        artifact_image_path = (
            artifact_images_path
            / "19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138"
        )
        assert (artifact_image_path / "deep_delta").exists()
        assert (
            artifact_image_path / "url-current.txt"
        ).read_text() == "busybox:1.37.0-glibc"
        assert (
            artifact_image_path / "sums-current.txt"
        ).read_text() == "3f9777e7e82e8591542f72b965ec7db7e8b3bdb59692976af1bb9b2850b05a4e"
        assert (
            artifact_image_path / "url-new.txt"
        ).read_text() == "busybox:1.37.0-musl"
        assert (
            artifact_image_path / "sums-new.txt"
        ).read_text() == "19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138"
        assert (artifact_image_path / "image.img").exists()
        # TODO open tar and verify contents

    def test_prep_image_raises_manifest_content_exception_on_ref_mismatch(
        self, tmp_path
    ):
        """Test that prep_image raises ManifestContentException when prepared image ref doesn't match."""

        context_mock = MagicMock()
        context_mock.logger = logger
        context_mock.delta = False
        context_mock.previous_artifact_metadata = SimpleNamespace(
            services={}, version="1.0.0"
        )
        context_mock.manifest_name = "test"
        context_mock.platform = "linux/amd64"
        context_mock.image_cache = MagicMock()

        # Create a pre-prepared image directory with conflicting metadata
        artifact_images_path = tmp_path / "artifact"
        artifact_images_path.mkdir()
        image_dir = (
            artifact_images_path
            / "hash11111111111111111111111111111111111111111111111111"
        )
        image_dir.mkdir()
        (image_dir / "sums-new.txt").write_text(
            "hash11111111111111111111111111111111111111111111111111"
        )
        (image_dir / "url-new.txt").write_text("busybox:old-ref")

        helper_artifact = LifecycleHelperArtifact(
            context_mock,
            "test",
            SimpleNamespace(
                services={
                    "serviceA": {
                        "image": {
                            "ref": "busybox:new-ref",
                            "hash": "hash11111111111111111111111111111111111111111111111111",
                        }
                    }
                },
                to_dict=lambda: "none",
            ),
            tmp_path / "artifact.mender",
        )

        # Should raise because the ref doesn't match
        with pytest.raises(ManifestContentException) as exc_info:
            helper_artifact.prep_image(
                "serviceA",
                {
                    "ref": "busybox:new-ref",
                    "hash": "hash11111111111111111111111111111111111111111111111111",
                },
                artifact_images_path,
            )

        assert "could not be prepared" in str(exc_info.value)
        assert "already assigned to" in str(exc_info.value)

    def test_prep_image_raises_manifest_content_exception_delta_vs_nondelta(
        self, tmp_path
    ):
        """Test that prep_image raises ManifestContentException when delta req conflicts with existing non-delta."""

        context_mock = MagicMock()
        context_mock.logger = logger
        context_mock.delta = True  # Now we want a delta
        context_mock.previous_artifact_metadata = SimpleNamespace(
            services={
                "serviceA": {
                    "image": {
                        "ref": "busybox:old",
                        "hash": "oldhash00000000000000000000000000000000000000000000000000",
                    }
                }
            },
            version="1.0.0",
        )
        context_mock.manifest_name = "test"
        context_mock.platform = "linux/amd64"
        context_mock.image_cache = MagicMock()

        # Create a pre-prepared image directory WITHOUT deep_delta (non-delta)
        artifact_images_path = tmp_path / "artifact"
        artifact_images_path.mkdir()
        image_dir = (
            artifact_images_path
            / "hash11111111111111111111111111111111111111111111111111"
        )
        image_dir.mkdir()
        (image_dir / "sums-new.txt").write_text(
            "hash11111111111111111111111111111111111111111111111111"
        )
        (image_dir / "url-new.txt").write_text("busybox:new-ref")
        # Note: NO deep_delta file - this is a non-delta prepared image

        helper_artifact = LifecycleHelperArtifact(
            context_mock,
            "test",
            SimpleNamespace(
                services={
                    "serviceB": {
                        "image": {
                            "ref": "busybox:new-ref",
                            "hash": "hash11111111111111111111111111111111111111111111111111",
                        }
                    }
                },
                to_dict=lambda: "none",
            ),
            tmp_path / "artifact.mender",
        )

        # Should raise because we want delta but it's not a delta
        with pytest.raises(ManifestContentException) as exc_info:
            helper_artifact.prep_image(
                "serviceB",
                {
                    "ref": "busybox:new-ref",
                    "hash": "hash11111111111111111111111111111111111111111111111111",
                },
                artifact_images_path,
            )

        assert "could not be prepared for service serviceB as a delta" in str(
            exc_info.value
        )
        assert "already assigned to" in str(exc_info.value)

    def test_prep_image_raises_manifest_content_exception_delta_previous_hash_mismatch(
        self, tmp_path
    ):
        """Test that prep_image raises ManifestContentException when delta previous hash doesn't match."""
        context_mock = MagicMock()
        context_mock.logger = logger
        context_mock.delta = True
        context_mock.previous_artifact_metadata = SimpleNamespace(
            services={
                "serviceA": {
                    "image": {
                        "ref": "busybox:oldA",
                        "hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    }
                },
                "serviceB": {
                    "image": {
                        "ref": "busybox:oldB",
                        "hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    }
                },
            },
            version="1.0.0",
        )
        context_mock.manifest_name = "test"
        context_mock.platform = "linux/amd64"
        context_mock.image_cache = MagicMock()

        # Create a pre-prepared image directory WITH deep_delta for serviceA (from aaa...)
        artifact_images_path = tmp_path / "artifact"
        artifact_images_path.mkdir()
        image_dir = (
            artifact_images_path
            / "newhash1111111111111111111111111111111111111111111111"
        )
        image_dir.mkdir()
        (image_dir / "sums-new.txt").write_text(
            "newhash1111111111111111111111111111111111111111111111"
        )
        (image_dir / "url-new.txt").write_text("busybox:new")
        (image_dir / "deep_delta").touch()
        (image_dir / "sums-current.txt").write_text(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )  # Previous hash for serviceA
        (image_dir / "url-current.txt").write_text("busybox:oldA")

        helper_artifact = LifecycleHelperArtifact(
            context_mock,
            "test",
            SimpleNamespace(
                services={
                    "serviceB": {
                        "image": {
                            "ref": "busybox:new",
                            "hash": "newhash1111111111111111111111111111111111111111111111",
                        }
                    }
                },
                to_dict=lambda: "none",
            ),
            tmp_path / "artifact.mender",
        )

        # Should raise because previous hash for serviceB (bbb...) doesn't match prepared (aaa...)
        with pytest.raises(ManifestContentException) as exc_info:
            helper_artifact.prep_image(
                "serviceB",
                {
                    "ref": "busybox:new",
                    "hash": "newhash1111111111111111111111111111111111111111111111",
                },
                artifact_images_path,
            )

        assert "could not be prepared for service serviceB as a delta from" in str(
            exc_info.value
        )
        assert "as it already exists as a delta from" in str(exc_info.value)

    def test_prep_image_short_circuits_on_matching_metadata_nondelta(self, tmp_path):
        """Test that prep_image returns early when metadata matches and not a delta update."""

        context_mock = MagicMock()
        context_mock.logger = logger
        context_mock.delta = False  # Non-delta context
        context_mock.previous_artifact_metadata = SimpleNamespace(
            services={}, version="1.0.0"
        )
        context_mock.manifest_name = "test"
        context_mock.platform = "linux/amd64"
        context_mock.image_cache = MagicMock()

        # Create a pre-prepared image directory with matching metadata
        artifact_images_path = tmp_path / "artifact"
        artifact_images_path.mkdir()
        image_dir = (
            artifact_images_path
            / "hash11111111111111111111111111111111111111111111111111"
        )
        image_dir.mkdir()
        (image_dir / "sums-new.txt").write_text(
            "hash11111111111111111111111111111111111111111111111111"
        )
        (image_dir / "url-new.txt").write_text("busybox:ref")

        helper_artifact = LifecycleHelperArtifact(
            context_mock,
            "test",
            SimpleNamespace(
                services={
                    "serviceA": {
                        "image": {
                            "ref": "busybox:ref",
                            "hash": "hash11111111111111111111111111111111111111111111111111",
                        }
                    }
                },
                to_dict=lambda: "none",
            ),
            tmp_path / "artifact.mender",
        )

        # Store original mtime
        original_mtime = (image_dir / "sums-new.txt").stat().st_mtime
        time.sleep(0.1)

        # Should short-circuit - no exception, no new files
        helper_artifact.prep_image(
            "serviceA",
            {
                "ref": "busybox:ref",
                "hash": "hash11111111111111111111111111111111111111111111111111",
            },
            artifact_images_path,
        )

        # Verify image_cache methods were not called (short-circuit)
        context_mock.image_cache.assert_not_called()
        context_mock.image_cache.save_cache_image.assert_not_called()

        # Verify mtime didn't change
        assert (image_dir / "sums-new.txt").stat().st_mtime == original_mtime

    def test_prep_image_short_circuits_on_matching_metadata_with_delta(self, tmp_path):
        """Test that prep_image returns early when metadata matches and delta checks pass."""

        context_mock = MagicMock()
        context_mock.logger = logger
        context_mock.delta = True
        context_mock.previous_artifact_metadata = SimpleNamespace(
            services={
                "serviceA": {
                    "image": {
                        "ref": "busybox:old",
                        "hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    }
                },
                "serviceB": {
                    "image": {
                        "ref": "busybox:old",
                        "hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    }
                },
            },
            version="1.0.0",
        )
        context_mock.manifest_name = "test"
        context_mock.platform = "linux/amd64"
        context_mock.image_cache = MagicMock()

        # Create a pre-prepared image directory WITH deep_delta for same previous hash
        artifact_images_path = tmp_path / "artifact"
        artifact_images_path.mkdir()
        image_dir = (
            artifact_images_path
            / "newhash1111111111111111111111111111111111111111111111"
        )
        image_dir.mkdir()
        (image_dir / "sums-new.txt").write_text(
            "newhash1111111111111111111111111111111111111111111111"
        )
        (image_dir / "url-new.txt").write_text("busybox:new")
        (image_dir / "deep_delta").touch()
        (image_dir / "sums-current.txt").write_text(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )  # Same previous hash for both services
        (image_dir / "url-current.txt").write_text("busybox:old")

        helper_artifact = LifecycleHelperArtifact(
            context_mock,
            "test",
            SimpleNamespace(
                services={
                    "serviceB": {
                        "image": {
                            "ref": "busybox:new",
                            "hash": "newhash1111111111111111111111111111111111111111111111",
                        }
                    }
                },
                to_dict=lambda: "none",
            ),
            tmp_path / "artifact.mender",
        )

        original_mtime = (image_dir / "sums-new.txt").stat().st_mtime
        time.sleep(0.1)

        # Should short-circuit - same hash, same previous hash, delta=True but already prepared
        helper_artifact.prep_image(
            "serviceB",
            {
                "ref": "busybox:new",
                "hash": "newhash1111111111111111111111111111111111111111111111",
            },
            artifact_images_path,
        )

        # Verify image_cache.delta was not called (short-circuit)
        context_mock.image_cache.delta.assert_not_called()

        # Verify mtime didn't change
        assert (image_dir / "sums-new.txt").stat().st_mtime == original_mtime


class TestPrepImages:
    """Tests for the prep_images function."""

    def test_prep_images_integration(self, tmp_path):
        """Test that prep_images works against real image refs and without mocking."""
        context_mock = LifecycleHelperContextMock(tmp_path / "cache")
        helper_artifact = LifecycleHelperArtifact(
            context_mock,
            "test",
            SimpleNamespace(
                services={
                    "serviceA": {
                        "image": {
                            "ref": "busybox:1.37.0-musl",
                            "hash": "19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138",
                        }
                    }
                },
                to_dict=lambda: "none",
            ),
            tmp_path / "artifact.mender",
        )
        artifact_path = tmp_path / "artifact"
        artifact_path.mkdir()
        helper_artifact.prep_images(artifact_path, "images.tar.gz")
        artifact_images_file = artifact_path / "images.tar.gz"

        assert artifact_images_file.exists()
        with tarfile.open(artifact_images_file, "r") as tar:
            tar.extractall(path=artifact_path, filter="tar")

        artifact_image_path = (
            artifact_path
            / "images"
            / "19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138"
        )
        assert (artifact_image_path / "deep_delta").exists()
        assert (
            artifact_image_path / "sums-current.txt"
        ).read_text() == "3f9777e7e82e8591542f72b965ec7db7e8b3bdb59692976af1bb9b2850b05a4e"
        assert (
            artifact_image_path / "url-current.txt"
        ).read_text() == "busybox:1.37.0-glibc"
        assert (artifact_image_path / "image.img").exists()
        # TODO open tar and verify contents

    def test_prep_image_handles_image_delta_exception(self, tmp_path):
        """Test that prep_image handles ImageDeltaException from prep_delta_image."""

        context_mock = MagicMock()
        context_mock.delta = True
        context_mock.manifest_name = "test"
        context_mock.previous_artifact_metadata = MagicMock(
            services={
                "serviceA": {
                    "image": {"ref": "busybox:1.37.0-glibc", "hash": "old_hash"}
                }
            },
            version="1.0.0",
        )
        context_mock.logger = MagicMock()
        context_mock.platform = "linux/amd64"
        context_mock.cache_dir = tmp_path / "cache"
        context_mock.image_cache = MagicMock()

        # Mock prep_delta_image to raise ImageDeltaException
        with patch.object(
            context_mock.image_cache,
            "delta",
            side_effect=ImageDeltaException("Test delta exception"),
        ):
            helper_artifact = LifecycleHelperArtifact(
                context_mock,
                "test",
                MagicMock(
                    services={
                        "serviceA": {
                            "image": {"ref": "busybox:1.37.0-musl", "hash": "new_hash"}
                        }
                    }
                ),
                tmp_path / "artifact.mender",
            )

            artifact_path = tmp_path / "artifact"
            artifact_path.mkdir()

            # Should not raise - ImageDeltaException should be caught and logged
            helper_artifact.prep_image(
                "serviceA",
                {"ref": "busybox:1.37.0-musl", "hash": "new_hash"},
                artifact_path,
            )

            # Verify warning was logged
            assert context_mock.logger.warning.called


class TestPrepManifests:
    """Tests for the prep_manifests function."""

    def test_prep_manifests_simple(self, tmp_path):
        """Test that prep_manifests works against a simple manifest config."""
        manifest_content = {
            "services": {
                "serviceA": {"image": "busybox:1.37.0-musl", "ports": ["8080:80"]}
            }
        }
        context_mock = LifecycleHelperContextMock(tmp_path / "cache")
        context_mock.manifest_file = tmp_path / "docker-compose.yml"
        context_mock.manifest = manifest_content
        helper_artifact = LifecycleHelperArtifact(
            context_mock,
            "test",
            example_artifact_metadata,
            tmp_path / "artifact.mender",
        )
        artifact_path = tmp_path / "artifact"
        artifact_path.mkdir()
        helper_artifact.prep_manifests(artifact_path, "manifests.tar.gz")
        artifact_manifests_file = artifact_path / "manifests.tar.gz"

        assert artifact_manifests_file.exists()
        with tarfile.open(artifact_manifests_file, "r") as tar:
            tar.extractall(path=artifact_path, filter="tar")

        artifact_image_path = artifact_path / "manifests" / "docker-compose.yml"
        assert artifact_image_path.exists()
        with open(artifact_image_path, "r") as manifest:
            assert yaml.safe_load(manifest) == manifest_content


class TestPrepArtifactDir:
    """Tests for the prep_artifact_dir function."""

    def test_prep_artifact_dir_integration(self, tmp_path):
        """Test that prep_artifact_dir works against real image refs and without mocking."""
        # Create a proper context with only the fields needed by prep_artifact_dir
        context_mock = SimpleNamespace(
            logger=logger,
            previous_artifact_metadata=SimpleNamespace(
                services={
                    "serviceA": {
                        "image": {
                            "ref": "busybox:1.37.0-glibc",
                            "hash": "3f9777e7e82e8591542f72b965ec7db7e8b3bdb59692976af1bb9b2850b05a4e",
                        }
                    }
                },
                version="1.0.0",
            ),
            manifest_name="test",
            platform="linux/amd64",
            delta=True,
            manifest_file=(tmp_path / "docker-compose.yml"),
            manifest={"services": {"serviceA": {"image": "busybox:1.37.0-musl"}}},
            image_cache=ImageCache(
                tmp_path / "cache" / "images", platform="linux/amd64"
            ),
        )
        helper_artifact = LifecycleHelperArtifact(
            context_mock,
            "test",
            SimpleNamespace(
                version="0.0.0",
                services={
                    "serviceA": {
                        "image": {
                            "ref": "busybox:1.37.0-musl",
                            "hash": "19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138",
                        }
                    }
                },
                to_dict=lambda: "none",
            ),
            tmp_path / "artifact.mender",
        )
        artifact_path = tmp_path / "artifact"
        artifact_path.mkdir()
        helper_artifact.prep_artifact_dir(
            artifact_path, "images.tar.gz", "manifests.tar.gz", "metadata.json"
        )

        # Verify metadata file exists and has correct structure
        metadata_file = artifact_path / "metadata.json"
        assert metadata_file.exists()
        with open(metadata_file, "r") as f:
            metadata = json.load(f)
        assert metadata["application_name"] == "test"
        assert metadata["orchestrator"] == "docker-compose"
        assert metadata["platform"] == "linux/amd64"
        assert len(metadata["images"]) == 1

        # Verify images archive exists and has correct structure
        images_archive = artifact_path / "images.tar.gz"
        assert images_archive.exists()
        with tarfile.open(images_archive, "r") as tar:
            tar.extractall(path=artifact_path, filter="tar")

        # Verify the images directory structure
        images_dir = (
            artifact_path
            / "images"
            / "19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138"
        )
        assert images_dir.exists()
        assert (images_dir / "deep_delta").exists()
        assert (
            images_dir / "sums-current.txt"
        ).read_text() == "3f9777e7e82e8591542f72b965ec7db7e8b3bdb59692976af1bb9b2850b05a4e"
        assert (images_dir / "url-current.txt").read_text() == "busybox:1.37.0-glibc"
        assert (
            images_dir / "sums-new.txt"
        ).read_text() == "19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138"
        assert (images_dir / "url-new.txt").read_text() == "busybox:1.37.0-musl"
        assert (images_dir / "image.img").exists()

        # Verify manifests archive exists and has correct structure
        manifests_archive = artifact_path / "manifests.tar.gz"
        assert manifests_archive.exists()
        with tarfile.open(manifests_archive, "r") as tar:
            tar.extractall(path=artifact_path, filter="tar")

        # Verify the manifests directory structure
        manifests_file = artifact_path / "manifests" / "docker-compose.yml"
        assert manifests_file.exists()
        with open(manifests_file, "r") as manifest:
            assert yaml.safe_load(manifest) == {
                "services": {"serviceA": {"image": "busybox:1.37.0-musl"}}
            }


class TestGenArtifact:
    def test_gen_artifact_integration(self, tmp_path):
        context_mock = SimpleNamespace(
            temp_dir=(tmp_path / "cache"),
            device_type="virtual",
            delta=True,
            image_cache=ImageCache(
                tmp_path / "cache" / "images", platform="linux/amd64"
            ),
            logger=logger,
            manifest_name="test",
            manifest_file=(tmp_path / "docker-compose.yml"),
            manifest={"services": {"serviceA": {"image": "busybox:1.37.0-musl"}}},
            platform="linux/amd64",
            previous_artifact_metadata=SimpleNamespace(
                version="1.0.0",
                services={
                    "serviceA": {
                        "image": {
                            "ref": "busybox:1.37.0-glibc",
                            "hash": "3f9777e7e82e8591542f72b965ec7db7e8b3bdb59692976af1bb9b2850b05a4e",
                        }
                    }
                },
            ),
        )
        artifact_file = tmp_path / "artifact.mender"
        helper_artifact = LifecycleHelperArtifact(
            context_mock,
            "test",
            SimpleNamespace(
                version="2.0.0",
                services={
                    "serviceA": {
                        "image": {
                            "ref": "busybox:1.37.0-musl",
                            "hash": "19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138",
                        }
                    }
                },
                to_dict=lambda: "none",
            ),
            artifact_file,
        )
        helper_artifact.gen_artifact_file()

        artifact_extract_dir = tmp_path / "artifact_extract"
        with tarfile.open(artifact_file, "r") as artifact:
            artifact.extractall(path=artifact_extract_dir, filter="tar")
        assert (
            artifact_extract_dir / "version"
        ).read_text() == '{"format":"mender","version":3}'
        manifest_content = (artifact_extract_dir / "manifest").read_text()
        assert "  data/0000/images.tar.gz" in manifest_content
        assert "  data/0000/manifests.tar.gz" in manifest_content
        assert "  header.tar.gz" in manifest_content
        assert "  version" in manifest_content

        data_extract_dir = tmp_path / "data_extract"
        with tarfile.open(
            artifact_extract_dir / "data" / "0000.tar.gz", "r"
        ) as artifact:
            artifact.extractall(path=data_extract_dir, filter="tar")
        assert data_extract_dir / "images.tar.gz"
        assert data_extract_dir / "manifests.tar.gz"

        header_extract_dir = tmp_path / "header_extract"
        with tarfile.open(artifact_extract_dir / "header.tar.gz", "r") as artifact:
            artifact.extractall(path=header_extract_dir, filter="tar")
        assert (
            header_extract_dir / "header-info"
        ).read_text() == '{"payloads":[{"type":"app"}],"artifact_provides":{"artifact_name":"test"},"artifact_depends":{"device_type":["virtual"]}}'
        assert (
            header_extract_dir / "headers" / "0000" / "meta-data"
        ).read_text() == '{"application_name":"test","images":["19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138"],"orchestrator":"docker-compose","platform":"linux/amd64","version":"2.0.0"}'
        assert (
            header_extract_dir / "headers" / "0000" / "type-info"
        ).read_text() == '{"type":"app","artifact_depends":{"rootfs-image.test.version":"1.0.0"},"artifact_provides":{"rootfs-image.test.version":"2.0.0"},"clears_artifact_provides":["rootfs-image.test.*"]}'

    def test_gen_artifact_integration_dependency(self, tmp_path):
        context_mock = SimpleNamespace(
            temp_dir=(tmp_path / "cache"),
            device_type="virtual",
            delta=False,
            image_cache=ImageCache(
                tmp_path / "cache" / "images", platform="linux/amd64"
            ),
            logger=logger,
            manifest_name="test",
            manifest_file=(tmp_path / "docker-compose.yml"),
            manifest={
                "services": {
                    "serviceA": {
                        "image": "busybox:1.37.0-glibc",
                        "entrypoint": "sleep 1000",
                    }
                }
            },
            platform="linux/amd64",
        )
        artifact_file = Path(tmp_path / "artifact1.mender")
        helper_artifact = LifecycleHelperArtifact(
            context_mock,
            "test",
            SimpleNamespace(
                version="0.0.0",
                services={
                    "serviceA": {
                        "image": {
                            "ref": "busybox:1.37.0-glibc",
                            "hash": "3f9777e7e82e8591542f72b965ec7db7e8b3bdb59692976af1bb9b2850b05a4e",
                        }
                    }
                },
                to_dict=lambda: "none",
            ),
            artifact_file,
        )
        helper_artifact.gen_artifact_file()

        context_mock.delta = True
        context_mock.previous_artifact_metadata = SimpleNamespace(
            version="0.0.0",
            services={
                "serviceA": {
                    "image": {
                        "ref": "busybox:1.37.0-glibc",
                        "hash": "3f9777e7e82e8591542f72b965ec7db7e8b3bdb59692976af1bb9b2850b05a4e",
                    }
                }
            },
        )
        context_mock.manifest["services"]["serviceA"]["image"] = "busybox:1.37.0-musl"
        artifact_file = Path(tmp_path / "artifact2.mender")
        helper_artifact = LifecycleHelperArtifact(
            context_mock,
            "test",
            SimpleNamespace(
                version="0.1.0",
                services={
                    "serviceA": {
                        "image": {
                            "ref": "busybox:1.37.0-musl",
                            "hash": "19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138",
                        }
                    }
                },
                to_dict=lambda: "none",
            ),
            artifact_file,
        )
        helper_artifact.gen_artifact_file()


class TestGenArtifactServices:
    """Tests for the gen_artifact_services function"""

    def test_gen_artifact_services_default(self):
        """Test gen_artifact_services with default case (manifest image used)."""
        context = SimpleNamespace(
            service_files={},
            service_images={},
            manifest={
                "services": {
                    "service1": {"image": "busybox:latest"},
                    "service2": {"image": "nginx:1.0"},
                }
            },
            previous_artifact_metadata=SimpleNamespace(services={}),
            logger=logger,
            match_or_find_hash=lambda svc, ref: {
                "busybox:latest": "hash1",
                "nginx:1.0": "hash2",
            }[ref],
        )

        result = LifecycleHelperArtifact.gen_artifact_services(context)
        assert result == {
            "service1": {"image": {"ref": "busybox:latest", "hash": "hash1"}},
            "service2": {"image": {"ref": "nginx:1.0", "hash": "hash2"}},
        }

    def test_gen_artifact_services_service_files(self, tmp_path):
        """Test gen_artifact_services with service file override."""
        service_file_path = tmp_path / "service1.tar.gz"
        service_file_path.write_bytes(b"fake tar")

        context = SimpleNamespace(
            service_files={"service1": service_file_path},
            service_images={},
            manifest={
                "services": {
                    "service1": {"image": "busybox:latest"},
                }
            },
            previous_artifact_metadata=SimpleNamespace(services={}),
            logger=logger,
            image_cache=SimpleNamespace(
                extract_cache_file=lambda p: {"ref": "file_ref", "hash": "file_hash"}
            ),
            match_or_find_hash=lambda svc, ref: "old_hash",
        )

        result = LifecycleHelperArtifact.gen_artifact_services(context)
        assert result == {
            "service1": {"image": {"ref": "file_ref", "hash": "file_hash"}},
        }

    def test_gen_artifact_services_image_override(self):
        """Test gen_artifact_services with image override."""
        context = SimpleNamespace(
            service_files={},
            service_images={"service1": "custom_image:tag"},
            manifest={
                "services": {
                    "service1": {"image": "busybox:latest"},
                }
            },
            previous_artifact_metadata=SimpleNamespace(services={}),
            logger=logger,
            match_or_find_hash=lambda svc, ref: (
                "found_hash" if ref == "custom_image:tag" else "old_hash"
            ),
        )

        result = LifecycleHelperArtifact.gen_artifact_services(context)
        assert result == {
            "service1": {"image": {"ref": "custom_image:tag", "hash": "found_hash"}},
        }

    def test_gen_artifact_services_service_image_manifest_content_mismatch(self):
        """Test gen_artifact_services raises ManifestContentException when hash in service image metadata mismatches."""
        context = SimpleNamespace(
            service_files={},
            service_images={"service2": "busybox:not-latest"},
            manifest={
                "services": {
                    "service1": {"image": "busybox:latest"},
                }
            },
            previous_artifact_metadata=SimpleNamespace(services={}),
            logger=logging.getLogger(__name__),
            match_or_find_hash=lambda svc, ref: "found_hash",
        )

        context.delta = True
        context.manifest_name = "test"
        context.previous_artifact_metadata = SimpleNamespace(
            services={}, version="1.0.0"
        )

        with pytest.raises(ManifestContentException):
            LifecycleHelperArtifact.gen_artifact_services(context)

    def test_gen_artifact_services_service_file_manifest_content_mismatch(self):
        """Test gen_artifact_services raises ManifestContentException when hash in service file metadata mismatches."""
        context = SimpleNamespace(
            service_files={"service3": "this-file"},
            service_images={},
            manifest={
                "services": {
                    "service1": {"image": "busybox:latest"},
                }
            },
            previous_artifact_metadata=SimpleNamespace(services={}),
            logger=logging.getLogger(__name__),
            match_or_find_hash=lambda svc, ref: "found_hash",
        )

        context.delta = True
        context.manifest_name = "test"
        context.previous_artifact_metadata = SimpleNamespace(
            services={}, version="1.0.0"
        )

        with pytest.raises(ManifestContentException):
            LifecycleHelperArtifact.gen_artifact_services(context)
