import json
import logging
import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Optional

from mender_docker_lifecycle_helper.utils.container_utils import (
    HASH_PREFIX,
    save_image_to_file,
)
from mender_docker_lifecycle_helper.utils.deep_delta import oci_deep_delta

DELTA_CACHE_DIRNAME = "delta"
EXTRACT_CACHE_DIRNAME = "extract"
IMAGE_FILE_NAME = "image.img"
OCI_LAYOUT_FILENAME = "oci-layout"
OCI_INDEX_FILENAME = "index.json"
SAVE_CACHE_DIRNAME = "save"


class ImageDirFormatException(Exception):
    """Raised when an OCI image directory is not in the expected format."""

    pass


class ImageCache:
    """
    Represents a cache of container images archive files, extractions of those archives, and files of the computed deltas between images. Images are referenced in the cache by manifest hash (and from/to hashes for deltas), and can be specified for inclusion in the cache by image ref and hash, or by OCI image filename.
    """

    def __init__(
        self,
        cache_dir: Path,
        delta_cache_dirname: Optional[str] = DELTA_CACHE_DIRNAME,
        extract_cache_dirname: Optional[str] = EXTRACT_CACHE_DIRNAME,
        image_file_name: Optional[str] = IMAGE_FILE_NAME,
        save_cache_dirname: Optional[str] = SAVE_CACHE_DIRNAME,
        logger: Optional[logging.Logger] = logging.getLogger(__name__),
    ):
        """
        Construct an ImageCache object, reading cache dir contents into maps if present or creating them as empty dirs.

        :param cache_dir: The top-level directory of the image cache.
        :param delta_cache_dirname: The name of the subdirectory for image deltas, defaults to DELTA_CACHE_DIRNAME.
        :param extract_cache_dirname: The name of the subdirectory for image extracts, defaults to EXTRACT_CACHE_DIRNAME.
        :param image_file_name: The filename to use for image save files, defaults to IMAGE_FILE_NAME.
        :param save_cache_dirname: The name of the subdirectory for image saves, defaults to SAVE_CACHE_DIRNAME.
        :param logger: A logger with which to log steps of cache processes, defaults to logging.getLogger(__name__).
        """
        self.logger = logger
        self.image_file_name = image_file_name
        self.cache_dir = cache_dir

        cache_dir.mkdir(parents=True, exist_ok=True)
        self.delta_cache_dir = cache_dir / delta_cache_dirname
        self.delta_cache_dir.mkdir(exist_ok=True)
        self.delta_cache = {
            from_dir.name: {
                to_dir.name: to_dir / image_file_name
                for to_dir in from_dir.iterdir()
                if to_dir.is_dir()
            }
            for from_dir in self.delta_cache_dir.iterdir()
            if from_dir.is_dir()
        }
        self.extract_cache_dir = cache_dir / extract_cache_dirname
        self.extract_cache_dir.mkdir(exist_ok=True)
        self.extract_cache = {
            hash_dir.name: hash_dir
            for hash_dir in self.extract_cache_dir.iterdir()
            if hash_dir.is_dir()
        }
        self.save_cache_dir = cache_dir / save_cache_dirname
        self.save_cache_dir.mkdir(exist_ok=True)
        self.save_cache = {
            hash_dir.name: hash_dir / image_file_name
            for hash_dir in self.save_cache_dir.iterdir()
            if hash_dir.is_dir()
        }

    def delta(
        self, from_image: dict[str, str], to_image: dict[str, str], target_platform: str
    ) -> Path:
        """
        Get the delta file path for a given from and to image hash, creating folders if required.

        :param from_image: The metadata (specifically {ref: <ref>, hash: <hash>}) of the image from which the delta is defined.
        :param to_image: The metadata (specifically {ref: <ref>, hash: <hash>}) of the image to which the delta is defined.
        :param target_platform: The platform to target, if the image contains multiple, as os/[architecture]/[variant].
        :return: The path to the delta file for the given from and to image hash.
        """
        from_hash = from_image["hash"]
        to_hash = to_image["hash"]

        if to_hash in self.delta_cache.get(from_hash, {}):
            delta_file = self.delta_cache[from_hash][to_hash]
            self.logger.debug(
                f"Found cached delta file {delta_file} for from hash {from_hash} to hash {to_hash}."
            )
            # Update the file timestamp for cache cleanup logic
            delta_file.touch()
            return delta_file
        else:
            delta_dir = self.delta_cache_dir / from_hash / to_hash
            self.logger.debug(
                f"Creating delta for {from_hash} to {to_hash} under {delta_dir}..."
            )
            delta_file = oci_deep_delta(
                self.extract_cache_image(from_image),
                self.extract_cache_image(to_image),
                delta_dir,
                self.image_file_name,
                target_platform,
                logger=self.logger,
            )
            if from_hash not in self.delta_cache:
                self.delta_cache[from_hash] = {}
            self.delta_cache[from_hash][to_hash] = delta_file

            return delta_file

    def _extract_oci_file(self, extract_dir: Path, extract_file: Path) -> None:
        """
        Extract specified OCI image file into specified directory, and ensure OCI-compliant layout.

        :param extract_dir: The path into which to extract the OCI file.
        :param extract_file: The OCI file to extract.
        :raises ImageDirFormatException: Indicates that the specified image file is not in the correct format.
        :return: None.
        """
        with tarfile.open(extract_file, "r:*") as tar:
            tar.extractall(
                path=extract_dir,
                filter="tar",
            )

        if not (extract_dir / OCI_LAYOUT_FILENAME).exists():
            raise ImageDirFormatException(
                f"{extract_file} as extracted to {extract_dir} is not in valid OCI format."
            )

    def extract_cache_file(self, extract_file: Path) -> dict[str, str]:
        """
        Extract image from a specified file to the cache and read and return the image metadata.

        :param extract_file: The path to the OCI image archive file to extract into the cache space.
        :raises ImageDirFormatException: Indicates that the specified image file is not in the correct format.
        :return: The image specification (as {ref: <ref>, hash: <hash>}) as read from the file.
        """

        image_ref = ""
        image_hash = ""
        with tempfile.TemporaryDirectory(
            dir=self.extract_cache_dir
        ) as temp_extract_dir:
            temp_extract_dir = Path(temp_extract_dir)
            self.logger.debug(
                f"Extracting {extract_file} into temp dir {temp_extract_dir}"
            )
            self._extract_oci_file(temp_extract_dir, extract_file)

            image_index = {}
            with open(temp_extract_dir / OCI_INDEX_FILENAME) as index_file:
                image_index = json.load(index_file)

            image_manifest = image_index.get("manifests", [{}])[0]
            # Check index annotations first (for index-descriptor annotations from buildx)
            # then fall back to manifest annotations
            image_ref = image_index.get("annotations", {}).get(
                "io.containerd.image.name", None
            )
            if image_ref is None:
                image_ref = image_manifest.get("annotations", {}).get(
                    "io.containerd.image.name", None
                )
            image_hash = image_manifest.get("digest", None)
            if image_hash is not None:
                image_hash = image_hash.removeprefix(f"{HASH_PREFIX}:")
            if image_ref is None:
                raise ImageDirFormatException(
                    f"{extract_file} as extracted to {temp_extract_dir} does not contain expected io.containerd.image.name metadata in its index."
                )
            if image_hash is None:
                raise ImageDirFormatException(
                    f"{extract_file} as extracted to {temp_extract_dir} does not contain digest metadata in its index."
                )

            image_extract_cache_dir = self.extract_cache_dir / image_hash
            self.logger.debug(
                f"Saving extracted image contents from {extract_file} to cache {image_extract_cache_dir}"
            )
            shutil.move(temp_extract_dir, image_extract_cache_dir)
            self.extract_cache[image_hash] = image_extract_cache_dir

        image_save_cache_folder = self.save_cache_dir / image_hash
        image_save_cache_folder.mkdir(parents=True, exist_ok=True)
        image_save_cache_file = image_save_cache_folder / self.image_file_name
        self.logger.debug(
            f"Saving image file {extract_file} to cache {image_save_cache_file}"
        )
        shutil.copy(extract_file, image_save_cache_file)
        self.save_cache[image_hash] = image_save_cache_file
        return {
            "ref": image_ref,
            "hash": image_hash,
        }

    def extract_cache_image(self, image: dict[str, str]) -> Path:
        """
        Extract an image with the given hash in the cache and return the path to the extracted image dir. If the image is not yet in the image save cache, it will be added there first.

        :param image: The metadata (specifically {ref: <ref>, hash: <hash>}) of the image to extract.
        :return: The path to the extracted image directory.
        """
        image_hash = image["hash"]
        if image_hash in self.extract_cache:
            self.logger.debug(
                f"Image {image['ref']} with hash {image_hash} already saved in cache at {self.extract_cache[image_hash]}."
            )
            return self.extract_cache[image_hash]

        image_file = self.save_cache_image(image)
        self.logger.debug(
            f"Extracting image file {image_file} with hash {image_hash} to cache."
        )
        extract_dir = self.extract_cache_dir / image_hash
        extract_dir.mkdir()
        self._extract_oci_file(extract_dir, image_file)
        self.extract_cache[image_hash] = extract_dir
        return extract_dir

    def save_cache_image(self, image: dict[str, str]) -> Path:
        """
        Save an image with the given ref and hash to the save cache, if not already present.

        :param image: The metadata (specifically {ref: <ref>, hash: <hash>}) of the image to save.
        :return: The path to the image file in the save cache.
        """
        image_hash = image["hash"]
        if image_hash in self.save_cache:
            save_image_file = self.save_cache[image_hash]
            self.logger.debug(
                f"Image with hash {image_hash} already saved in cache at {save_image_file}."
            )
            # Update the file timestamp for cache cleanup logic
            save_image_file.touch()
            return save_image_file
        else:
            save_image_dir = self.save_cache_dir / image_hash
            self.logger.debug(
                f"Saving image with hash {image_hash} for ref {image['ref']} to cache at {save_image_dir}."
            )
            save_image_dir.mkdir(parents=True, exist_ok=True)
            save_image_file = save_image_dir / self.image_file_name
            save_image_to_file(image, save_image_file)
            self.logger.debug(f"Image file {save_image_file} saved.")
            self.save_cache[image_hash] = save_image_file
            return save_image_file

    def cleanup_by_mtime(
        self,
        limit_size_bytes: Optional[int] = None,
        disk_percent: Optional[float] = None,
    ) -> int:
        """
        Remove oldest cached items to bring cache size at or below limit.

        Only folder items (save/<hash>, extract/<hash>, delta/<from>/<to>) are removed.

        :param limit_size_bytes: Maximum cache size in bytes. If None with disk_percent,
            no cleanup occurs.
        :param disk_percent: If set, calculate free space needed as percent of total disk.
        :return: Total bytes freed by cleanup.
        """
        current_size = self._get_cache_size()
        bytes_freed = 0

        if disk_percent is not None:
            space_to_free = self._calculate_space_to_free_for_percent(
                disk_percent, current_size
            )
        elif limit_size_bytes is not None:
            space_to_free = current_size - limit_size_bytes
        else:
            self.logger.debug("No cleanup limit specified, skipping cleanup.")
            return 0

        if space_to_free <= 0:
            self.logger.debug("Cache size already within limits, skipping cleanup.")
            return 0

        self.logger.info(
            f"Cache cleanup triggered, need to free {space_to_free} bytes."
        )

        items = self._get_cache_items_by_mtime()
        for item_path, mtime, size in items:
            if space_to_free <= 0:
                break

            self.logger.debug(f"Removing cache item {item_path} ({size} bytes).")
            try:
                shutil.rmtree(item_path)
                bytes_freed += size
                space_to_free -= size
                self.logger.info(
                    f"Removed {item_path}, freed {bytes_freed} bytes so far."
                )
            except Exception as e:
                self.logger.warning(f"Failed to remove {item_path}: {e}")

        self._sync_cache_dicts_on_cleanup()
        return bytes_freed

    def _get_cache_size(self) -> int:
        """
        Calculate total size of the images cache directory.

        :return: Total size in bytes.
        """
        total = 0
        for subdir in [
            self.save_cache_dir,
            self.extract_cache_dir,
            self.delta_cache_dir,
        ]:
            for path in subdir.rglob("*"):
                if path.is_file():
                    total += path.stat().st_size
        return total

    def _get_disk_stats(self) -> dict:
        """
        Get disk usage stats for the filesystem containing the cache.

        :return: Dictionary with 'total' and 'free' keys in bytes.
        """
        stat = os.statvfs(self.cache_dir)
        return {
            "total": stat.f_blocks * stat.f_frsize,
            "free": stat.f_bavail * stat.f_frsize,
        }

    def _calculate_space_to_free_for_percent(
        self, disk_percent: float, current_cache_size: int
    ) -> int:
        """
        Calculate how much space needs to be freed to meet the disk percent threshold.

        :param disk_percent: Minimum percent of total disk that should remain free.
        :param current_cache_size: Current cache size in bytes.
        :return: Bytes to free, or 0 if no cleanup needed or cache is already within limits.
        """
        stats = self._get_disk_stats()
        min_free_bytes = int(stats["total"] * disk_percent / 100)
        current_free = stats["free"]
        additional_needed = min_free_bytes - current_free

        if additional_needed <= 0:
            return 0

        # We can only free up to the current cache size
        return min(additional_needed, current_cache_size)

    def _get_cache_items_by_mtime(self) -> list[tuple[Path, float, int]]:
        """
        Get all cache items ordered by modification time.

        :return: List of (path, mtime, size) tuples. Items are always directories:
            save/<hash>, extract/<hash>, delta/<from>/<to>.
        """
        items = []
        for hash_dir in self.save_cache_dir.iterdir():
            if hash_dir.is_dir():
                mtime = hash_dir.stat().st_mtime
                size = self._get_dir_size(hash_dir)
                items.append((hash_dir, mtime, size))

        for hash_dir in self.extract_cache_dir.iterdir():
            if hash_dir.is_dir():
                mtime = hash_dir.stat().st_mtime
                size = self._get_dir_size(hash_dir)
                items.append((hash_dir, mtime, size))

        for from_dir in self.delta_cache_dir.iterdir():
            if from_dir.is_dir():
                for to_dir in from_dir.iterdir():
                    if to_dir.is_dir():
                        mtime = to_dir.stat().st_mtime
                        size = self._get_dir_size(to_dir)
                        items.append((to_dir, mtime, size))

        return sorted(items, key=lambda x: x[1])

    def _get_dir_size(self, path: Path) -> int:
        """
        Recursively calculate total size of directory.

        :param path: The directory path to calculate size for.
        :return: Total size in bytes.
        """
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

    def _sync_cache_dicts_on_cleanup(self) -> None:
        """
        Remove entries from in-memory cache dicts after cleanup removes those dirs.

        :return: None.
        """
        for hash_dir in list(self.save_cache.keys()):
            if not (self.save_cache_dir / hash_dir).exists():
                del self.save_cache[hash_dir]

        for hash_dir in list(self.extract_cache.keys()):
            if not (self.extract_cache_dir / hash_dir).exists():
                del self.extract_cache[hash_dir]

        for from_hash in list(self.delta_cache.keys()):
            for to_hash in list(self.delta_cache[from_hash].keys()):
                delta_path = self.delta_cache_dir / from_hash / to_hash
                if not delta_path.exists():
                    del self.delta_cache[from_hash][to_hash]
            if not self.delta_cache[from_hash]:
                del self.delta_cache[from_hash]
