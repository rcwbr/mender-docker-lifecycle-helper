import logging
import subprocess

from itertools import zip_longest
from pathlib import Path

DAEMON_TRANSPORT = "docker-daemon:"
DOCKER_BIN = "docker"
OCI_TRANSPORT = "oci-archive"
HASH_PREFIX = "sha256"
REF_HASH_SEPARATOR = f"@{HASH_PREFIX}:"
REF_TAG_SEPARATOR = ":"
REF_NOT_FOUND_DAEMON_LOG = "loading image from docker engine: Error response from daemon: reference does not exist"
HASH_NOT_FOUND_DAEMON_LOG = (
    "loading image from docker engine: Error response from daemon: failed to get digest"
)
REF_NOT_FOUND_REGISTRY_LOG = "requested access to the resource is denied"
REGISTRY_TRANSPORT = "docker://"
SKOPEO_BIN = "skopeo"


class ImageRefHashMismatchException(Exception):
    pass


class ImageNotFoundException(Exception):
    pass


def _split_image_ref(image_ref: str) -> tuple[str, str, str]:
    """
    Split an image ref into its component parts, if present.

    :param image_ref: The image ref to split.
    :return: A tuple of the image registry, tag, and hash, or None if not specified.
    """
    image_registry = None
    image_tag = None
    image_hash = None
    if REF_HASH_SEPARATOR in image_ref:
        # Split into parts before and after the hash prefix
        image_ref, image_hash = image_ref.split(REF_HASH_SEPARATOR, 1)
    if REF_TAG_SEPARATOR in image_ref:
        # Find the last colon
        last_colon = image_ref.rfind(REF_TAG_SEPARATOR)
        # Check if there is a / after the colon (would indicate it is part of a path or port)
        if "/" in image_ref[last_colon:]:
            image_registry = image_ref
        # If there is no / after the colon, it is a tag
        else:
            image_registry = image_ref[:last_colon]
            image_tag = image_ref[(last_colon + 1) :]
    else:
        image_registry = image_ref
    return image_registry, image_tag, image_hash


def _image_ref_hash_or_tag(
    image_registry: str,
    image_tag: str,
    image_hash: str,
) -> str:
    """
    Reconstructs an image ref using only the hash (no tag) if provided, or the tag ref otherwise.

    :param image_registry: The registry portion of image ref.
    :param image_tag: The tag portion of image ref.
    :param image_hash: The hash portion of image ref.
    :return: The reconstructed image ref.
    """
    if image_hash is not None:
        return f"{image_registry}{REF_HASH_SEPARATOR}{image_hash}"
    elif image_tag is not None:
        return f"{image_registry}{REF_TAG_SEPARATOR}{image_tag}"
    else:
        return image_registry


def get_image_hash(
    image_ref: str,
    logger: logging.Logger,
) -> str:
    """
    Read the image hash for a given image reference from a remote registry, or, if unavailable, from the local image store.

    :param image_ref: The image ref for which to get the hash.
    :param logger: The logger object to which to report.
    :raises ValueError: If the image hash cannot be retrieved.
    :return: The hash of the image.
    """

    image_hash = None
    # Try docker buildx imagetools inspect for remote images
    try:
        image_hash = (
            subprocess.run(
                [
                    DOCKER_BIN,
                    "buildx",
                    "imagetools",
                    "inspect",
                    image_ref,
                    "--format",
                    '"{{json .Manifest.Digest}}"',
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            .stdout.strip()
            .strip('"')
            .removeprefix(f"{HASH_PREFIX}:")
        )
    except subprocess.CalledProcessError as e:
        logger.debug(
            f"docker buildx imagetools inspect failed for image {image_ref}: {e}\n{e.stderr}"
        )
        # Try docker inspect for local images
        try:
            image_hash = (
                subprocess.run(
                    [DOCKER_BIN, "inspect", "--format", "{{.Id}}", image_ref],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                .stdout.strip()
                .removeprefix(f"{HASH_PREFIX}:")
            )
        except subprocess.CalledProcessError as e:
            logger.debug(
                f"docker inspect failed for image {image_ref}: {e}\n{e.stderr}"
            )
            raise ValueError(f"Could not retrieve hash for image: {image_ref}")

    return image_hash


def save_registry_image_to_file(
    image_ref: str, file: Path, platform: str = None
) -> subprocess.CompletedProcess:
    """
    Saves the specified container image from a registry to the specified file.

    :param image_ref: The ref of the image to save.
    :param file: The path of the file to which to save the image.
    :param platform: The platform for which to save the image, as os/arch[/variant].
    :raises ImageNotFoundException: If the save operation cannot find the image.
    :return: The completed process from the subprocess call.
    """

    image_ref = _image_ref_hash_or_tag(*_split_image_ref(image_ref))

    platform_dict = {"os": None, "arch": None, "variant": None}
    if platform is not None:
        platform_values = platform.split("/")
        platform_fields = platform_dict.keys()
        platform_dict = dict(
            zip_longest(platform_fields, platform_values, fillvalue=None)
        )

    # skopeo copy docker://<image_ref> oci-archive:<file>
    try:
        cmd = [
            SKOPEO_BIN,
            "copy",
        ]
        if platform_dict["os"] is not None:
            cmd.extend(["--override-os", platform_dict["os"]])
        if platform_dict["arch"] is not None:
            cmd.extend(["--override-arch", platform_dict["arch"]])
        if platform_dict["variant"] is not None:
            cmd.extend(["--override-variant", platform_dict["variant"]])
        cmd.extend(
            [
                f"{REGISTRY_TRANSPORT}{image_ref}",
                f"{OCI_TRANSPORT}:{file}",
            ]
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=True,
        )
        if result.returncode != 0:
            raise subprocess.SubprocessError(result.stdout, result.stderr)
        return result
    except subprocess.CalledProcessError as e:
        stderr_str = (
            e.stderr.decode("utf-8", errors="ignore")
            if isinstance(e.stderr, bytes)
            else e.stderr
        )
        if REF_NOT_FOUND_REGISTRY_LOG in stderr_str:
            raise ImageNotFoundException(f"Ref {image_ref} not found in registry.")
        else:
            raise subprocess.SubprocessError(stderr_str)


def save_local_image_to_file(
    image_hash: str, file: Path
) -> subprocess.CompletedProcess:
    """
    Saves the specified container image from the local image store to the specified file.

    :param image_hash: The hash of the image to save.
    :param file: The path of the file to which to save the image.
    :raises ImageNotFoundException: If the save operation cannot find the image.
    :return: The completed process from the subprocess call.
    """
    # skopeo copy docker-daemon:<image_hash> oci-archive:<file>
    try:
        result = subprocess.run(
            [
                SKOPEO_BIN,
                "copy",
                f"{DAEMON_TRANSPORT}{HASH_PREFIX}:{image_hash}",
                f"{OCI_TRANSPORT}:{file}",
            ],
            capture_output=True,
            check=True,
        )
        if result.returncode != 0:
            raise subprocess.SubprocessError(result.stdout, result.stderr)
        return result
    except subprocess.CalledProcessError as e:
        stderr_str = (
            e.stderr.decode("utf-8", errors="ignore")
            if isinstance(e.stderr, bytes)
            else e.stderr
        )
        if (
            REF_NOT_FOUND_DAEMON_LOG in stderr_str
            or HASH_NOT_FOUND_DAEMON_LOG in stderr_str
        ):
            raise ImageNotFoundException(
                f"Hash {image_hash} not found in local daemon."
            )
        else:
            raise e


def save_image_to_file(
    image: dict[str, str], file: Path, platform: str = None
) -> subprocess.CompletedProcess:
    """
    Saves the specified container image to the specified file.

    :param image: The metadata (as {ref: <ref>, hash: <hash>}) of the image to save.
    :param file: The path of the file to which to save the image.
    :param platform: The platform for which to save the image, as os/arch[/variant].
    :raises ImageRefHashMismatchException: If the metadata ref contains a hash that does not match the provided metadata hash.
    :raises ImageNotFoundException: If the image cannot be found.
    :return: The completed process from the subprocess call.
    """
    image_ref = image["ref"]
    image_hash = image["hash"]

    image_registry, image_tag, image_ref_hash = _split_image_ref(image_ref)
    if image_ref_hash is not None and image_ref_hash != image_hash:
        raise ImageRefHashMismatchException(
            f"Specified hash {image_hash} does not match hash embedded in ref {image_ref}."
        )
    image_ref = _image_ref_hash_or_tag(image_registry, image_tag, image_hash)

    try:
        return save_local_image_to_file(image_hash, file)
    except ImageNotFoundException:
        try:
            return save_registry_image_to_file(image_ref, file, platform)
        except ImageNotFoundException:
            raise ImageNotFoundException(
                f"Image with ref {image_ref} not found in local daemon or remote registry"
            )
