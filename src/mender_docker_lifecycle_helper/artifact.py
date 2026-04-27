import json
import shutil
import subprocess
import tarfile
import yaml

from pathlib import Path

from mender_docker_lifecycle_helper.artifact_metadata import ArtifactMetadata
from mender_docker_lifecycle_helper.context import LifecycleHelperContext
from mender_docker_lifecycle_helper.utils.deep_delta import ImageDeltaException
from mender_docker_lifecycle_helper.utils.image_cache import IMAGE_FILE_NAME


DEEP_DELTA_FILENAME = "deep_delta"


class ManifestContentMismatchException(Exception):
    pass


class LifecycleHelperArtifact:
    """
    Representation of the artifact on which the helper is operating. Provides the gen_artifact_file method to perform necessary processing and preparation for creating a Mender artifact file.
    """

    def __init__(
        self,
        context: LifecycleHelperContext,
        name: str,
        artifact_metadata: ArtifactMetadata,
        filename: Path,
    ):
        """
        Construct a LifecycleHelperArtifact object.

        :param context: The context of the lifecycle helper execution.
        :param name: The name of the artifact as recognized by Mender.
        :param artifact_metadata: The metadata of the artifact for caching.
        :param filename: The file at which to generate the artifact.
        """
        self.context = context
        self.name = name
        self.filename = filename
        self.artifact_metadata = artifact_metadata

        self.context.logger.debug(
            f"Creating artifact named {name} with metadata {artifact_metadata.to_dict()}"
        )

        self.depends = (
            [
                f"rootfs-image.{context.manifest_name}.version:{context.previous_artifact_metadata.version}"
            ]
            if context.delta
            else []
        )
        self.image_ids = [
            service_spec["image"]["hash"]
            for service_spec in artifact_metadata.services.values()
        ]
        self.image_ids.sort()  # Sort only for determinism

    @staticmethod
    def call_mender_artifact(
        context: LifecycleHelperContext, arg_list: list[str]
    ) -> str:
        """
        Execute the mender-artifact executable with the supplied arguments.

        :param context: The context of the lifecycle helper execution.
        :param arg_list: The arguments to supply to the mender-artifact executable.
        :raises RuntimeError: If the mender-artifact execution fails.
        :return: The stdout output of the mender-artifact execution.
        """
        rendered_args = "\n  ".join(arg_list)
        context.logger.debug(f"Calling mender-artifact with args: \n  {rendered_args}")
        try:
            result = subprocess.run(
                # Join/split to handle arg items with and without spaces
                ["mender-artifact", *(" ".join(arg_list).split(" "))],
                capture_output=True,
                text=True,
                check=True,
            )
            context.logger.debug(f"mender-artifact output: {result.stdout}")
            return result.stdout
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"mender-artifact \n  {rendered_args} failed: {e.stdout} {e.stderr}"
            )

    def prep_delta_image(
        self,
        service_name: str,
        service_image: dict[str, str],
        artifact_image_prep_dir: Path,
    ) -> None:
        """
        Prepare a delta image file, which may be an empty delta file if the image ref and hash for the service match those in the previous artifact metadata, or a real delta.

        :param service_name: The name of the service in the manifest for which to generate an image delta.
        :param service_image: The metadata of the image for which to generate a delta.
        :param artifact_image_prep_dir: The directory into which the image delta file will be written.
        :raises ImageDeltaException: If the delta generation fails.
        :return: None
        """
        self.context.logger.debug(f"Preparing image delta for service {service_name}")
        # Generate a delta file in the artifact. If the image ref and hash for a service match those in the previous artifact metadata, each layer diff will be empty.
        previous_image = self.context.previous_artifact_metadata.services[service_name][
            "image"
        ]
        (artifact_image_prep_dir / DEEP_DELTA_FILENAME).touch()
        # Ensure images for delta are extracted in the cache
        image_delta_file = self.context.image_cache.delta(
            previous_image, service_image, self.context.platform
        )
        (artifact_image_prep_dir / IMAGE_FILE_NAME).symlink_to(image_delta_file)
        (artifact_image_prep_dir / "sums-current.txt").write_text(
            previous_image["hash"]
        )
        (artifact_image_prep_dir / "url-current.txt").write_text(previous_image["ref"])

    def prep_image(
        self,
        service_name: str,
        service_image: dict[str, str],
        artifact_images_prep_dir: Path,
    ) -> None:
        """
        Prepare the required directory and files for the specified image in the specified artifact prep directory.

        :param service_name: The name of the service in the manifest for which to generate an image delta.
        :param service_image: The metadata of the image for which to generate a delta.
        :param artifact_images_prep_dir: The directory into which the image directory will be created.
        :raises ImageDeltaException: If delta generation fails.
        :return: None
        """
        artifact_image_prep_dir = artifact_images_prep_dir / service_image["hash"]
        self.context.logger.debug(
            f"Preparing artifact files for image {service_image['ref']} for service {service_name} in {artifact_image_prep_dir}"
        )
        artifact_image_prep_dir.mkdir()
        (artifact_image_prep_dir / "sums-new.txt").write_text(service_image["hash"])
        (artifact_image_prep_dir / "url-new.txt").write_text(service_image["ref"])

        # For non-delta artifacts or new services, the image as a whole is included in the artifact
        if (
            self.context.delta
            and service_name in self.context.previous_artifact_metadata.services
        ):
            try:
                self.prep_delta_image(
                    service_name, service_image, artifact_image_prep_dir
                )
                return
            except ImageDeltaException as e:
                # TODO ensure possible to mix delta and non-delta images in artifact
                self.context.logger.warning("Delta image generation failure:")
                self.context.logger.warning(e)
                self.context.logger.warning(
                    f"Will include the full image {service_image} for {service_name} instead."
                )

        # Write the new image details as current in the case of a non-delta image.
        (artifact_image_prep_dir / "sums-current.txt").write_text(service_image["hash"])
        (artifact_image_prep_dir / "url-current.txt").write_text(service_image["ref"])
        self.context.logger.debug(
            f"Including full image {service_image['ref']} with hash {service_image['hash']} for service {service_name} in artifact."
        )
        (artifact_image_prep_dir / IMAGE_FILE_NAME).symlink_to(
            self.context.image_cache.save_cache_image(service_image)
        )

    def prep_images(
        self,
        artifact_prep_dir: Path,
        images_archive_filename: str,
    ) -> None:
        """
        Prepare the archive file for the specified images in the Mender artifact format, downloading and/or diffing images as necessary based on the image refs and hashes.

        :param artifact_prep_dir: The directory into which the images archive will be generated.
        :param images_archive_filename: The name of the images archive file to generate.
        :return: None
        """
        artifact_images_prep_dir = artifact_prep_dir / "images_prep"
        self.context.logger.debug(
            f"Preparing images artifact files in {artifact_images_prep_dir}"
        )

        artifact_images_prep_dir.mkdir()
        for service_name, service_spec in self.artifact_metadata.services.items():
            self.prep_image(
                service_name, service_spec["image"], artifact_images_prep_dir
            )

        images_archive = artifact_prep_dir / images_archive_filename
        self.context.logger.debug(f"Archiving images to file {images_archive}")
        with tarfile.open(
            name=images_archive, mode="w:gz", dereference=True
        ) as images_tar:
            images_tar.add(
                artifact_images_prep_dir,
                arcname="images",
            )
        self.context.logger.debug(
            f"Cleaning up images prep dir {artifact_images_prep_dir}"
        )
        shutil.rmtree(artifact_images_prep_dir)

    def prep_manifests(
        self, artifact_prep_dir: Path, manifests_archive_filename: str
    ) -> None:
        """
        Prepare the manifests archive file in the Mender artifact format.

        :param artifact_prep_dir: The directory into which the manifests archive will be generated.
        :param manifests_archive_filename: The name of the manifests archive file to generate.
        :return: None
        """
        artifact_manifests_prep_dir = artifact_prep_dir / "manifests_prep"
        self.context.logger.debug(
            f"Preparing manifests artifact files in {artifact_manifests_prep_dir}"
        )

        artifact_manifests_prep_dir.mkdir()
        artifact_manifest = (
            artifact_manifests_prep_dir / self.context.manifest_file.name
        )
        with open(artifact_manifest, "w") as f:
            yaml.safe_dump(self.context.manifest, f)

        manifests_archive = artifact_prep_dir / manifests_archive_filename
        with tarfile.open(name=manifests_archive, mode="w:gz") as manifests_tar:
            manifests_tar.add(
                artifact_manifests_prep_dir,
                arcname="manifests",
            )
        self.context.logger.debug(
            f"Cleaning up manifests prep dir {artifact_manifests_prep_dir}"
        )
        shutil.rmtree(artifact_manifests_prep_dir)

    def prep_artifact_dir(
        self,
        artifact_prep_dir: Path,
        images_archive_filename: str,
        manifests_archive_filename: str,
        metadata_filename: str,
    ) -> None:
        """
        Prepare artifact directory with necessary files for artifact generation, such as extracted service file images and any other necessary files.

        :param artifact_prep_dir: The directory into which to prepare the artifact files.
        :param images_archive_filename: The filename for the artifact images archive.
        :param manifests_archive_filename: The filename for the artifact manifests archive.
        :param metadata_filename: The filename for the artifact metadata file.
        :return: None
        """

        self.prep_manifests(artifact_prep_dir, manifests_archive_filename)
        self.prep_images(artifact_prep_dir, images_archive_filename)
        metadata_file = artifact_prep_dir / metadata_filename
        with open(metadata_file, "w") as f:
            json.dump(
                {
                    "application_name": self.context.manifest_name,
                    "orchestrator": "docker-compose",
                    "platform": self.context.platform,
                    "version": self.artifact_metadata.version,
                    "images": self.image_ids,
                },
                f,
            )

    def gen_artifact_file(self) -> None:
        """
        Prepare the artifact by generating necessary files and processing via the mender-artifact tool.

        :return: None
        """
        artifact_prep_dir = self.context.temp_dir / "artifact_prep"
        images_archive_filename = "images.tar.gz"
        manifests_archive_filename = "manifests.tar.gz"
        metadata_filename = "metadata.json"

        artifact_prep_dir.mkdir()
        self.prep_artifact_dir(
            artifact_prep_dir,
            images_archive_filename,
            manifests_archive_filename,
            metadata_filename,
        )
        self.call_mender_artifact(
            self.context,
            [
                "write",
                "module-image",
                "--type app",
                f"--device-type {self.context.device_type}",
                f"--output-path {self.filename}",
                f"--artifact-name {self.name}",
                f"--file {artifact_prep_dir / images_archive_filename}",
                f"--file {artifact_prep_dir / manifests_archive_filename}",
                f"--meta-data {artifact_prep_dir / metadata_filename}",
                f"--software-name {self.context.manifest_name}",
                f"--software-version {self.artifact_metadata.version}",
            ]
            + [f"--depends {depend}" for depend in self.depends],
        )
        shutil.rmtree(artifact_prep_dir)

    @staticmethod
    def gen_artifact_services(
        context: LifecycleHelperContext,
    ) -> dict[str : dict[str : dict[str, str]]]:
        """
        Determine the services metadata for the current artifact, including reading the image hashes from remote images when required. To establish this list, any provided service-file image archives are extracted and read.

        :param context: The context of the lifecycle helper execution.
        :raises ManifestContentMismatchException: If service name in args not found in manifest.
        :return: The services to be included in the current artifact, in the following dict structure:
            {
                serviceName: {
                    image: {
                        ref: str,
                        hash: str
                    }
                }
            }
        """

        context.logger.info("Determining services for the artifact.")
        artifact_services = {}
        for service_name, service_spec in context.manifest["services"].items():
            artifact_service = artifact_services[service_name] = {}
            artifact_service_image = artifact_service["image"] = {}
            # The metadata from each specified service file is used in the artifact, taking precedence over any specified service image override
            if service_name in context.service_files:
                if service_name in context.service_images:
                    context.logger.warning(
                        f"Service {service_name} has both a service file and an image override specified. Ignoring the image override."
                    )

                service_filename = context.service_files[service_name]
                service_image = context.image_cache.extract_cache_file(service_filename)
                # Both the ref and hash are set for services with a provided service file
                context.logger.debug(
                    f"Overriding {service_name} image details from file {service_filename} to ref {service_image['ref']} and hash {service_image['hash']}."
                )
                artifact_service_image["ref"] = service_image["ref"]
                artifact_service_image["hash"] = service_image["hash"]

            # The metadata from each specified image override is used in the artifact
            elif service_name in context.service_images:
                image_override = context.service_images[service_name]
                context.logger.debug(
                    f"Overriding {service_name} image ref to {image_override}."
                )
                artifact_service_image["ref"] = image_override
                artifact_service_image["hash"] = context.match_or_find_hash(
                    service_name, image_override
                )

            # By default, the image ref from the manifest is used for the artifact
            else:
                artifact_service_image["ref"] = service_spec["image"]
                artifact_service_image["hash"] = context.match_or_find_hash(
                    service_name, service_spec["image"]
                )

        # Check that all service file args match the manifest
        for service_name, service_filename in context.service_files.items():
            if service_name not in context.manifest["services"]:
                # Cannot map specified service name to service in the manifest
                raise ManifestContentMismatchException(
                    f"Service {service_name} specified to map to service file {service_filename} not found in manifest."
                )

        # Check that all service image args match the manifest
        for service_name, image_override in context.service_images.items():
            if service_name not in context.manifest["services"]:
                # Cannot map specified service name to service in the manifest
                raise ManifestContentMismatchException(
                    f"Service {service_name} specified to map to service image override {image_override} not found in manifest."
                )

        return artifact_services
