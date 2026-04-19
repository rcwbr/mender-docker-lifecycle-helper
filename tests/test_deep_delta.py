import pytest
import json
import logging
import tarfile
from unittest.mock import patch, MagicMock
from pathlib import Path
import subprocess
import tempfile
import os

from mender_docker_lifecycle_helper.utils.deep_delta import (
    _read_layers_from_manifest,
    oci_deep_delta,
    ImageDeltaException
)


def test_read_layers_from_manifest():
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
                    "mediaType": "application/vnd.oci.image.manifest.v1+json"
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
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip"
                },
                {
                    "digest": "sha256:fedcba0987654321",
                    "size": 2000,
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip"
                }
            ]
        }
        manifest_file = blobs_dir / "abcdef1234567890"
        manifest_file.write_text(json.dumps(manifest_data))

        # Call function
        layers = _read_layers_from_manifest(test_dir)

        # Assertions
        assert len(layers) == 2
        assert layers[0] == blobs_dir / "layer1234567890abcdef"
        assert layers[1] == blobs_dir / "fedcba0987654321"


def test_oci_deep_delta_success():
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
        (to_dir / "blobs" / "sha256" / "layer1").parent.mkdir(parents=True, exist_ok=True)
        (to_dir / "blobs" / "sha256" / "layer1").touch()
        (to_dir / "blobs" / "sha256" / "layer2").touch()
        (to_dir / "blobs" / "sha256" / "layer3").touch()

        # Create fake layer files in from_dir (these are what _read_layers_from_manifest returns)
        (from_dir / "layer1").touch()
        (from_dir / "layer2").touch()

        with patch("mender_docker_lifecycle_helper.utils.deep_delta._read_layers_from_manifest") as mock_read_layers, \
            patch("subprocess.run") as mock_subprocess, \
            patch("tarfile.open") as mock_tarfile, \
            patch("shutil.rmtree") as mock_rmtree:

            # Setup mocks
            mock_read_layers.side_effect = [
                [from_dir / "layer1", from_dir / "layer2"],  # from_layers
                [to_dir / "blobs" / "sha256" / "layer1", to_dir / "blobs" / "sha256" / "layer2", to_dir / "blobs" / "sha256" / "layer3"]  # to_layers
            ]
            mock_subprocess.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            mock_tar_instance = MagicMock()
            mock_tarfile.return_value.__enter__.return_value = mock_tar_instance

            # Call function
            delta_filename = "test-delta.tar"
            result = oci_deep_delta(from_dir, to_dir, delta_dir, delta_filename)

            # Assertions
            assert mock_read_layers.call_count == 2

            # Should call subprocess.run for each layer pair (2 calls since from_layers has 2 items)
            assert mock_subprocess.call_count == 2

            # Check that tarfile was called correctly
            mock_tarfile.assert_called_once_with(delta_dir / "test-delta.tar", "w")
            mock_tar_instance.add.assert_called_once()

            # Check cleanup
            mock_rmtree.assert_called_once_with(delta_dir / "gen")

            # Check result
            assert result == delta_dir / "test-delta.tar"


def test_oci_deep_delta_error_on_more_from_layers():
    """Test oci_deep_delta raises ImageDeltaException when from image has more layers than to image."""
    with patch("mender_docker_lifecycle_helper.utils.deep_delta._read_layers_from_manifest") as mock_read_layers:
        # Setup mocks - from has 3 layers, to has 2 layers
        mock_read_layers.side_effect = [
            [Path("/fake/from/layer1"), Path("/fake/from/layer2"), Path("/fake/from/layer3")],  # from_layers
            [Path("/fake/to/layer1"), Path("/fake/to/layer2")]  # to_layers
        ]

        from_dir = Path("/fake/from")
        to_dir = Path("/fake/to")
        delta_dir = Path("/fake/delta")
        delta_filename = "test-delta.tar"

        # Should raise ImageDeltaException
        with pytest.raises(ImageDeltaException) as exc_info:
            oci_deep_delta(from_dir, to_dir, delta_dir, delta_filename)

        assert "source image has more layers than the new one" in str(exc_info.value)


def test_oci_deep_delta_subprocess_error():
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
        (to_dir / "blobs" / "sha256" / "layer1").parent.mkdir(parents=True, exist_ok=True)
        (to_dir / "blobs" / "sha256" / "layer1").touch()

        # Create fake layer files in from_dir (these are what _read_layers_from_manifest returns)
        (from_dir / "layer1").touch()

        with patch("mender_docker_lifecycle_helper.utils.deep_delta._read_layers_from_manifest") as mock_read_layers, \
             patch("shutil.copytree"), \
             patch("subprocess.run") as mock_subprocess, \
             patch("tarfile.open"), \
             patch("shutil.rmtree"):

            # Setup mocks
            mock_read_layers.side_effect = [
                [from_dir / "layer1"],  # from_layers
                [to_dir / "blobs" / "sha256" / "layer1"]     # to_layers
            ]
            # Simulate subprocess error via CalledProcessError (which gets converted)
            error = subprocess.CalledProcessError(1, "xdelta3")
            error.stderr = "xdelta3 failed"
            mock_subprocess.side_effect = error

            # Should propagate the subprocess error
            with pytest.raises(subprocess.SubprocessError) as exc_info:
                oci_deep_delta(from_dir, to_dir, delta_dir, "test-delta.tar")

            assert "xdelta3 failed" in str(exc_info.value)


def test_oci_deep_delta_subprocess_error_non_zero_returncode():
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
        (to_dir / "blobs" / "sha256" / "layer1").parent.mkdir(parents=True, exist_ok=True)
        (to_dir / "blobs" / "sha256" / "layer1").touch()

        # Create fake layer files in from_dir (these are what _read_layers_from_manifest returns)
        (from_dir / "layer1").touch()

        with patch("mender_docker_lifecycle_helper.utils.deep_delta._read_layers_from_manifest") as mock_read_layers, \
             patch("shutil.copytree"), \
             patch("subprocess.run") as mock_subprocess, \
             patch("tarfile.open"), \
             patch("shutil.rmtree"):

            # Setup mocks
            mock_read_layers.side_effect = [
                [from_dir / "layer1"],  # from_layers
                [to_dir / "blobs" / "sha256" / "layer1"]     # to_layers
            ]
            # Simulate subprocess returning non-zero exit code (but not throwing exception)
            mock_subprocess.return_value = subprocess.CompletedProcess(
                args=["xdelta3", "-f", "-e", "-s", "/fake/from/layer1", "/fake/to/layer1", "/fake/delta/gen/blobs/sha256/layer1.vcdiff"],
                returncode=1,
                stdout=b"",
                stderr=b"xdelta3 failed"
            )

            # Should propagate the subprocess error via our manual check
            with pytest.raises(subprocess.SubprocessError) as exc_info:
                oci_deep_delta(from_dir, to_dir, delta_dir, "test-delta.tar")

            assert "xdelta3 failed" in str(exc_info.value)


def test_oci_deep_delta_with_custom_delta_cmd():
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
        (to_dir / "blobs" / "sha256" / "layer1").parent.mkdir(parents=True, exist_ok=True)
        (to_dir / "blobs" / "sha256" / "layer1").touch()

        # Create fake layer files in from_dir (these are what _read_layers_from_manifest returns)
        (from_dir / "layer1").touch()

        with patch("mender_docker_lifecycle_helper.utils.deep_delta._read_layers_from_manifest") as mock_read_layers, \
            patch("subprocess.run") as mock_subprocess, \
            patch("tarfile.open"), \
            patch("shutil.rmtree"):

            # Setup mocks
            mock_read_layers.side_effect = [
                [from_dir / "layer1"],  # from_layers
                [to_dir / "blobs" / "sha256" / "layer1"]  # to_layers
            ]
            mock_subprocess.return_value = subprocess.CompletedProcess(args=[], returncode=0)

            delta_filename = "test-delta.tar"
            custom_delta_cmd = ["custom-delta-tool", "-arg1", "-arg2"]

            # Call function with custom delta command
            oci_deep_delta(from_dir, to_dir, delta_dir, delta_filename, delta_cmd=custom_delta_cmd)

            # Verify subprocess was called with custom command
            mock_subprocess.assert_called_once()
            args, kwargs = mock_subprocess.call_args
            # Check that the command starts with our custom delta command
            assert args[0][:len(custom_delta_cmd)] == custom_delta_cmd
            assert kwargs["capture_output"] is True
            assert kwargs["check"] is True
