import io
import json
import shutil
import tarfile
from unittest.mock import patch

import pytest

from mender_docker_lifecycle_helper.utils.image_cache import (
    ImageCache,
    ImageDirFormatException,
)


def _create_oci_tar(tmp_path, image_name="test-image", digest="sha256abc123"):
    """Helper to create a minimal OCI image tar archive for testing."""
    tar_path = tmp_path / f"test_image-{image_name}.tar"
    with tarfile.open(tar_path, "w") as tar:
        oci_layout_content = json.dumps({"imageLayoutVersion": "1.0.0"}).encode("utf-8")
        oci_layout_info = tarfile.TarInfo(name="oci-layout")
        oci_layout_info.size = len(oci_layout_content)
        tar.addfile(oci_layout_info, io.BytesIO(oci_layout_content))

        index_content = json.dumps(
            {
                "schemaVersion": 2,
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": digest,
                        "size": 42,
                        "annotations": {"io.containerd.image.name": image_name},
                    }
                ],
            }
        ).encode("utf-8")
        index_info = tarfile.TarInfo(name="index.json")
        index_info.size = len(index_content)
        tar.addfile(index_info, io.BytesIO(index_content))

    return tar_path


class TestImageCacheInit:
    """Tests for ImageCache initialization."""

    def test_init_creates_cache_dirs(self, tmp_path):
        """Test that __init__ creates all required cache directories."""
        cache = ImageCache(tmp_path)

        assert (tmp_path / "delta").is_dir()
        assert (tmp_path / "extract").is_dir()
        assert (tmp_path / "save").is_dir()

    def test_init_with_custom_dirnames(self, tmp_path):
        """Test that custom directory names are used."""
        cache = ImageCache(
            tmp_path,
            delta_cache_dirname="custom_delta",
            extract_cache_dirname="custom_extract",
            save_cache_dirname="custom_save",
        )

        assert (tmp_path / "custom_delta").is_dir()
        assert (tmp_path / "custom_extract").is_dir()
        assert (tmp_path / "custom_save").is_dir()

    def test_init_populates_delta_cache_empty(self, tmp_path):
        """Test that delta_cache is empty when no deltas exist."""
        cache = ImageCache(tmp_path)

        assert cache.delta_cache == {}

    def test_init_populates_extract_cache_empty(self, tmp_path):
        """Test that extract_cache is empty when no images extracted."""
        cache = ImageCache(tmp_path)

        assert cache.extract_cache == {}

    def test_init_populates_save_cache_empty(self, tmp_path):
        """Test that save_cache is empty when no images saved."""
        cache = ImageCache(tmp_path)

        assert cache.save_cache == {}

    def test_init_populates_delta_cache_with_existing(self, tmp_path):
        """Test that delta_cache is populated with existing deltas."""
        # Create existing delta structure
        delta_dir = tmp_path / "delta" / "hash1" / "hash2"
        delta_dir.mkdir(parents=True)
        (delta_dir / "image.img").touch()

        cache = ImageCache(tmp_path)

        assert "hash1" in cache.delta_cache
        assert "hash2" in cache.delta_cache["hash1"]
        assert cache.delta_cache["hash1"]["hash2"] == delta_dir / "image.img"


class TestImageCacheDelta:
    """Tests for ImageCache.delta method."""

    def test_delta_existing_delta_returns_path(self, tmp_path):
        """Test that delta returns existing delta path."""
        # Pre-populate delta cache
        from_dir = tmp_path / "delta" / "hash1" / "hash2"
        from_dir.mkdir(parents=True)
        delta_file = from_dir / "image.img"
        delta_file.touch()

        cache = ImageCache(tmp_path)

        result = cache.delta(
            {"ref": "from-image", "hash": "hash1"},
            {"ref": "to-image", "hash": "hash2"},
            "linux/amd64",
        )
        assert result == delta_file

    def test_delta_mock_oci_deep_delta(self, tmp_path):
        """Test that delta calls oci_deep_delta with expected inputs."""
        cache = ImageCache(tmp_path)

        # Prepare test images in cache
        from_tar = _create_oci_tar(
            tmp_path, image_name="from-image", digest="from_hash"
        )
        to_tar = _create_oci_tar(tmp_path, image_name="to-image", digest="to_hash")
        cache.extract_cache_file(from_tar)
        cache.extract_cache_file(to_tar)

        # Mock oci_deep_delta to return a predictable path
        with patch(
            "mender_docker_lifecycle_helper.utils.image_cache.oci_deep_delta"
        ) as mock_oci_deep_delta:
            mock_return_path = (
                tmp_path / "delta" / "from_hash" / "to_hash" / "image.img"
            )
            mock_return_path.parent.mkdir(parents=True)
            mock_return_path.touch()
            mock_oci_deep_delta.return_value = mock_return_path

            # Call delta method
            result = cache.delta(
                {"ref": "from-image", "hash": "from_hash"},
                {"ref": "to-image", "hash": "to_hash"},
                "linux/amd64",
            )

            # Verify oci_deep_delta was called with correct parameters
            mock_oci_deep_delta.assert_called_once()
            args, kwargs = mock_oci_deep_delta.call_args

            # Check that the first two args are the extracted image directories
            assert args[0] == tmp_path / "extract" / "from_hash"
            assert args[1] == tmp_path / "extract" / "to_hash"

            # Check that the third arg is the delta directory
            assert args[2] == tmp_path / "delta" / "from_hash" / "to_hash"

            # Check that the fourth arg is the image file name
            assert args[3] == "image.img"
            assert args[4] == "linux/amd64"

            # Verify the result is what we mocked
            assert result == mock_return_path

    def test_delta_cached_does_not_call_oci_deep_delta(self, tmp_path):
        """Test that a second delta() call with same inputs returns cached path without calling oci_deep_delta."""
        cache = ImageCache(tmp_path)

        # Prepare test images in cache
        from_tar = _create_oci_tar(
            tmp_path, image_name="from-image", digest="from_hash"
        )
        to_tar = _create_oci_tar(tmp_path, image_name="to-image", digest="to_hash")
        cache.extract_cache_file(from_tar)
        cache.extract_cache_file(to_tar)

        mock_return_path = tmp_path / "delta" / "from_hash" / "to_hash" / "image.img"
        mock_return_path.parent.mkdir(parents=True)
        mock_return_path.touch()

        with patch(
            "mender_docker_lifecycle_helper.utils.image_cache.oci_deep_delta",
            return_value=mock_return_path,
        ) as mock_oci:
            # First call should invoke oci_deep_delta
            result1 = cache.delta(
                {"ref": "from-image", "hash": "from_hash"},
                {"ref": "to-image", "hash": "to_hash"},
                "linux/amd64",
            )
            assert result1 == mock_return_path
            assert mock_oci.call_count == 1

            # Second call with same params should hit cache, not call oci_deep_delta again
            result2 = cache.delta(
                {"ref": "from-image", "hash": "from_hash"},
                {"ref": "to-image", "hash": "to_hash"},
                "linux/amd64",
            )
            assert result2 == mock_return_path
            assert mock_oci.call_count == 1


class TestImageCacheCustomImageFileName:
    """Tests for ImageCache with custom image file name."""

    def test_init_with_custom_image_filename(self, tmp_path):
        """Test that custom image file name is used."""
        cache = ImageCache(tmp_path, image_file_name="custom.img")
        image_tar = _create_oci_tar(tmp_path, image_name="image", digest="hash")

        result = cache.save_cache_image(cache.extract_cache_file(image_tar))
        assert result.name == "custom.img"


class TestImageCacheExtractCacheFile:
    """Tests for ImageCache.extract_cache_file method."""

    def test_extract_cache_file_success(self, tmp_path):
        """Test successful extraction and caching of an OCI image file."""

        # Create test tar file
        tar_path = _create_oci_tar(
            tmp_path, image_name="test-image", digest="sha256abc123"
        )

        cache = ImageCache(tmp_path)

        result = cache.extract_cache_file(tar_path)

        assert result["ref"] == "test-image"
        assert result["hash"] == "sha256abc123"
        assert (tmp_path / "extract" / "sha256abc123").is_dir()
        assert (tmp_path / "extract" / "sha256abc123" / "oci-layout").exists()
        assert (tmp_path / "save" / "sha256abc123" / "image.img").exists()

    def test_extract_cache_file_missing_oci_layout_raises(self, tmp_path):
        """Test that missing oci-layout file raises ImageDirFormatException."""

        # Create tar without oci-layout
        tar_path = tmp_path / "bad.tar"
        with tarfile.open(tar_path, "w") as tar:
            # Only add index.json without oci-layout
            index_content = json.dumps(
                {
                    "schemaVersion": 2,
                    "manifests": [
                        {
                            "digest": "sha256abc",
                            "annotations": {"io.containerd.image.name": "test"},
                        }
                    ],
                }
            ).encode("utf-8")
            index_info = tarfile.TarInfo(name="index.json")
            index_info.size = len(index_content)
            tar.addfile(index_info, io.BytesIO(index_content))

        cache = ImageCache(tmp_path)

        with pytest.raises(ImageDirFormatException) as exc_info:
            cache.extract_cache_file(tar_path)

        assert "not in valid OCI format" in str(exc_info.value)

    def test_extract_cache_file_missing_ref_raises(self, tmp_path):
        """Test that missing io.containerd.image.name raises ImageDirFormatException."""

        # Create tar with oci-layout but missing ref annotation
        tar_path = _create_oci_tar(tmp_path, image_name=None, digest="sha256abc123")
        # Rewrite tar without the annotation
        tar_path2 = tmp_path / "test_image2.tar"
        with tarfile.open(tar_path2, "w") as tar:
            oci_layout_content = json.dumps({"imageLayoutVersion": "1.0.0"}).encode(
                "utf-8"
            )
            oci_layout_info = tarfile.TarInfo(name="oci-layout")
            oci_layout_info.size = len(oci_layout_content)
            tar.addfile(oci_layout_info, io.BytesIO(oci_layout_content))

            index_content = json.dumps(
                {
                    "schemaVersion": 2,
                    "manifests": [{"digest": "sha256abc123"}],  # No annotations
                }
            ).encode("utf-8")
            index_info = tarfile.TarInfo(name="index.json")
            index_info.size = len(index_content)
            tar.addfile(index_info, io.BytesIO(index_content))

        cache = ImageCache(tmp_path)

        with pytest.raises(ImageDirFormatException) as exc_info:
            cache.extract_cache_file(tar_path2)

        assert "does not contain expected io.containerd.image.name metadata" in str(
            exc_info.value
        )

    def test_extract_cache_file_missing_digest_raises(self, tmp_path):
        """Test that missing digest raises ImageDirFormatException."""

        # Create tar with oci-layout but missing digest
        tar_path = tmp_path / "test_image3.tar"
        with tarfile.open(tar_path, "w") as tar:
            oci_layout_content = json.dumps({"imageLayoutVersion": "1.0.0"}).encode(
                "utf-8"
            )
            oci_layout_info = tarfile.TarInfo(name="oci-layout")
            oci_layout_info.size = len(oci_layout_content)
            tar.addfile(oci_layout_info, io.BytesIO(oci_layout_content))

            index_content = json.dumps(
                {
                    "schemaVersion": 2,
                    "manifests": [
                        {"annotations": {"io.containerd.image.name": "test"}}
                    ],  # No digest
                }
            ).encode("utf-8")
            index_info = tarfile.TarInfo(name="index.json")
            index_info.size = len(index_content)
            tar.addfile(index_info, io.BytesIO(index_content))

        cache = ImageCache(tmp_path)

        with pytest.raises(ImageDirFormatException) as exc_info:
            cache.extract_cache_file(tar_path)

        assert "does not contain digest metadata" in str(exc_info.value)

    def test_extract_cache_file_populates_extract_cache(self, tmp_path):
        """Test that extract_cache is populated after extraction."""

        tar_path = _create_oci_tar(
            tmp_path, image_name="test-image", digest="sha256hash1"
        )

        cache = ImageCache(tmp_path)

        cache.extract_cache_file(tar_path)

        assert "sha256hash1" in cache.extract_cache
        assert cache.extract_cache["sha256hash1"].is_dir()

    def test_extract_cache_file_populates_save_cache(self, tmp_path):
        """Test that save_cache is populated after extraction."""

        tar_path = _create_oci_tar(
            tmp_path, image_name="test-image", digest="sha256hash1"
        )

        cache = ImageCache(tmp_path)

        cache.extract_cache_file(tar_path)

        assert "sha256hash1" in cache.save_cache
        assert cache.save_cache["sha256hash1"].exists()

    def test_extract_cache_file_content(self, tmp_path):
        """Test that extract_cache_file correctly extracts and validates file contents."""
        # Create test tar file with specific content
        tar_path = _create_oci_tar(
            tmp_path, image_name="content-test-image", digest="sha256content123"
        )

        cache = ImageCache(tmp_path)

        result = cache.extract_cache_file(tar_path)

        # Validate returned metadata
        assert result["ref"] == "content-test-image"
        assert result["hash"] == "sha256content123"

        # Validate extraction directory structure
        extract_dir = tmp_path / "extract" / "sha256content123"
        assert extract_dir.is_dir()
        assert (extract_dir / "oci-layout").is_file()
        assert (extract_dir / "index.json").is_file()

        # Verify oci-layout contains the expected version
        oci_layout_content = (extract_dir / "oci-layout").read_text()
        assert oci_layout_content == '{"imageLayoutVersion": "1.0.0"}'

        # Verify index.json contains the expected manifest content
        index_content = json.loads((extract_dir / "index.json").read_text())
        assert index_content["schemaVersion"] == 2
        manifest_section = index_content["manifests"][0]
        assert (
            manifest_section["mediaType"]
            == "application/vnd.oci.image.manifest.v1+json"
        )
        assert manifest_section["size"] == 42
        assert (
            manifest_section["annotations"]["io.containerd.image.name"]
            == "content-test-image"
        )
        assert manifest_section["digest"] == "sha256content123"

        # Validate save cache entry exists
        save_image_path = tmp_path / "save" / "sha256content123" / "image.img"
        assert save_image_path.exists()

    def test_extract_cache_file_strips_sha256_prefix(self, tmp_path):
        """Test that sha256: prefix is stripped from digest in returned metadata and cache keys."""
        tar_path = _create_oci_tar(
            tmp_path, image_name="prefix-test-image", digest="sha256:abc123def"
        )

        cache = ImageCache(tmp_path)

        result = cache.extract_cache_file(tar_path)

        # Verify the sha256: prefix is stripped in the returned metadata
        assert result["hash"] == "abc123def"
        assert "sha256:" not in result["hash"]

        # Verify the extract cache uses the stripped hash as key
        assert "abc123def" in cache.extract_cache
        assert cache.extract_cache["abc123def"].is_dir()

        # Verify the save cache uses the stripped hash as key
        assert "abc123def" in cache.save_cache
        assert cache.save_cache["abc123def"].exists()

        # Verify the actual directory names don't have the prefix
        assert (tmp_path / "extract" / "abc123def").is_dir()
        assert (tmp_path / "save" / "abc123def" / "image.img").exists()


class TestImageCacheExtractCacheImage:
    """Tests for ImageCache.extract_cache_image method."""

    def test_extract_cache_image_existing_in_cache(self, tmp_path):
        """Test that extract_cache_image returns cached image when already extracted."""
        tar_path = _create_oci_tar(
            tmp_path, image_name="test-image", digest="sha256hash1"
        )

        cache = ImageCache(tmp_path)

        # First extract to populate cache
        cache.extract_cache_file(tar_path)

        # Verify we get the same path for existing cache
        image = {"ref": "test-image", "hash": "sha256hash1"}
        result = cache.extract_cache_image(image)

        assert result == cache.extract_cache["sha256hash1"]
        assert result.is_dir()

    def test_extract_cache_image_not_in_cache(self, tmp_path):
        """Test that extract_cache_image extracts when not in cache."""
        tar_path = _create_oci_tar(
            tmp_path, image_name="test-image", digest="sha256hash2"
        )
        cache = ImageCache(tmp_path)

        # Extract to save cache first
        cache.extract_cache_file(tar_path)

        # We must clear the extract_cache directory so that cache2 does not find it in extract_cache,
        # but finds it in save_cache
        shutil.rmtree(tmp_path / "extract" / "sha256hash2")

        # Create new ImageCache to simulate fresh start
        cache2 = ImageCache(tmp_path)

        # Now extract_cache_image should extract from save cache
        image = {"ref": "test-image", "hash": "sha256hash2"}
        result = cache2.extract_cache_image(image)

        assert result.is_dir()
        assert (result / "oci-layout").exists()

    def test_extract_cache_image_not_in_either_cache(self, tmp_path, monkeypatch):
        """Test that extract_cache_image saves and then extracts when not in either cache."""
        # Create a dummy tar to use as the saved file
        tar_path = _create_oci_tar(
            tmp_path, image_name="test-image", digest="sha256hash3"
        )

        # Mock save_image_to_file to copy the dummy tar in place of pulling from docker
        def fake_save_image_to_file(image, file):
            shutil.copy(tar_path, file)

        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.image_cache.save_image_to_file",
            fake_save_image_to_file,
        )

        cache = ImageCache(tmp_path)
        image = {"ref": "test-image", "hash": "sha256hash3"}
        result = cache.extract_cache_image(image)

        assert result.is_dir()
        assert (result / "oci-layout").exists()

        # Verify it was added to both caches
        assert "sha256hash3" in cache.save_cache
        assert "sha256hash3" in cache.extract_cache


class TestImageCacheSaveCacheImage:
    """Tests for ImageCache.save_cache_image method."""

    def test_save_cache_image_new_image(self, tmp_path, monkeypatch):
        """Test that save_cache_image saves new image to cache."""
        # Track calls to save_image_to_file
        calls = []

        def fake_save_image_to_file(image, file):
            file.touch()
            calls.append((image, file))

        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.image_cache.save_image_to_file",
            fake_save_image_to_file,
        )

        tar_path = _create_oci_tar(
            tmp_path, image_name="test-image", digest="sha256oldhash"
        )
        cache = ImageCache(tmp_path)

        # First extract to populate save cache
        cache.extract_cache_file(tar_path)

        # Create new cache and save an image
        cache2 = ImageCache(tmp_path)
        image = {"ref": "new-image", "hash": "sha256newhash"}

        result = cache2.save_cache_image(image)

        assert result.exists()
        assert len(calls) == 1

    def test_save_cache_image_existing_image_updates_timestamp(self, tmp_path):
        """Test that save_cache_image updates file timestamp for existing image."""
        import os

        tar_path = _create_oci_tar(
            tmp_path, image_name="test-image", digest="sha256touchhash"
        )
        cache = ImageCache(tmp_path)

        # First extract to populate save cache
        cache.extract_cache_file(tar_path)

        # Get initial stat
        image_file = cache.save_cache["sha256touchhash"]
        initial_mtime = os.path.getmtime(image_file)

        # Wait a moment and call save_cache_image again
        import time

        time.sleep(0.1)

        cache2 = ImageCache(tmp_path)
        image = {"ref": "test-image", "hash": "sha256touchhash"}

        result = cache2.save_cache_image(image)

        # Timestamp should be updated
        final_mtime = os.path.getmtime(result)
        assert (
            final_mtime > initial_mtime
        ), "File timestamp should be updated for existing image"


class TestImageCacheExtractOciFile:
    """Tests for ImageCache._extract_oci_file method."""

    def test_extract_oci_file_success(self, tmp_path):
        """Test that _extract_oci_file successfully extracts a valid OCI file and validates layout."""
        tar_path = tmp_path / "test.tar"
        with tarfile.open(tar_path, "w") as tar:
            oci_layout_content = json.dumps({"imageLayoutVersion": "1.0.0"}).encode(
                "utf-8"
            )
            oci_layout_info = tarfile.TarInfo(name="oci-layout")
            oci_layout_info.size = len(oci_layout_content)
            tar.addfile(oci_layout_info, io.BytesIO(oci_layout_content))

            # Add a dummy file to verify extraction
            dummy_content = b"dummy"
            dummy_info = tarfile.TarInfo(name="dummy.txt")
            dummy_info.size = len(dummy_content)
            tar.addfile(dummy_info, io.BytesIO(dummy_content))

        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()

        cache = ImageCache(tmp_path)
        cache._extract_oci_file(extract_dir, tar_path)

        # Validate folder layout
        assert (extract_dir / "oci-layout").exists()
        assert (extract_dir / "dummy.txt").exists()
        with open(extract_dir / "oci-layout", "r") as f:
            assert json.load(f) == {"imageLayoutVersion": "1.0.0"}

    def test_extract_oci_file_missing_oci_layout_raises(self, tmp_path):
        """Test that _extract_oci_file raises ImageDirFormatException if oci-layout is missing."""
        tar_path = tmp_path / "bad.tar"
        with tarfile.open(tar_path, "w") as tar:
            # Add a dummy file to verify extraction without oci-layout
            dummy_content = b"dummy"
            dummy_info = tarfile.TarInfo(name="dummy.txt")
            dummy_info.size = len(dummy_content)
            tar.addfile(dummy_info, io.BytesIO(dummy_content))

        extract_dir = tmp_path / "extract_bad"
        extract_dir.mkdir()

        cache = ImageCache(tmp_path)

        with pytest.raises(ImageDirFormatException) as exc_info:
            cache._extract_oci_file(extract_dir, tar_path)

        assert "not in valid OCI format" in str(exc_info.value)
        # Verify it actually extracted the other files before failing
        assert (extract_dir / "dummy.txt").exists()

    def test_extract_oci_file_uses_filter_tar(self, tmp_path, monkeypatch):
        """Test that _extract_oci_file uses filter="tar" parameter."""

        tar_path = tmp_path / "test.tar"
        with tarfile.open(tar_path, "w") as tar:
            oci_layout_content = json.dumps({"imageLayoutVersion": "1.0.0"}).encode(
                "utf-8"
            )
            oci_layout_info = tarfile.TarInfo(name="oci-layout")
            oci_layout_info.size = len(oci_layout_content)
            tar.addfile(oci_layout_info, io.BytesIO(oci_layout_content))

        extract_dir = tmp_path / "extract"
        extract_dir.mkdir(exist_ok=True)

        # Track the filter parameter used in extractall
        captured_params = {}

        original_extractall = tarfile.TarFile.extractall

        def mock_extractall(self, path, members=None, *, numeric_owner=False, **kwargs):
            captured_params.update(kwargs)
            return original_extractall(
                self, path, members, numeric_owner=numeric_owner, filter="tar"
            )

        monkeypatch.setattr(tarfile.TarFile, "extractall", mock_extractall)

        cache = ImageCache(tmp_path)
        cache._extract_oci_file(extract_dir, tar_path)

        assert "filter" in captured_params
        assert captured_params["filter"] == "tar"
