import json
import logging
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Optional

from mender_docker_lifecycle_helper.utils.container_utils import save_image_to_file
from mender_docker_lifecycle_helper.utils.deep_delta import oci_deep_delta

DELTA_CACHE_DIRNAME = "delta"
EXTRACT_CACHE_DIRNAME = "extract"
IMAGE_FILE_NAME = "image.img"
OCI_LAYOUT_FILENAME = "oci-layout"
OCI_INDEX_FILENAME = "index.json"
SAVE_CACHE_DIRNAME = "save"


class ImageDirFormatException(Exception):
    pass


class ImageCache:
    """
    Represents a cache of container images archive files, extractions of those archives, and files of the computed deltas between images. Images are referenced in the cache by manifest hash (and from/to hashes for deltas), and can be specified inclusion in the cache by image ref and hash, or by OCI image filename.
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
        :param delta_cache_dirname: The name of the subdirectory for image deltas.
        :param extract_cache_dirname: The name of the subdirectory for image extracts.
        :param image_filename: The filename to use for image save files.
        :param save_cache_dirname: The name of the subdirectory for image saves.
        :param logger: A logger with which to log steps of cache processes.
        """
        self.logger = logger
        self.image_file_name = image_file_name

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

    def delta(self, from_image: dict[str, str], to_image: dict[str, str]) -> Path:
        """
        Get the delta file path for a given from and to image hash, creating folders if required.

        :param from_image: The metadata (specifically {ref: <ref>, hash: <hash>}) of the image from which the delta is defined.
        :param to_image: The metadata (specifically {ref: <ref>, hash: <hash>}) of the image to which the delta is defined.

        :returns: The path to the delta file for the given from and to image hash.
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

        :returns: None

        :raises ImageDirFormatException: indicates that the specified image file is not in the correct format.
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
        :returns: The image specification (as {ref: <ref>, hash: <hash>}) as read from the file.

        :raises ImageDirFormatException: indicates that the specified image file is not in the correct format.
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
            image_ref = image_manifest.get("annotations", {}).get(
                "io.containerd.image.name", None
            )
            image_hash = image_manifest.get("digest", None)
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

        :returns: The path to the extracted image directory.
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
        :returns: The path to the image file in the save cache.
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
