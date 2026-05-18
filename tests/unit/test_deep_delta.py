import hashlib
import json
import pytest
import subprocess
import tarfile
import tempfile

from unittest.mock import patch, MagicMock
from pathlib import Path

from mender_docker_lifecycle_helper.utils.deep_delta import (
    _read_layers_from_manifest,
    oci_deep_delta,
    ImageDeltaException,
)
from mender_docker_lifecycle_helper.utils.image_cache import ImageCache


class TestReadLayersFromManifest:
    """Tests for the deep_delta _read_layers_from_manifest function"""

    def test_read_layers_from_manifest(self):
        """Test _read_layers_from_manifest reads layers correctly from OCI image structure."""
        # Setup test directory structure
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_dir = Path(tmp_dir) / "test-image"
            blobs_dir = test_dir / "blobs" / "sha256"
            blobs_dir.mkdir(parents=True)

            # Create index.json
            index_data = {
                "manifests": [
                    {
                        "digest": "sha256:abcdef1234567890",
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    }
                ]
            }
            index_file = test_dir / "index.json"
            index_file.write_text(json.dumps(index_data))

            # Create manifest file
            manifest_data = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "layers": [
                    {
                        "digest": "sha256:layer1234567890abcdef",
                        "size": 1000,
                        "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    },
                    {
                        "digest": "sha256:fedcba0987654321",
                        "size": 2000,
                        "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    },
                ],
            }
            manifest_file = blobs_dir / "abcdef1234567890"
            manifest_file.write_text(json.dumps(manifest_data))

            # Call function
            layers = _read_layers_from_manifest(test_dir, "linux/amd64")

            # Assertions
            assert len(layers) == 2
            assert layers[0] == blobs_dir / "layer1234567890abcdef"
            assert layers[1] == blobs_dir / "fedcba0987654321"

    def test_read_layers_from_manifest_multi_platform(self):
        """Test _read_layers_from_manifest handles multi-platform images correctly."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_dir = Path(tmp_dir) / "test-image"
            blobs_dir = test_dir / "blobs" / "sha256"
            blobs_dir.mkdir(parents=True)

            # index.json points to an intermediate manifest (multi-platform index)
            index_data = {
                "schemaVersion": 2,
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:intermediate_manifest",
                    },
                ],
            }
            index_file = test_dir / "index.json"
            index_file.write_text(json.dumps(index_data))

            # Intermediate manifest contains platform-specific manifests
            intermediate_manifest = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:manifest_amd64",
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:manifest_arm64",
                        "platform": {"os": "linux", "architecture": "arm64"},
                    },
                ],
            }
            (blobs_dir / "intermediate_manifest").write_text(
                json.dumps(intermediate_manifest)
            )

            amd64_manifest = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "layers": [
                    {
                        "digest": "sha256:amd64_layer1",
                        "size": 1000,
                        "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    },
                ],
            }
            (blobs_dir / "manifest_amd64").write_text(json.dumps(amd64_manifest))

            arm64_manifest = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "layers": [
                    {
                        "digest": "sha256:arm64_layer1",
                        "size": 1000,
                        "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    },
                ],
            }
            (blobs_dir / "manifest_arm64").write_text(json.dumps(arm64_manifest))

            layers = _read_layers_from_manifest(test_dir, "linux/amd64")
            assert len(layers) == 1
            assert layers[0] == blobs_dir / "amd64_layer1"

            layers = _read_layers_from_manifest(test_dir, "linux/arm64")
            assert len(layers) == 1
            assert layers[0] == blobs_dir / "arm64_layer1"

    def test_read_layers_from_manifest_multi_platform_with_variant(self):
        """Test _read_layers_from_manifest handles multi-platform images with variant."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_dir = Path(tmp_dir) / "test-image"
            blobs_dir = test_dir / "blobs" / "sha256"
            blobs_dir.mkdir(parents=True)

            # index.json points to an intermediate manifest (multi-platform index)
            index_data = {
                "schemaVersion": 2,
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:intermediate_manifest",
                    },
                ],
            }
            index_file = test_dir / "index.json"
            index_file.write_text(json.dumps(index_data))

            # Intermediate manifest contains platform-specific manifests with variants
            intermediate_manifest = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:manifest_arm64_v8",
                        "platform": {
                            "os": "linux",
                            "architecture": "arm64",
                            "variant": "v8",
                        },
                    },
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:manifest_arm64_v7",
                        "platform": {
                            "os": "linux",
                            "architecture": "arm64",
                            "variant": "v7",
                        },
                    },
                ],
            }
            (blobs_dir / "intermediate_manifest").write_text(
                json.dumps(intermediate_manifest)
            )

            v8_manifest = {
                "schemaVersion": 2,
                "layers": [
                    {
                        "digest": "sha256:v8_layer1",
                        "size": 1000,
                        "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    },
                ],
            }
            (blobs_dir / "manifest_arm64_v8").write_text(json.dumps(v8_manifest))

            v7_manifest = {
                "schemaVersion": 2,
                "layers": [
                    {
                        "digest": "sha256:v7_layer1",
                        "size": 1000,
                        "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    },
                ],
            }
            (blobs_dir / "manifest_arm64_v7").write_text(json.dumps(v7_manifest))

            layers = _read_layers_from_manifest(test_dir, "linux/arm64/v8")
            assert len(layers) == 1
            assert layers[0] == blobs_dir / "v8_layer1"

            layers = _read_layers_from_manifest(test_dir, "linux/arm64/v7")
            assert len(layers) == 1
            assert layers[0] == blobs_dir / "v7_layer1"

    def test_read_layers_from_manifest_multi_platform_no_match(self):
        """Test _read_layers_from_manifest uses first manifest if no platform match."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_dir = Path(tmp_dir) / "test-image"
            blobs_dir = test_dir / "blobs" / "sha256"
            blobs_dir.mkdir(parents=True)

            index_data = {
                "schemaVersion": 2,
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:manifest_amd64",
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                ],
            }
            index_file = test_dir / "index.json"
            index_file.write_text(json.dumps(index_data))

            amd64_manifest = {
                "schemaVersion": 2,
                "layers": [
                    {
                        "digest": "sha256:amd64_layer1",
                        "size": 1000,
                        "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    },
                ],
            }
            (blobs_dir / "manifest_amd64").write_text(json.dumps(amd64_manifest))

            layers = _read_layers_from_manifest(test_dir, "linux/nonexistent")
            assert len(layers) == 1
            assert layers[0] == blobs_dir / "amd64_layer1"

    def test_read_layers_from_manifest_deeply_nested(self):
        """Test _read_layers_from_manifest handles deeply nested manifests (multiple levels)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_dir = Path(tmp_dir) / "test-image"
            blobs_dir = test_dir / "blobs" / "sha256"
            blobs_dir.mkdir(parents=True)

            # index.json points to level1 manifest (no layers, has manifests)
            index_data = {
                "schemaVersion": 2,
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:manifest_level1",
                    },
                ],
            }
            index_file = test_dir / "index.json"
            index_file.write_text(json.dumps(index_data))

            # Level 1 manifest: no layers, contains platform-specific manifests
            # This simulates a multi-arch index that points to another multi-arch index
            level1_manifest = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:manifest_level2_amd64",
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:manifest_level2_arm64",
                        "platform": {"os": "linux", "architecture": "arm64"},
                    },
                ],
            }
            (blobs_dir / "manifest_level1").write_text(json.dumps(level1_manifest))

            # Level 2 manifest for amd64: still no layers, another level of nesting
            level2_amd64_manifest = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:manifest_final_amd64",
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                ],
            }
            (blobs_dir / "manifest_level2_amd64").write_text(
                json.dumps(level2_amd64_manifest)
            )

            # Level 2 manifest for arm64: still no layers, another level of nesting
            level2_arm64_manifest = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:manifest_final_arm64",
                        "platform": {"os": "linux", "architecture": "arm64"},
                    },
                ],
            }
            (blobs_dir / "manifest_level2_arm64").write_text(
                json.dumps(level2_arm64_manifest)
            )

            # Final amd64 manifest with actual layers
            final_amd64_manifest = {
                "schemaVersion": 2,
                "layers": [
                    {
                        "digest": "sha256:deep_amd64_layer1",
                        "size": 1000,
                        "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    },
                    {
                        "digest": "sha256:deep_amd64_layer2",
                        "size": 2000,
                        "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    },
                ],
            }
            (blobs_dir / "manifest_final_amd64").write_text(
                json.dumps(final_amd64_manifest)
            )

            # Final arm64 manifest with actual layers
            final_arm64_manifest = {
                "schemaVersion": 2,
                "layers": [
                    {
                        "digest": "sha256:deep_arm64_layer1",
                        "size": 1000,
                        "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    },
                ],
            }
            (blobs_dir / "manifest_final_arm64").write_text(
                json.dumps(final_arm64_manifest)
            )

            # Test amd64 - should traverse 3 levels deep
            layers = _read_layers_from_manifest(test_dir, "linux/amd64")
            assert len(layers) == 2
            assert layers[0] == blobs_dir / "deep_amd64_layer1"
            assert layers[1] == blobs_dir / "deep_amd64_layer2"

            # Test arm64 - should traverse 3 levels deep
            layers = _read_layers_from_manifest(test_dir, "linux/arm64")
            assert len(layers) == 1
            assert layers[0] == blobs_dir / "deep_arm64_layer1"

    def test_read_layers_from_manifest_cycle_detection(self):
        """Test _read_layers_from_manifest raises exception on cyclic manifest references."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_dir = Path(tmp_dir) / "test-image"
            blobs_dir = test_dir / "blobs" / "sha256"
            blobs_dir.mkdir(parents=True)

            # index.json points to manifest_a
            index_data = {
                "schemaVersion": 2,
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:manifest_a",
                    },
                ],
            }
            index_file = test_dir / "index.json"
            index_file.write_text(json.dumps(index_data))

            # manifest_a points back to manifest_a (cycle)
            manifest_a = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:manifest_a",
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                ],
            }
            (blobs_dir / "manifest_a").write_text(json.dumps(manifest_a))

            # Should raise ImageDeltaException due to cycle detection
            with pytest.raises(ImageDeltaException) as exc_info:
                _read_layers_from_manifest(test_dir, "linux/amd64")

            assert "Cycle detected" in str(exc_info.value)

    def test_read_layers_from_manifest_no_matching_platform(self):
        """Test _read_layers_from_manifest raises exception when no matching platform in nested manifest."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_dir = Path(tmp_dir) / "test-image"
            blobs_dir = test_dir / "blobs" / "sha256"
            blobs_dir.mkdir(parents=True)

            # index.json points to an intermediate manifest
            index_data = {
                "schemaVersion": 2,
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:manifest_level1",
                    },
                ],
            }
            index_file = test_dir / "index.json"
            index_file.write_text(json.dumps(index_data))

            # Level 1 manifest has no matching platform
            level1_manifest = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:manifest_arm64",
                        "platform": {"os": "linux", "architecture": "arm64"},
                    },
                ],
            }
            (blobs_dir / "manifest_level1").write_text(json.dumps(level1_manifest))

            # Should raise ImageDeltaException when no matching platform found
            with pytest.raises(ImageDeltaException) as exc_info:
                _read_layers_from_manifest(test_dir, "linux/amd64")

            assert "No matching platform found" in str(exc_info.value)


class TestOCIDeepDelta:
    """Tests for the deep_delta oci_deep_delta function"""

    def test_oci_deep_delta_success(self):
        """Test oci_deep_delta generates delta successfully when from_layers <= to_layers."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            from_dir = Path(tmp_dir) / "from"
            to_dir = Path(tmp_dir) / "to"
            delta_dir = Path(tmp_dir) / "delta"

            # Create basic directory structure
            from_dir.mkdir()
            to_dir.mkdir()
            delta_dir.mkdir()

            # Create fake layer files in to_dir (these will be copied by copytree)
            (to_dir / "blobs" / "sha256" / "layer1").parent.mkdir(
                parents=True, exist_ok=True
            )
            (to_dir / "blobs" / "sha256" / "layer1").touch()
            (to_dir / "blobs" / "sha256" / "layer2").touch()
            (to_dir / "blobs" / "sha256" / "layer3").touch()

            # Create fake layer files in from_dir (these are what _read_layers_from_manifest returns)
            (from_dir / "layer1").touch()
            (from_dir / "layer2").touch()

            with (
                patch(
                    "mender_docker_lifecycle_helper.utils.deep_delta._read_layers_from_manifest"
                ) as mock_read_layers,
                patch("subprocess.run") as mock_subprocess,
                patch("tarfile.open") as mock_tarfile,
                patch("shutil.rmtree") as mock_rmtree,
            ):

                # Setup mocks
                mock_read_layers.side_effect = [
                    [from_dir / "layer1", from_dir / "layer2"],  # from_layers
                    [
                        to_dir / "blobs" / "sha256" / "layer1",
                        to_dir / "blobs" / "sha256" / "layer2",
                        to_dir / "blobs" / "sha256" / "layer3",
                    ],  # to_layers
                ]
                mock_subprocess.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0
                )
                mock_tar_instance = MagicMock()
                mock_tarfile.return_value.__enter__.return_value = mock_tar_instance

                result = oci_deep_delta(
                    from_dir, to_dir, delta_dir, "test-delta.tar", "linux/amd64"
                )

                assert mock_read_layers.call_count == 2
                for call in mock_read_layers.call_args_list:
                    assert call[0][1] == "linux/amd64"

                # Should call subprocess.run for each layer pair + 1 extra for the additional layer in to_layers
                assert mock_subprocess.call_count == 3

                # Check that tarfile was called correctly
                mock_tarfile.assert_called_once_with(delta_dir / "test-delta.tar", "w")
                mock_tar_instance.add.assert_called_once()

                # Check cleanup
                mock_rmtree.assert_called_once_with(delta_dir / "gen")

                # Check result
                assert result == delta_dir / "test-delta.tar"

    def test_oci_deep_delta_extra_layers_in_to_image(self):
        """Test oci_deep_delta handles extra layers in to image by creating full layer diffs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            from_dir = Path(tmp_dir) / "from"
            to_dir = Path(tmp_dir) / "to"
            delta_dir = Path(tmp_dir) / "delta"

            # Create basic directory structure
            from_dir.mkdir()
            to_dir.mkdir()
            delta_dir.mkdir()

            # Create fake layer files in to_dir (these will be copied by copytree)
            (to_dir / "blobs" / "sha256" / "layer1").parent.mkdir(
                parents=True, exist_ok=True
            )
            (to_dir / "blobs" / "sha256" / "layer1").touch()
            (to_dir / "blobs" / "sha256" / "layer2").touch()
            (to_dir / "blobs" / "sha256" / "layer3").touch()

            # Create fake layer files in from_dir
            (from_dir / "layer1").touch()
            (from_dir / "layer2").touch()

            with (
                patch(
                    "mender_docker_lifecycle_helper.utils.deep_delta._read_layers_from_manifest"
                ) as mock_read_layers,
                patch("subprocess.run") as mock_subprocess,
                patch("tarfile.open"),
                patch("shutil.rmtree"),
            ):

                # Setup mocks: to has 3 layers, from has 2 layers
                mock_read_layers.side_effect = [
                    [from_dir / "layer1", from_dir / "layer2"],  # from_layers
                    [
                        to_dir / "blobs" / "sha256" / "layer1",
                        to_dir / "blobs" / "sha256" / "layer2",
                        to_dir / "blobs" / "sha256" / "layer3",
                    ],  # to_layers - has 1 extra layer
                ]
                mock_subprocess.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0
                )

                result = oci_deep_delta(
                    from_dir, to_dir, delta_dir, "test-delta.tar", "linux/amd64"
                )

                # Should call subprocess.run 3 times (2 for regular diffs + 1 for extra layer)
                assert mock_subprocess.call_count == 3

                # Check the last call was for /dev/null source (index 4 after: xdelta3, -f, -e, -s)
                last_call_args = mock_subprocess.call_args_list[-1][0][0]
                assert str(last_call_args[4]) == "/dev/null"

                assert result == delta_dir / "test-delta.tar"

    def test_oci_deep_delta_error_on_more_from_layers(self):
        """Test oci_deep_delta raises ImageDeltaException when from image has more layers than to image."""
        with patch(
            "mender_docker_lifecycle_helper.utils.deep_delta._read_layers_from_manifest"
        ) as mock_read_layers:
            # Setup mocks - from has 3 layers, to has 2 layers
            mock_read_layers.side_effect = [
                [
                    Path("/fake/from/layer1"),
                    Path("/fake/from/layer2"),
                    Path("/fake/from/layer3"),
                ],  # from_layers
                [Path("/fake/to/layer1"), Path("/fake/to/layer2")],  # to_layers
            ]

            from_dir = Path("/fake/from")
            to_dir = Path("/fake/to")
            delta_dir = Path("/fake/delta")

            # Should raise ImageDeltaException
            with pytest.raises(ImageDeltaException) as exc_info:
                oci_deep_delta(
                    from_dir, to_dir, delta_dir, "test-delta.tar", "linux/amd64"
                )

            assert "source image has more layers than the new one" in str(
                exc_info.value
            )

    def test_oci_deep_delta_subprocess_error(self):
        """Test oci_deep_delta handles subprocess errors properly."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            from_dir = Path(tmp_dir) / "from"
            to_dir = Path(tmp_dir) / "to"
            delta_dir = Path(tmp_dir) / "delta"

            # Create basic directory structure
            from_dir.mkdir()
            to_dir.mkdir()
            delta_dir.mkdir()

            # Create fake layer files in to_dir (these will be copied by copytree)
            (to_dir / "blobs" / "sha256" / "layer1").parent.mkdir(
                parents=True, exist_ok=True
            )
            (to_dir / "blobs" / "sha256" / "layer1").touch()

            # Create fake layer files in from_dir (these are what _read_layers_from_manifest returns)
            (from_dir / "layer1").touch()

            with (
                patch(
                    "mender_docker_lifecycle_helper.utils.deep_delta._read_layers_from_manifest"
                ) as mock_read_layers,
                patch("shutil.copytree"),
                patch("subprocess.run") as mock_subprocess,
                patch("tarfile.open"),
                patch("shutil.rmtree"),
            ):

                # Setup mocks
                mock_read_layers.side_effect = [
                    [from_dir / "layer1"],  # from_layers
                    [to_dir / "blobs" / "sha256" / "layer1"],  # to_layers
                ]
                # Simulate subprocess error via CalledProcessError (which gets converted)
                error = subprocess.CalledProcessError(1, "xdelta3")
                error.stderr = "xdelta3 failed"
                mock_subprocess.side_effect = error

                with pytest.raises(subprocess.SubprocessError) as exc_info:
                    oci_deep_delta(
                        from_dir,
                        to_dir,
                        delta_dir,
                        "test-delta.tar",
                        "linux/amd64",
                    )

                assert "xdelta3 failed" in str(exc_info.value)

    def test_oci_deep_delta_subprocess_error_non_zero_returncode(self):
        """Test oci_deep_delta handles subprocess errors when returncode != 0 but no exception thrown."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            from_dir = Path(tmp_dir) / "from"
            to_dir = Path(tmp_dir) / "to"
            delta_dir = Path(tmp_dir) / "delta"

            # Create basic directory structure
            from_dir.mkdir()
            to_dir.mkdir()
            delta_dir.mkdir()

            # Create fake layer files in to_dir (these will be copied by copytree)
            (to_dir / "blobs" / "sha256" / "layer1").parent.mkdir(
                parents=True, exist_ok=True
            )
            (to_dir / "blobs" / "sha256" / "layer1").touch()

            # Create fake layer files in from_dir (these are what _read_layers_from_manifest returns)
            (from_dir / "layer1").touch()

            with (
                patch(
                    "mender_docker_lifecycle_helper.utils.deep_delta._read_layers_from_manifest"
                ) as mock_read_layers,
                patch("shutil.copytree"),
                patch("subprocess.run") as mock_subprocess,
                patch("tarfile.open"),
                patch("shutil.rmtree"),
            ):

                # Setup mocks
                mock_read_layers.side_effect = [
                    [from_dir / "layer1"],  # from_layers
                    [to_dir / "blobs" / "sha256" / "layer1"],  # to_layers
                ]
                # Simulate subprocess returning non-zero exit code (but not throwing exception)
                mock_subprocess.return_value = subprocess.CompletedProcess(
                    args=[
                        "xdelta3",
                        "-f",
                        "-e",
                        "-s",
                        "/fake/from/layer1",
                        "/fake/to/layer1",
                        "/fake/delta/gen/blobs/sha256/layer1.vcdiff",
                    ],
                    returncode=1,
                    stdout=b"",
                    stderr=b"xdelta3 failed",
                )

                # Should propagate the subprocess error via our manual check
                with pytest.raises(subprocess.SubprocessError) as exc_info:
                    oci_deep_delta(
                        from_dir,
                        to_dir,
                        delta_dir,
                        "test-delta.tar",
                        "linux/amd64",
                    )

                assert "xdelta3 failed" in str(exc_info.value)

    def test_oci_deep_delta_with_custom_delta_cmd(self):
        """Test oci_deep_delta works with custom delta command."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            from_dir = Path(tmp_dir) / "from"
            to_dir = Path(tmp_dir) / "to"
            delta_dir = Path(tmp_dir) / "delta"

            # Create basic directory structure
            from_dir.mkdir()
            to_dir.mkdir()
            delta_dir.mkdir()

            # Create fake layer files in to_dir (these will be copied by copytree)
            (to_dir / "blobs" / "sha256" / "layer1").parent.mkdir(
                parents=True, exist_ok=True
            )
            (to_dir / "blobs" / "sha256" / "layer1").touch()

            # Create fake layer files in from_dir (these are what _read_layers_from_manifest returns)
            (from_dir / "layer1").touch()

            with (
                patch(
                    "mender_docker_lifecycle_helper.utils.deep_delta._read_layers_from_manifest"
                ) as mock_read_layers,
                patch("subprocess.run") as mock_subprocess,
                patch("tarfile.open"),
                patch("shutil.rmtree"),
            ):

                # Setup mocks
                mock_read_layers.side_effect = [
                    [from_dir / "layer1"],  # from_layers
                    [to_dir / "blobs" / "sha256" / "layer1"],  # to_layers
                ]
                mock_subprocess.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0
                )

                delta_filename = "test-delta.tar"
                custom_delta_cmd = ["custom-delta-tool", "-arg1", "-arg2"]

                # Call function with custom delta command
                oci_deep_delta(
                    from_dir,
                    to_dir,
                    delta_dir,
                    "test-delta.tar",
                    "linux/amd64",
                    delta_cmd=custom_delta_cmd,
                )

                # Verify subprocess was called with custom command
                mock_subprocess.assert_called_once()
                args, kwargs = mock_subprocess.call_args
                # Check that the command starts with our custom delta command
                assert args[0][: len(custom_delta_cmd)] == custom_delta_cmd
                assert kwargs["capture_output"] is True
                assert kwargs["check"] is True

                for call in mock_read_layers.call_args_list:
                    assert call[0][1] == "linux/amd64"


class TestDeepDeltaIntegration:
    """Integration tests for deep_delta functions"""

    def test_oci_deep_delta_integration_busybox(self, tmp_path):
        """Integration test: generate delta between two busybox images and compare to expected layers."""
        # Create temporary cache directory
        cache_dir = tmp_path / "cache"

        # Initialize cache with platform
        cache = ImageCache(cache_dir, platform="linux/amd64")

        # Use the two specific busybox image hashes
        from_hash = "3f9777e7e82e8591542f72b965ec7db7e8b3bdb59692976af1bb9b2850b05a4e"
        to_hash = "19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138"

        # Generate delta file - this will pull images and extract them
        from_image = {"ref": "busybox:1.37.0-glibc", "hash": from_hash}
        to_image = {"ref": "busybox:1.37.0-musl", "hash": to_hash}
        delta_file = cache.delta(from_image, to_image)

        # Verify delta file was created with correct contents
        extract_dir = tmp_path / "delta_extract"
        extract_dir.mkdir()
        with tarfile.open(delta_file, "r:*") as tar:
            tar.extractall(
                path=extract_dir,
                filter="tar",
            )

        expected_dir = Path(
            "tests/resources/deep_delta_integration/test_oci_deep_delta_integration_busybox"
        )
        assert (extract_dir / "index.json").read_text() == (
            expected_dir / "index.json"
        ).read_text()
        assert (extract_dir / "oci-layout").read_text() == (
            expected_dir / "oci-layout"
        ).read_text()

        assert (
            extract_dir
            / "blobs"
            / "sha256"
            / "298efc24641ff8a1a285abdc555a0ce5ab7c42eb085e1be099f824188e069604"
        ).read_text() == (
            expected_dir
            / "blobs"
            / "sha256"
            / "298efc24641ff8a1a285abdc555a0ce5ab7c42eb085e1be099f824188e069604"
        ).read_text()

        assert (
            extract_dir
            / "blobs"
            / "sha256"
            / "0188a8de47ca89b720586f01da7d7f870bdcf5f770b19f740291d716235d3107"
        ).read_text() == (
            expected_dir
            / "blobs"
            / "sha256"
            / "0188a8de47ca89b720586f01da7d7f870bdcf5f770b19f740291d716235d3107"
        ).read_text()

        assert (
            extract_dir
            / "blobs"
            / "sha256"
            / "5bfa213ad2917fd7ef0d56c49b841de3a4788e60b3554ad86d616100e095c1f8.source"
        ).read_text() == (
            expected_dir
            / "blobs"
            / "sha256"
            / "5bfa213ad2917fd7ef0d56c49b841de3a4788e60b3554ad86d616100e095c1f8.source"
        ).read_text()

        # sha256sum compare of 5bfa213ad2917fd7ef0d56c49b841de3a4788e60b3554ad86d616100e095c1f8.vcdiff
        assert (
            hashlib.sha256(
                (
                    extract_dir
                    / "blobs"
                    / "sha256"
                    / "5bfa213ad2917fd7ef0d56c49b841de3a4788e60b3554ad86d616100e095c1f8.vcdiff"
                ).read_bytes()
            ).hexdigest()
            == "b09f1c585797e15f60348f6a312e2e9a1918c639317665c1be48fb8fa9ddd078"
        )
