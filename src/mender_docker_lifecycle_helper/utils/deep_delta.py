# Inspired by the deep_delta function from app-gen:
# https://github.com/mendersoftware/app-update-module/blob/29eb51169d1dc32ef1bd013e2414361f67195219/gen/app-gen#L377

import json
import logging
import shutil
import subprocess
import tarfile

from pathlib import Path

from mender_docker_lifecycle_helper.utils.container_utils import HASH_PREFIX

XDELTA_CMD = ["xdelta3", "-f", "-e", "-s"]


class ImageDeltaException(Exception):
    pass


def _read_layers_from_manifest(
    image_dir: Path,
    target_platform: str,
    logger: logging.Logger | None = logging.getLogger(__name__),
) -> list[Path]:
    """
    Reads the layers from an OCI image manifest file.

    :param image_dir: The directory in which the image is extracted.
    :param target_platform: The platform to target, if the image contains multiple, as os/[architecture]/[variant].
    :param logger: A logger with which to log steps of function processes, defaults to logging.getLogger(__name__).
    :return: The list of paths to the layers referenced by the image manifest.
    """
    blobs_dir = image_dir / "blobs" / HASH_PREFIX

    index = {}
    index_filename = image_dir / "index.json"
    logger.debug(f"Reading the image index file {index_filename}.")
    with open(index_filename, "r") as index_file:
        index = json.load(index_file)

    manifest_hash = index["manifests"][0]["digest"].removeprefix(f"{HASH_PREFIX}:")
    manifest = {}
    manifest_filename = blobs_dir / manifest_hash
    logger.debug(f"Reading manifest file {manifest_filename}.")
    with open(blobs_dir / manifest_hash) as manifest_file:
        manifest = json.load(manifest_file)

    # Multi-platform images may have multiple levels of nested manifests.
    # Loop through manifests as needed until layers are found.
    visited = set()
    while "layers" not in manifest and "manifests" in manifest:
        logger.debug(
            "Manifest without layers detected, looking for matching platform manifest..."
        )
        found = False
        for platform_manifest in manifest["manifests"]:
            platform_values = target_platform.split("/")
            platform_fields = ["os", "architecture", "variant"]
            if all(
                platform_manifest["platform"].get(platform_field) == platform_value
                for platform_field, platform_value in zip(
                    platform_fields, platform_values
                )
            ):
                logger.debug("Matching platform found!")
                new_hash = platform_manifest["digest"].removeprefix(f"{HASH_PREFIX}:")
                if f"{blobs_dir}-{new_hash}" in visited:
                    raise ImageDeltaException("Cycle detected while resolving manifest")
                visited.add(f"{blobs_dir}-{new_hash}")
                with open(blobs_dir / new_hash) as manifest_file:
                    manifest = json.load(manifest_file)
                found = True
                break
        if not found:
            raise ImageDeltaException("No matching platform found in manifest")

    layers = [
        blobs_dir / layer["digest"].removeprefix(f"{HASH_PREFIX}:")
        for layer in manifest["layers"]
    ]
    return layers


def oci_deep_delta(
    from_dir: Path,
    to_dir: Path,
    delta_dir: Path,
    delta_filename: str,
    target_platform: str,
    delta_cmd: list[str] | None = XDELTA_CMD,
    logger: logging.Logger | None = logging.getLogger(__name__),
) -> Path:
    """
    Generate deep delta between OCI images.

    Writes .vcdiff and .source files into delta_dir based on the layer files in to_dir and from_dir, bundled into a tar file.

    :param from_dir: The path to the extracted current image.
    :param to_dir: The path to the extracted new image.
    :param delta_dir: The path under which to create the delta layers.
    :param delta_filename: The name of the delta image archive file to create.
    :param delta_cmd: The command to use for layer delta generation, defaults to XDELTA_CMD.
    :param target_platform: The platform to target, if the image contains multiple, as os/[architecture]/[variant].
    :param logger: A logger with which to log steps of function processes, defaults to logging.getLogger(__name__).
    :raises ImageDeltaException: If images contain different numbers of layers.
    :return: The image delta file.
    """
    # Load layers from current image manifest
    from_layers = _read_layers_from_manifest(from_dir, target_platform, logger)

    # Load layers from new image manifest
    to_layers = _read_layers_from_manifest(to_dir, target_platform, logger)

    # Check if current image has more layers than new image
    if len(from_layers) > len(to_layers):
        logger.error(
            "Failed to create image delta because the source image has more layers than the new one."
        )
        raise ImageDeltaException(
            "Image delta generation failed: source image has more layers than the new one"
        )

    delta_gen_dir = delta_dir / "gen"
    logger.debug(f"Copying to-image dir {to_dir} to new delta dir {delta_gen_dir}.")
    delta_gen_dir.mkdir(parents=True)
    # Copy full dir to capture layout and accompanying files
    shutil.copytree(to_dir, delta_gen_dir, dirs_exist_ok=True)

    # Generate deltas for each layer pair
    for i in range(len(from_layers)):
        logger.debug(f"Diffing layer {i + 1} of {len(from_layers)}")
        from_layer_path = from_layers[i]
        to_layer_path = to_layers[i]
        to_layer = to_layer_path.name
        delta_layer_path = delta_gen_dir / "blobs" / HASH_PREFIX / to_layer
        source_path = delta_gen_dir / "blobs" / HASH_PREFIX / (to_layer + ".source")
        vcdiff_layer_path = (
            delta_gen_dir / "blobs" / HASH_PREFIX / (to_layer + ".vcdiff")
        )

        # Run delta command, creating the vcdiff file in the delta dir
        try:
            result = subprocess.run(
                [*delta_cmd, from_layer_path, to_layer_path, vcdiff_layer_path],
                capture_output=True,
                check=True,
            )
            if result.returncode != 0:
                raise subprocess.SubprocessError(result.stdout, result.stderr)
        except subprocess.CalledProcessError as e:
            stderr_str = (
                e.stderr.decode("utf-8", errors="ignore")
                if isinstance(e.stderr, bytes)
                else e.stderr
            )
            raise subprocess.SubprocessError(stderr_str)

        # Remove the layer file from the delta dir
        delta_layer_path.unlink()

        # Write source layer reference in the delta dir.
        # The .source file must contain the relative path from the image root to the source blob,
        # because the docker-compose module prepends current_image_dir to this value.
        source_relative_path = from_layers[i].relative_to(from_dir)
        with open(source_path, "w") as f:
            f.write(str(source_relative_path))

    # Handle any extra layers in the new image that have no corresponding layer in the old image.
    # Create a "full layer diff" using /dev/null as source.
    for i in range(len(from_layers), len(to_layers)):
        logger.debug(
            f"Copying extra layer {i + 1} of {len(to_layers) - len(from_layers)}"
        )
        to_layer_path = to_layers[i]
        to_layer = to_layer_path.name
        delta_layer_path = delta_gen_dir / "blobs" / HASH_PREFIX / to_layer
        vcdiff_layer_path = (
            delta_gen_dir / "blobs" / HASH_PREFIX / (to_layer + ".vcdiff")
        )
        source_path = delta_gen_dir / "blobs" / HASH_PREFIX / (to_layer + ".source")

        # Create a vcdiff that produces the full layer when applied to /dev/null.
        # This works because xdelta3 -e -s /dev/null <layer> creates a delta
        # that reconstructs the layer content when applied to empty.
        try:
            result = subprocess.run(
                [*delta_cmd, Path("/dev/null"), to_layer_path, vcdiff_layer_path],
                capture_output=True,
                check=True,
            )
            if result.returncode != 0:
                raise subprocess.SubprocessError(result.stdout, result.stderr)
        except subprocess.CalledProcessError as e:
            stderr_str = (
                e.stderr.decode("utf-8", errors="ignore")
                if isinstance(e.stderr, bytes)
                else e.stderr
            )
            raise subprocess.SubprocessError(stderr_str)

        # Point to /dev/null as the source - apply_layer_delta_oci will use this path
        with open(source_path, "w") as f:
            f.write("/dev/null")

        # Remove the original layer blob - it will be reconstructed from the vcdiff
        delta_layer_path.unlink()

    delta_file = delta_dir / delta_filename
    logger.debug(f"Layer diffing complete, creating delta file {delta_file}...")
    with tarfile.open(delta_file, "w") as tar:
        tar.add(delta_gen_dir, arcname=".")
    logger.debug(
        f"Delta file {delta_file} complete. Cleaning up delta gen dir {delta_gen_dir}."
    )
    shutil.rmtree(delta_gen_dir)
    return delta_file
