import logging
import pytest
import subprocess
import tarfile

from unittest.mock import patch

from mender_docker_lifecycle_helper.utils.container_utils import (
    _image_ref_hash_or_tag,
    _split_image_ref,
    get_image_hash,
    save_registry_image_to_file,
    save_local_image_to_file,
    save_image_to_file,
    ImageNotFoundException,
    ImageRefHashMismatchException,
    REF_NOT_FOUND_DAEMON_LOG,
    REF_NOT_FOUND_REGISTRY_LOG,
    HASH_PREFIX,
)


class TestSplitImageRef:
    """Tests for the container_utils _split_image_ref method"""

    def test_split_image_ref_registry_image_tag(self):
        """Test _split_image_ref with just a registry/image:tag."""
        registry, tag, hash_val = _split_image_ref("my-registry.com/my-image:latest")
        assert registry == "my-registry.com/my-image"
        assert tag == "latest"
        assert hash_val is None

    def test_split_image_ref_registry_image_only(self):
        """Test _split_image_ref with just a registry/image (no tag)."""
        registry, tag, hash_val = _split_image_ref("my-registry.com/my-image")
        assert registry == "my-registry.com/my-image"
        assert tag is None
        assert hash_val is None

    def test_split_image_ref_digest_only(self):
        """Test _split_image_ref with digest only."""
        registry, tag, hash_val = _split_image_ref(
            "my-registry.com/my-image@sha256:1234567890abcdef"
        )
        assert registry == "my-registry.com/my-image"
        assert tag is None
        assert hash_val == "1234567890abcdef"

    def test_split_image_ref_registry_image_tag_and_digest(self):
        """Test _split_image_ref with registry/image:tag and digest."""
        registry, tag, hash_val = _split_image_ref(
            "my-registry.com/my-image:latest@sha256:1234567890abcdef"
        )
        assert registry == "my-registry.com/my-image"
        assert tag == "latest"
        assert hash_val == "1234567890abcdef"

    def test_split_image_ref_image_tag_only(self):
        """Test _split_image_ref with just image:tag (no hash)."""
        registry, tag, hash_val = _split_image_ref("my-image:latest")
        assert registry == "my-image"
        assert tag == "latest"
        assert hash_val is None

    def test_split_image_ref_image_only(self):
        """Test _split_image_ref with just image (no registry, no tag)."""
        registry, tag, hash_val = _split_image_ref("my-image")
        assert registry == "my-image"
        assert tag is None
        assert hash_val is None

    def test_split_image_ref_image_digest_only(self):
        """Test _split_image_ref with image@digest (no registry, no tag)."""
        registry, tag, hash_val = _split_image_ref("my-image@sha256:1234567890abcdef")
        assert registry == "my-image"
        assert tag is None
        assert hash_val == "1234567890abcdef"

    def test_split_image_ref_registry_port_with_tag(self):
        """Test _split_image_ref with registry port and tag."""
        registry, tag, hash_val = _split_image_ref(
            "my-registry.com:5000/my-image:latest"
        )
        assert registry == "my-registry.com:5000/my-image"
        assert tag == "latest"
        assert hash_val is None

    def test_split_image_ref_registry_port_with_digest(self):
        """Test _split_image_ref with registry port and digest."""
        registry, tag, hash_val = _split_image_ref(
            "my-registry.com:5000/my-image@sha256:1234567890abcdef"
        )
        assert registry == "my-registry.com:5000/my-image"
        assert tag is None
        assert hash_val == "1234567890abcdef"

    def test_split_image_ref_registry_port_with_tag_and_digest(self):
        """Test _split_image_ref with registry port, tag, and digest."""
        registry, tag, hash_val = _split_image_ref(
            "my-registry.com:5000/my-image:latest@sha256:1234567890abcdef"
        )
        assert registry == "my-registry.com:5000/my-image"
        assert tag == "latest"
        assert hash_val == "1234567890abcdef"


class TestImageRefHashOrTag:
    """Tests for the container_utils _image_ref_hash_or_tag method"""

    def test_image_ref_hash_or_tag_with_hash(self):
        """Test _image_ref_hash_or_tag with tag and hash provided (should prefer hash)."""
        result = _image_ref_hash_or_tag(
            "my-registry.com/my-image", "latest", "1234567890abcdef"
        )
        assert result == "my-registry.com/my-image@sha256:1234567890abcdef"

    def test_image_ref_hash_or_tag_with_hash(self):
        """Test _image_ref_hash_or_tag with hash provided (should prefer hash)."""
        result = _image_ref_hash_or_tag(
            "my-registry.com/my-image", None, "1234567890abcdef"
        )
        assert result == "my-registry.com/my-image@sha256:1234567890abcdef"

    def test_image_ref_hash_or_tag_with_tag(self):
        """Test _image_ref_hash_or_tag with no hash but tag provided (should use tag)."""
        result = _image_ref_hash_or_tag("my-registry.com/my-image", "latest", None)
        assert result == "my-registry.com/my-image:latest"

    def test_image_ref_hash_or_tag_neither(self):
        """Test _image_ref_hash_or_tag with neither hash nor tag (should return just registry)."""
        result = _image_ref_hash_or_tag("my-registry.com/my-image", None, None)
        assert result == "my-registry.com/my-image"

    def test_image_ref_hash_or_tag_empty_registry_with_tag(self):
        """Test _image_ref_hash_or_tag with empty registry and tag provided."""
        result = _image_ref_hash_or_tag("", "latest", None)
        assert result == ":latest"

    def test_image_ref_hash_or_tag_empty_registry_with_hash(self):
        """Test _image_ref_hash_or_tag with empty registry and hash provided."""
        result = _image_ref_hash_or_tag("", None, "1234567890abcdef")
        assert result == "@sha256:1234567890abcdef"


class TestSaveRegistryImageToFile:
    """Tests for the container_utils save_registry_image_to_file method"""

    def test_save_registry_image_to_file_success(self, tmp_path):
        """Test that save_registry_image_to_file calls skopeo with correct arguments."""
        file_path = tmp_path / "image.tar"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            save_registry_image_to_file("my-registry.com/my-image:latest", file_path)

            mock_run.assert_called_once_with(
                f"skopeo copy docker://my-registry.com/my-image:latest oci-archive:{file_path}".split(
                    " "
                ),
                capture_output=True,
                check=True,
            )

    def test_save_registry_image_to_file_success_with_platform(self, tmp_path):
        """Test that save_registry_image_to_file calls skopeo with platform arguments."""
        file_path = tmp_path / "image.tar"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            save_registry_image_to_file(
                "my-registry.com/my-image:latest", file_path, "linux/amd64"
            )

            mock_run.assert_called_once_with(
                f"skopeo copy --override-os linux --override-arch amd64 docker://my-registry.com/my-image:latest oci-archive:{file_path}".split(
                    " "
                ),
                capture_output=True,
                check=True,
            )

    def test_save_registry_image_to_file_success_with_platform_only_os(self, tmp_path):
        """Test that save_registry_image_to_file calls skopeo with only os override."""
        file_path = tmp_path / "image.tar"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            save_registry_image_to_file(
                "my-registry.com/my-image:latest", file_path, "linux"
            )

            mock_run.assert_called_once_with(
                f"skopeo copy --override-os linux docker://my-registry.com/my-image:latest oci-archive:{file_path}".split(
                    " "
                ),
                capture_output=True,
                check=True,
            )

    def test_save_registry_image_to_file_success_with_platform_and_variant(
        self, tmp_path
    ):
        """Test that save_registry_image_to_file calls skopeo with platform and variant arguments."""
        file_path = tmp_path / "image.tar"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            save_registry_image_to_file(
                "my-registry.com/my-image:latest", file_path, "linux/arm/v7"
            )

            mock_run.assert_called_once_with(
                f"skopeo copy --override-os linux --override-arch arm --override-variant v7 docker://my-registry.com/my-image:latest oci-archive:{file_path}".split(
                    " "
                ),
                capture_output=True,
                check=True,
            )

    def test_save_registry_image_to_file_not_found(self, tmp_path):
        """Test that save_registry_image_to_file raises ImageNotFoundException when image not found in registry."""
        image_ref = "my-registry.com/my-image:latest"
        file_path = tmp_path / "image.tar"

        with patch("subprocess.run") as mock_run:
            error = subprocess.CalledProcessError(1, "skopeo")
            error.stderr = f"some error output\n{REF_NOT_FOUND_REGISTRY_LOG}\nmore text"
            mock_run.side_effect = error

            with pytest.raises(ImageNotFoundException) as exc_info:
                save_registry_image_to_file(image_ref, file_path)

            assert f"Ref {image_ref} not found in registry." in str(exc_info.value)

    def test_save_registry_image_to_file_other_error(self, tmp_path):
        """Test that save_registry_image_to_file raises CalledProcessError for non-not-found errors."""
        image_ref = "my-registry.com/my-image:latest"
        file_path = tmp_path / "image.tar"

        with patch("subprocess.run") as mock_run:
            error = subprocess.CalledProcessError(1, "skopeo")
            error.stderr = "some random unrelated error"
            mock_run.side_effect = error

            # save_registry_image_to_file now raises any unmatched CalledProcessError
            with pytest.raises(subprocess.SubprocessError):
                save_registry_image_to_file(image_ref, file_path)


class TestSaveLocalImageToFile:
    """Tests for the container_utils save_local_image_to_file method"""

    def test_save_local_image_to_file_success(self, tmp_path):
        """Test that save_local_image_to_file calls skopeo with correct arguments."""
        file_path = tmp_path / "image.tar"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            save_local_image_to_file("1234567890abcdef", file_path)

            mock_run.assert_called_once_with(
                f"skopeo copy docker-daemon:sha256:1234567890abcdef oci-archive:{file_path}".split(
                    " "
                ),
                capture_output=True,
                check=True,
            )

    def test_save_local_image_to_file_not_found(self, tmp_path):
        """Test that save_local_image_to_file raises ImageNotFoundException when image not found in local daemon."""
        with patch("subprocess.run") as mock_run:
            error = subprocess.CalledProcessError(1, "skopeo")
            error.stderr = f"some error\n{REF_NOT_FOUND_DAEMON_LOG}\n"
            mock_run.side_effect = error

            with pytest.raises(ImageNotFoundException) as exc_info:
                save_local_image_to_file("1234567890abcdef", tmp_path / "image.tar")

            assert "Hash 1234567890abcdef not found in local daemon." == str(
                exc_info.value
            )

    def test_save_local_image_to_file_other_error(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            error = subprocess.CalledProcessError(1, "skopeo")
            error.stderr = "unrelated error"
            mock_run.side_effect = error

            # save_local_image_to_file now raises any unmatched CalledProcessError
            with pytest.raises(subprocess.CalledProcessError):
                save_local_image_to_file("1234567890abcdef", tmp_path / "image.tar")


class TestSaveImageToFile:
    """Tests for the container_utils save_image_to_file method"""

    def test_save_image_to_file_hash_mismatch(self, tmp_path):
        """Test that save_image_to_file raises ImageRefHashMismatchException when ref hash doesn't match provided hash."""
        image = {"ref": "my-image@sha256:wronghash", "hash": "1234567890abcdef"}
        file_path = tmp_path / "image.tar"

        with pytest.raises(ImageRefHashMismatchException) as exc_info:
            save_image_to_file(image, file_path)

        assert (
            "Specified hash 1234567890abcdef does not match hash embedded in ref my-image@sha256:wronghash."
            == str(exc_info.value)
        )

    def test_save_image_to_file_local_success(self, tmp_path):
        """Test that save_image_to_file calls save_local_image_to_file when ref has no hash prefix."""
        image = {"ref": "my-image", "hash": "1234567890abcdef"}
        file_path = tmp_path / "image.tar"

        with patch(
            "mender_docker_lifecycle_helper.utils.container_utils.save_local_image_to_file"
        ) as mock_local:
            with patch(
                "mender_docker_lifecycle_helper.utils.container_utils.save_registry_image_to_file"
            ) as mock_registry:
                save_image_to_file(image, file_path)

                mock_local.assert_called_once_with(image["hash"], file_path)
                mock_registry.assert_not_called()

    def test_save_image_to_file_local_success_with_hash_in_ref(self, tmp_path):
        """Test that save_image_to_file calls save_local_image_to_file when ref already contains hash."""
        image = {"ref": "my-image@sha256:1234567890abcdef", "hash": "1234567890abcdef"}
        file_path = tmp_path / "image.tar"

        with patch(
            "mender_docker_lifecycle_helper.utils.container_utils.save_local_image_to_file"
        ) as mock_local:
            with patch(
                "mender_docker_lifecycle_helper.utils.container_utils.save_registry_image_to_file"
            ) as mock_registry:
                save_image_to_file(image, file_path)

                mock_local.assert_called_once_with(image["hash"], file_path)
                mock_registry.assert_not_called()

    def test_save_image_to_file_registry_fallback_success(self, tmp_path):
        """Test that save_image_to_file falls back to registry when local save fails and ref has no hash prefix."""
        image = {"ref": "my-image", "hash": "1234567890abcdef"}
        file_path = tmp_path / "image.tar"

        with patch(
            "mender_docker_lifecycle_helper.utils.container_utils.save_local_image_to_file"
        ) as mock_local:
            with patch(
                "mender_docker_lifecycle_helper.utils.container_utils.save_registry_image_to_file"
            ) as mock_registry:
                mock_local.side_effect = ImageNotFoundException("local fail")

                save_image_to_file(image, file_path)

                mock_local.assert_called_once_with(image["hash"], file_path)
                # When ref has no hash prefix, the registry fallback appends the hash to the ref
                # The ref here is "my-image" so appending "sha256:..." gives "my-image@sha256:..."
                mock_registry.assert_called_once_with(
                    "my-image@sha256:1234567890abcdef", file_path, None
                )

    def test_save_image_to_file_registry_fallback_success_hash_in_ref(self, tmp_path):
        """Test that save_image_to_file falls back to registry when local save fails and ref already contains hash."""
        image = {"ref": "my-image@sha256:1234567890abcdef", "hash": "1234567890abcdef"}
        file_path = tmp_path / "image.tar"

        with patch(
            "mender_docker_lifecycle_helper.utils.container_utils.save_local_image_to_file"
        ) as mock_local:
            with patch(
                "mender_docker_lifecycle_helper.utils.container_utils.save_registry_image_to_file"
            ) as mock_registry:
                mock_local.side_effect = ImageNotFoundException("local fail")

                save_image_to_file(image, file_path)

                mock_local.assert_called_once_with(image["hash"], file_path)
                # If REF_HASH_PREFIX is already in image_ref, it does not append the hash, but uses the original image_ref
                mock_registry.assert_called_once_with(
                    "my-image@sha256:1234567890abcdef", file_path, None
                )

    def test_save_image_to_file_registry_fallback_success_hash_in_ref_with_platform(
        self, tmp_path
    ):
        """Test that save_image_to_file passes platform to registry on fallback with hash in ref."""
        image = {"ref": "my-image@sha256:1234567890abcdef", "hash": "1234567890abcdef"}
        file_path = tmp_path / "image.tar"

        with patch(
            "mender_docker_lifecycle_helper.utils.container_utils.save_local_image_to_file"
        ) as mock_local:
            with patch(
                "mender_docker_lifecycle_helper.utils.container_utils.save_registry_image_to_file"
            ) as mock_registry:
                mock_local.side_effect = ImageNotFoundException("local fail")

                save_image_to_file(image, file_path, "linux/amd64")

                mock_local.assert_called_once_with(image["hash"], file_path)
                mock_registry.assert_called_once_with(
                    "my-image@sha256:1234567890abcdef", file_path, "linux/amd64"
                )

    def test_save_image_to_file_both_fail(self, tmp_path):
        """Test that save_image_to_file raises ImageNotFoundException when both local and registry saves fail."""
        image = {"ref": "my-image", "hash": "1234567890abcdef"}
        file_path = tmp_path / "image.tar"

        with patch(
            "mender_docker_lifecycle_helper.utils.container_utils.save_local_image_to_file"
        ) as mock_local:
            with patch(
                "mender_docker_lifecycle_helper.utils.container_utils.save_registry_image_to_file"
            ) as mock_registry:
                mock_local.side_effect = ImageNotFoundException("local fail")
                mock_registry.side_effect = ImageNotFoundException("registry fail")

                with pytest.raises(ImageNotFoundException) as exc_info:
                    save_image_to_file(image, file_path)

                # Verify the exact exception message includes the modified ref
                assert (
                    str(exc_info.value)
                    == "Image with ref my-image@sha256:1234567890abcdef not found in local daemon or remote registry"
                )

    def test_save_image_to_file_propagates_other_exceptions_from_local(self, tmp_path):
        """Test that non-ImageNotFoundException exceptions from save_local_image_to_file propagate up."""
        image = {"ref": "my-image", "hash": "1234567890abcdef"}
        file_path = tmp_path / "image.tar"

        with patch(
            "mender_docker_lifecycle_helper.utils.container_utils.save_local_image_to_file"
        ) as mock_local:
            with patch(
                "mender_docker_lifecycle_helper.utils.container_utils.save_registry_image_to_file"
            ) as mock_registry:
                # Simulate an unexpected error (e.g., permission error)
                mock_local.side_effect = PermissionError("Cannot access local daemon")
                mock_registry.side_effect = ImageNotFoundException("registry fail")

                # The PermissionError should propagate up, not be caught
                with pytest.raises(PermissionError, match="Cannot access local daemon"):
                    save_image_to_file(image, file_path)

                mock_local.assert_called_once()
                mock_registry.assert_not_called()  # Should not fall back to registry on non-ImageNotFoundException

    def test_save_image_to_file_propagates_other_exceptions_from_registry(
        self, tmp_path
    ):
        """Test that non-ImageNotFoundException exceptions from save_registry_image_to_file propagate up."""
        image = {"ref": "my-image", "hash": "1234567890abcdef"}
        file_path = tmp_path / "image.tar"

        with patch(
            "mender_docker_lifecycle_helper.utils.container_utils.save_local_image_to_file"
        ) as mock_local:
            with patch(
                "mender_docker_lifecycle_helper.utils.container_utils.save_registry_image_to_file"
            ) as mock_registry:
                # Local fails with ImageNotFoundException (triggering fallback)
                mock_local.side_effect = ImageNotFoundException("local fail")
                # Registry fails with unexpected error
                mock_registry.side_effect = PermissionError("Cannot access registry")

                # The PermissionError should propagate up
                with pytest.raises(PermissionError, match="Cannot access registry"):
                    save_image_to_file(image, file_path)

                mock_local.assert_called_once()
                mock_registry.assert_called_once()


class TestGetImageHash:
    """Tests for the container_utils get_image_hash method"""

    def test_get_image_hash_remote_success(self):
        """Test that get_image_hash retrieves hash via docker buildx imagetools for remote images."""
        logger = logging.getLogger("test")
        image_ref = "my-registry.com/my-image:latest"
        expected_hash = "1234567890abcdef"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=f'"sha256:{expected_hash}"', stderr=""
            )

            result = get_image_hash(image_ref, logger)

            assert result == expected_hash
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args == [
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                image_ref,
                "--format",
                '"{{json .Manifest.Digest}}"',
            ]

    def test_get_image_hash_local_fallback(self):
        """Test that get_image_hash falls back to docker inspect when buildx fails."""
        logger = logging.getLogger("test")
        image_ref = "my-image:latest"
        expected_hash = "1234567890abcdef"

        with patch("subprocess.run") as mock_run:
            # First call (buildx) fails, second call (inspect) succeeds
            mock_run.side_effect = [
                subprocess.CalledProcessError(1, "docker buildx"),
                subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=f"sha256:{expected_hash}", stderr=""
                ),
            ]

            result = get_image_hash(image_ref, logger)

            assert result == expected_hash
            assert mock_run.call_count == 2

    def test_get_image_hash_both_fail(self):
        """Test that get_image_hash raises ValueError when both buildx and inspect fail."""
        logger = logging.getLogger("test")
        image_ref = "my-image:latest"

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                subprocess.CalledProcessError(1, "docker buildx"),
                subprocess.CalledProcessError(1, "docker inspect"),
            ]

            with pytest.raises(ValueError) as exc_info:
                get_image_hash(image_ref, logger)

            assert f"Could not retrieve hash for image: {image_ref}" in str(
                exc_info.value
            )

    def test_get_image_hash_strips_quotes_and_prefix(self):
        """Test that get_image_hash properly strips quotes and sha256: prefix from output."""
        logger = logging.getLogger("test")
        image_ref = "my-registry.com/my-image:latest"
        expected_hash = "abc123def456"

        with patch("subprocess.run") as mock_run:
            # Output with quotes and sha256: prefix
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=f'"{HASH_PREFIX}:{expected_hash}"',
                stderr="",
            )

            result = get_image_hash(image_ref, logger)

            assert result == expected_hash


class TestSaveImageIntegration:
    """Integration tests for the container_utils save image methods"""

    def test_save_registry_image_to_file_integration(self, tmp_path):
        """Integration test that actually calls skopeo to save a registry image to a file."""
        # Use the exact image reference specified in the task
        image_ref = "busybox:1.37.0-musl@sha256:19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138"
        file_path = tmp_path / "busybox.tar"

        # This should not raise an exception if the image is available and skopeo works
        save_registry_image_to_file(image_ref, file_path)

        # Verify the file was created and is not empty
        assert file_path.exists()
        assert file_path.stat().st_size > 100000

    def test_save_image_to_file_integration(self, tmp_path):
        """Integration test that actually calls skopeo to save a remote image to a file."""
        # Use the exact image reference specified in the task
        image = {
            "ref": "busybox:1.37.0-musl",
            "hash": "19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138",
        }
        file_path = tmp_path / "busybox.tar"

        # This should not raise an exception if the image is available and skopeo works
        save_image_to_file(image, file_path)

        # Verify the file was created and contains expected content
        assert file_path.exists()
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()
        with tarfile.open(file_path, "r:*") as tar:
            tar.extractall(
                path=extract_dir,
                filter="tar",
            )
        assert (
            extract_dir / "index.json"
        ).read_text() == '{"schemaVersion":2,"mediaType":"application/vnd.oci.image.index.v1+json","manifests":[{"mediaType":"application/vnd.oci.image.manifest.v1+json","digest":"sha256:298efc24641ff8a1a285abdc555a0ce5ab7c42eb085e1be099f824188e069604","size":608}]}'
        assert (
            extract_dir / "oci-layout"
        ).read_text() == '{"imageLayoutVersion":"1.0.0"}'
        assert (
            extract_dir
            / "blobs"
            / "sha256"
            / "0188a8de47ca89b720586f01da7d7f870bdcf5f770b19f740291d716235d3107"
        ).exists()
        assert (
            extract_dir
            / "blobs"
            / "sha256"
            / "298efc24641ff8a1a285abdc555a0ce5ab7c42eb085e1be099f824188e069604"
        ).exists()
        assert (
            extract_dir
            / "blobs"
            / "sha256"
            / "5bfa213ad2917fd7ef0d56c49b841de3a4788e60b3554ad86d616100e095c1f8"
        ).exists()
