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


class TestImageCacheCleanup:
    """Tests for ImageCache.cleanup_by_mtime method."""

    def _create_cache_item(
        self, cache_dir, item_type, hash1, hash2=None, size_bytes=100
    ):
        """Helper to create a cache item with specific size and modification time."""
        if item_type == "save":
            item_dir = cache_dir / "save" / hash1
            item_dir.mkdir(parents=True)
            image_file = item_dir / "image.img"
            image_file.write_bytes(b"x" * size_bytes)
            return image_file.parent
        elif item_type == "extract":
            item_dir = cache_dir / "extract" / hash1
            item_dir.mkdir(parents=True)
            dummy_file = item_dir / "dummy.txt"
            dummy_file.write_bytes(b"x" * size_bytes)
            return dummy_file.parent
        elif item_type == "delta":
            item_dir = cache_dir / "delta" / hash1 / hash2
            item_dir.mkdir(parents=True)
            image_file = item_dir / "image.img"
            image_file.write_bytes(b"x" * size_bytes)
            return image_file.parent

    def test_cleanup_removes_oldest_items_first(self, tmp_path):
        """Test that cleanup removes oldest items first (LRU behavior)."""
        import time

        cache = ImageCache(tmp_path)

        # Create items with different ages
        old_item = self._create_cache_item(tmp_path, "save", "old_hash", size_bytes=100)
        time.sleep(0.01)
        newer_item = self._create_cache_item(
            tmp_path, "save", "newer_hash", size_bytes=100
        )
        time.sleep(0.01)
        newest_item = self._create_cache_item(
            tmp_path, "save", "newest_hash", size_bytes=100
        )

        # Set oldest item even older by touching it first, then waiting
        time.sleep(0.01)
        newest_item.touch()

        # Cleanup to free 100 bytes - should remove oldest
        bytes_freed = cache.cleanup_by_mtime(limit_size_bytes=200)

        assert bytes_freed > 0
        # Oldest item should be removed
        assert not old_item.exists(), "Oldest item should be removed"
        # Newer items should remain
        assert newest_item.exists(), "Newest item should remain"

    def test_cleanup_respects_limit_size(self, tmp_path):
        """Test that cleanup respects size limit."""
        cache = ImageCache(tmp_path)

        # Create items totaling 300 bytes
        item1 = self._create_cache_item(tmp_path, "save", "hash1", size_bytes=100)
        item2 = self._create_cache_item(tmp_path, "save", "hash2", size_bytes=100)
        item3 = self._create_cache_item(tmp_path, "save", "hash3", size_bytes=100)

        # Calculate sizes
        total_size = sum(
            [
                cache._get_dir_size(item1),
                cache._get_dir_size(item2),
                cache._get_dir_size(item3),
            ]
        )
        # Cleanup to leave only 150 bytes
        bytes_freed = cache.cleanup_by_mtime(limit_size_bytes=150)

        assert bytes_freed > 0
        remaining_size = cache._get_cache_size()
        assert remaining_size <= 150, f"Expected <= 150 bytes, got {remaining_size}"

    def test_cleanup_no_op_when_within_limit(self, tmp_path):
        """Test that cleanup is a no-op when already within limits."""
        cache = ImageCache(tmp_path)

        # Create small cache items
        self._create_cache_item(tmp_path, "save", "hash1", size_bytes=100)

        # Cleanup with large limit - should do nothing
        bytes_freed = cache.cleanup_by_mtime(limit_size_bytes=10000)
        assert bytes_freed == 0

    def test_cleanup_no_limit_returns_zero(self, tmp_path):
        """Test that cleanup returns 0 when no limits specified."""
        cache = ImageCache(tmp_path)

        self._create_cache_item(tmp_path, "save", "hash1", size_bytes=100)

        bytes_freed = cache.cleanup_by_mtime()
        assert bytes_freed == 0

    def test_cleanup_handles_extract_items(self, tmp_path):
        """Test that cleanup properly handles extract cache items."""
        cache = ImageCache(tmp_path)

        # Create extract cache item
        item = self._create_cache_item(
            tmp_path, "extract", "extract_hash", size_bytes=100
        )

        bytes_freed = cache.cleanup_by_mtime(limit_size_bytes=50)
        assert bytes_freed > 0
        assert not item.exists()

    def test_cleanup_handles_delta_items(self, tmp_path):
        """Test that cleanup properly handles delta cache items."""
        cache = ImageCache(tmp_path)

        # Create delta cache item
        item = self._create_cache_item(
            tmp_path, "delta", "from_hash", "to_hash", size_bytes=100
        )

        bytes_freed = cache.cleanup_by_mtime(limit_size_bytes=50)
        assert bytes_freed > 0
        assert not item.exists()

    def test_cleanup_synced_with_in_memory_caches(self, tmp_path):
        """Test that cleanup removes entries from in-memory cache dicts."""
        cache = ImageCache(tmp_path)

        # Create and populate caches
        item = self._create_cache_item(tmp_path, "save", "save_hash", size_bytes=100)
        cache = ImageCache(tmp_path)  # Re-init to populate dicts from disk
        assert "save_hash" in cache.save_cache

        # Cleanup
        cache.cleanup_by_mtime(limit_size_bytes=50)

        # Verify in-memory dict is synced
        assert "save_hash" not in cache.save_cache

    def test_cleanup_preserves_newer_items(self, tmp_path):
        """Test that newer items are preserved during cleanup."""
        import time

        cache = ImageCache(tmp_path)

        # Create items at different times
        old_item = self._create_cache_item(tmp_path, "save", "old", size_bytes=100)
        time.sleep(0.02)
        new_item = self._create_cache_item(tmp_path, "save", "new", size_bytes=100)

        # Touch to ensure time difference
        new_item.touch()

        # Cleanup
        cache.cleanup_by_mtime(limit_size_bytes=100)

        # New item should remain (or both removed if total size exceeded)
        # But newer should be preferred
        assert (
            new_item.exists() or not old_item.exists()
        ), "Newer items should be preserved"

    def test_cleanup_respects_percent_free(self, tmp_path, monkeypatch):
        """Test that cleanup respects disk percent free threshold."""
        cache = ImageCache(tmp_path)

        # Create items totaling 300 bytes
        item1 = self._create_cache_item(tmp_path, "save", "hash1", size_bytes=100)
        item2 = self._create_cache_item(tmp_path, "save", "hash2", size_bytes=100)
        item3 = self._create_cache_item(tmp_path, "save", "hash3", size_bytes=100)

        # Mock disk stats: 1000 byte total disk, 100 free
        # With 20% threshold, we need 200 free, so need to free 100 bytes
        def mock_statvfs(path):
            return type(
                "statvfs",
                (),
                {
                    "f_blocks": 10,  # 10 blocks
                    "f_frsize": 100,  # 100 bytes per block = 1000 total
                    "f_bavail": 1,  # 1 block free = 100 bytes free (only 10% free)
                    "f_bfree": 1,
                },
            )()

        monkeypatch.setattr("os.statvfs", mock_statvfs)

        # With 20% threshold on 1000 byte disk, we need 200 free
        # Only have 100 free, so need to free 100 bytes
        bytes_freed = cache.cleanup_by_mtime(disk_percent=20, limit_size_bytes=None)

        assert bytes_freed > 0, "Should have freed bytes to reach 20% free threshold"
        # Verify that cleanup happened by checking cache size reduced
        remaining_size = cache._get_cache_size()
        assert remaining_size < 300, "Cache size should be reduced"

    def test_cleanup_handles_missing_files(self, tmp_path, monkeypatch):
        """Test that cleanup logs warning and continues when file removal fails."""
        cache = ImageCache(tmp_path)

        # Create items
        item1 = self._create_cache_item(tmp_path, "save", "hash1", size_bytes=100)
        item2 = self._create_cache_item(tmp_path, "save", "hash2", size_bytes=100)

        # Re-init cache to ensure items are in the list
        cache = ImageCache(tmp_path)

        # Mock rmtree to always fail - cleanup should handle gracefully
        def mock_rmtree(path, *args, **kwargs):
            raise OSError("Simulated deletion failure")

        # Patch where shutil is used (in the image_cache module)
        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.image_cache.shutil.rmtree",
            mock_rmtree,
        )

        # Cleanup should not raise, should return 0 bytes freed
        bytes_freed = cache.cleanup_by_mtime(limit_size_bytes=50)

        # No bytes freed since all removals fail
        assert bytes_freed == 0, "Should have freed 0 bytes when all removals fail"

        # Items should still exist
        assert item1.exists()
        assert item2.exists()

    def test_cleanup_mixed_item_types(self, tmp_path):
        """Test that cleanup handles a mix of save, extract, and delta items."""
        cache = ImageCache(tmp_path)

        # Create items of different types
        save_item = self._create_cache_item(
            tmp_path, "save", "save_hash", size_bytes=100
        )
        extract_item = self._create_cache_item(
            tmp_path, "extract", "extract_hash", size_bytes=100
        )
        delta_item = self._create_cache_item(
            tmp_path, "delta", "from_hash", "to_hash", size_bytes=100
        )

        # Cleanup to free 150 bytes - should remove 2 items (oldest first)
        bytes_freed = cache.cleanup_by_mtime(limit_size_bytes=150)

        assert bytes_freed >= 100, "Should have freed at least 100 bytes"
        # At least one item should be removed
        remaining_items = sum(
            [
                (
                    len(list((tmp_path / "save").iterdir()))
                    if (tmp_path / "save").exists()
                    else 0
                ),
                (
                    len(list((tmp_path / "extract").iterdir()))
                    if (tmp_path / "extract").exists()
                    else 0
                ),
                (
                    sum(
                        len(list(d.iterdir()))
                        for d in (tmp_path / "delta").iterdir()
                        if d.is_dir()
                    )
                    if (tmp_path / "delta").exists()
                    else 0
                ),
            ]
        )
        assert remaining_items <= 2, "Should have removed at least one item"

    def test_cleanup_disk_percent_without_limit_size(self, tmp_path, monkeypatch):
        """Test that cleanup works with disk_percent even without limit_size_bytes."""
        cache = ImageCache(tmp_path)

        # Create items totaling 300 bytes
        self._create_cache_item(tmp_path, "save", "hash1", size_bytes=100)
        self._create_cache_item(tmp_path, "save", "hash2", size_bytes=100)
        self._create_cache_item(tmp_path, "save", "hash3", size_bytes=100)

        # Mock disk stats: 1000 byte total disk, 50 free
        # With 20% threshold, we need 200 free, so need to free 150 bytes
        def mock_statvfs(path):
            return type(
                "statvfs",
                (),
                {
                    "f_blocks": 10,
                    "f_frsize": 100,
                    "f_bavail": 0.5,  # 50 bytes free
                    "f_bfree": 0.5,
                },
            )()

        monkeypatch.setattr("os.statvfs", mock_statvfs)

        # Cleanup should trigger based on disk_percent alone
        bytes_freed = cache.cleanup_by_mtime(disk_percent=20)

        assert bytes_freed > 0, "Should have freed bytes based on disk_percent"

    def test_cleanup_empty_cache(self, tmp_path):
        """Test that cleanup handles an empty cache without error."""
        cache = ImageCache(tmp_path)

        # No items created
        bytes_freed = cache.cleanup_by_mtime(limit_size_bytes=100)

        assert bytes_freed == 0

    def test_get_cache_items_ordered_by_mtime(self, tmp_path):
        """Test that _get_cache_items_by_mtime returns items sorted by oldest first."""
        import time

        cache = ImageCache(tmp_path)

        # Create items at different times
        item1 = self._create_cache_item(tmp_path, "save", "first", size_bytes=100)
        time.sleep(0.01)
        item2 = self._create_cache_item(tmp_path, "save", "second", size_bytes=100)
        time.sleep(0.01)
        item3 = self._create_cache_item(tmp_path, "save", "third", size_bytes=100)

        items = cache._get_cache_items_by_mtime()

        # Should be ordered oldest first
        assert len(items) == 3
        assert items[0][0].name == "first"
        assert items[1][0].name == "second"
        assert items[2][0].name == "third"

    def test_cleanup_updates_in_memory_caches_after_mixed_removal(self, tmp_path):
        """Test that cleanup syncs all in-memory caches after removing mixed item types."""
        cache = ImageCache(tmp_path)

        # Create items of each type
        self._create_cache_item(tmp_path, "save", "save_hash", size_bytes=100)
        self._create_cache_item(tmp_path, "extract", "extract_hash", size_bytes=100)
        self._create_cache_item(
            tmp_path, "delta", "from_hash", "to_hash", size_bytes=100
        )

        # Re-init to populate dicts from disk
        cache = ImageCache(tmp_path)
        assert "save_hash" in cache.save_cache
        assert "extract_hash" in cache.extract_cache
        assert "from_hash" in cache.delta_cache

        # Cleanup to remove all items
        cache.cleanup_by_mtime(limit_size_bytes=50)

        # All caches should be empty
        assert "save_hash" not in cache.save_cache
        assert "extract_hash" not in cache.extract_cache
        assert "from_hash" not in cache.delta_cache

    def test_calculate_space_to_free_insufficient_cache(self, tmp_path, monkeypatch):
        """Test _calculate_space_to_free_for_percent when cache is smaller than needed."""
        cache = ImageCache(tmp_path)

        # Create a small cache item (10 bytes)
        self._create_cache_item(tmp_path, "save", "small_hash", size_bytes=10)

        # Mock disk stats: 10000 byte total disk, need to free 5000 bytes for 50% threshold
        # But cache only has ~10 bytes
        def mock_statvfs(path):
            return type(
                "statvfs",
                (),
                {
                    "f_blocks": 100,
                    "f_frsize": 100,
                    "f_bavail": 1,  # Only 100 bytes free
                    "f_bfree": 1,
                },
            )()

        monkeypatch.setattr("os.statvfs", mock_statvfs)

        # Re-init cache to get accurate size
        cache = ImageCache(tmp_path)
        space_needed = cache._calculate_space_to_free_for_percent(
            50, cache._get_cache_size()
        )

        # Should be capped at cache size (we can't free more than we have)
        assert space_needed <= cache._get_cache_size()

    def test_cleanup_partial_item_removes_whole_directory(self, tmp_path):
        """Test that cleanup removes entire directory even if only partial space is needed."""
        cache = ImageCache(tmp_path)

        # Create a single large item (500 bytes)
        item = self._create_cache_item(tmp_path, "save", "large_hash", size_bytes=500)

        # Cleanup to free only 100 bytes
        bytes_freed = cache.cleanup_by_mtime(limit_size_bytes=400)

        # The entire 500-byte directory should be removed (not partial)
        assert bytes_freed == 500
        assert not item.exists()

    def test_get_dir_size_empty_directory(self, tmp_path):
        """Test that _get_dir_size returns 0 for empty directory."""
        cache = ImageCache(tmp_path)
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        size = cache._get_dir_size(empty_dir)

        assert size == 0

    def test_get_disk_stats_returns_dict(self, tmp_path):
        """Test that _get_disk_stats returns correct dict structure."""
        cache = ImageCache(tmp_path)
        stats = cache._get_disk_stats()

        assert "total" in stats
        assert "free" in stats
        assert stats["total"] > 0
        assert stats["free"] >= 0

    def test_calculate_space_to_free_no_cleanup_needed(self, tmp_path, monkeypatch):
        """Test _calculate_space_to_free_for_percent returns 0 when already enough free space."""
        cache = ImageCache(tmp_path)

        # Mock disk stats: 1000 byte total disk, 500 free
        # With 20% threshold, we need 200 free, but we have 500 free
        # So additional_needed = 200 - 500 = -300 <= 0
        def mock_statvfs(path):
            return type(
                "statvfs",
                (),
                {
                    "f_blocks": 10,
                    "f_frsize": 100,
                    "f_bavail": 5,  # 500 bytes free
                    "f_bfree": 5,
                },
            )()

        monkeypatch.setattr("os.statvfs", mock_statvfs)

        space_to_free = cache._calculate_space_to_free_for_percent(20, 1000)

        # Should return 0 because we already have more free space than needed
        assert space_to_free == 0

    def test_calculate_space_to_free_exact_threshold(self, tmp_path, monkeypatch):
        """Test _calculate_space_to_free_for_percent returns 0 when exactly at threshold."""
        cache = ImageCache(tmp_path)

        # Mock disk stats: 1000 byte total disk, exactly at threshold
        # With 20% threshold, we need 200 free, and we have exactly 200 free
        # So additional_needed = 200 - 200 = 0 <= 0
        def mock_statvfs(path):
            return type(
                "statvfs",
                (),
                {
                    "f_blocks": 10,
                    "f_frsize": 100,
                    "f_bavail": 2,  # 200 bytes free (exactly 20%)
                    "f_bfree": 2,
                },
            )()

        monkeypatch.setattr("os.statvfs", mock_statvfs)

        space_to_free = cache._calculate_space_to_free_for_percent(20, 1000)

        # Should return 0 because additional_needed = 0
        assert space_to_free == 0

    def test_sync_cache_dicts_on_cleanup_removes_missing_save_entries(self, tmp_path):
        """Test that _sync_cache_dicts_on_cleanup removes save_cache entries for missing dirs."""
        cache = ImageCache(tmp_path)

        # Create and populate both caches
        save_item = self._create_cache_item(
            tmp_path, "save", "save_hash", size_bytes=100
        )
        cache = ImageCache(tmp_path)  # Re-init to populate dicts from disk
        assert "save_hash" in cache.save_cache

        # Manually remove the directory from filesystem
        shutil.rmtree(tmp_path / "save" / "save_hash")

        # Call sync method directly
        cache._sync_cache_dicts_on_cleanup()

        # Verify the in-memory dict entry is removed
        assert "save_hash" not in cache.save_cache

    def test_sync_cache_dicts_on_cleanup_removes_missing_extract_entries(
        self, tmp_path
    ):
        """Test that _sync_cache_dicts_on_cleanup removes extract_cache entries for missing dirs."""
        cache = ImageCache(tmp_path)

        # Create and populate both caches
        extract_item = self._create_cache_item(
            tmp_path, "extract", "extract_hash", size_bytes=100
        )
        cache = ImageCache(tmp_path)  # Re-init to populate dicts from disk
        assert "extract_hash" in cache.extract_cache

        # Manually remove the directory from filesystem
        shutil.rmtree(tmp_path / "extract" / "extract_hash")

        # Call sync method directly
        cache._sync_cache_dicts_on_cleanup()

        # Verify the in-memory dict entry is removed
        assert "extract_hash" not in cache.extract_cache

    def test_sync_cache_dicts_on_cleanup_removes_missing_delta_entries(self, tmp_path):
        """Test that _sync_cache_dicts_on_cleanup removes delta_cache entries for missing dirs."""
        cache = ImageCache(tmp_path)

        # Create and populate delta cache with two to_hashes to test nested removal
        self._create_cache_item(
            tmp_path, "delta", "from_hash", "to_hash1", size_bytes=100
        )
        self._create_cache_item(
            tmp_path, "delta", "from_hash", "to_hash2", size_bytes=100
        )
        cache = ImageCache(tmp_path)  # Re-init to populate dicts from disk
        assert "from_hash" in cache.delta_cache
        assert "to_hash1" in cache.delta_cache["from_hash"]
        assert "to_hash2" in cache.delta_cache["from_hash"]

        # Manually remove only one to_hash directory from filesystem
        shutil.rmtree(tmp_path / "delta" / "from_hash" / "to_hash1")

        # Call sync method directly
        cache._sync_cache_dicts_on_cleanup()

        # Verify only the missing entry is removed, other entries remain
        assert "to_hash1" not in cache.delta_cache["from_hash"]
        assert "to_hash2" in cache.delta_cache["from_hash"]
        # from_hash should still exist since to_hash2 is still there
        assert "from_hash" in cache.delta_cache

    def test_sync_cache_dicts_on_cleanup_removes_empty_delta_from_hash(self, tmp_path):
        """Test that _sync_cache_dicts_on_cleanup removes empty from_hash entries."""
        cache = ImageCache(tmp_path)

        # Create and populate delta cache
        delta_item = self._create_cache_item(
            tmp_path, "delta", "from_hash", "to_hash", size_bytes=100
        )
        cache = ImageCache(tmp_path)  # Re-init to populate dicts from disk
        assert "from_hash" in cache.delta_cache
        assert "to_hash" in cache.delta_cache["from_hash"]

        # Manually remove the only to_hash directory from filesystem
        shutil.rmtree(tmp_path / "delta" / "from_hash" / "to_hash")

        # Call sync method directly
        cache._sync_cache_dicts_on_cleanup()

        # Verify both to_hash and empty from_hash are removed
        assert "to_hash" not in cache.delta_cache.get("from_hash", {})
        assert "from_hash" not in cache.delta_cache

    def test_sync_cache_dicts_on_cleanup_handles_all_item_types(self, tmp_path):
        """Test that _sync_cache_dicts_on_cleanup handles mixed save, extract, and delta items."""
        cache = ImageCache(tmp_path)

        # Create all item types
        save_item = self._create_cache_item(
            tmp_path, "save", "save_hash", size_bytes=100
        )
        extract_item = self._create_cache_item(
            tmp_path, "extract", "extract_hash", size_bytes=100
        )
        delta_item = self._create_cache_item(
            tmp_path, "delta", "from_hash", "to_hash", size_bytes=100
        )

        # Re-init to populate dicts from disk
        cache = ImageCache(tmp_path)
        assert "save_hash" in cache.save_cache
        assert "extract_hash" in cache.extract_cache
        assert "from_hash" in cache.delta_cache

        # Remove only the save item from filesystem
        shutil.rmtree(tmp_path / "save" / "save_hash")

        # Call sync method directly
        cache._sync_cache_dicts_on_cleanup()

        # Only save_cache should be synced, others should remain
        assert "save_hash" not in cache.save_cache
        assert "extract_hash" in cache.extract_cache
        assert "from_hash" in cache.delta_cache
