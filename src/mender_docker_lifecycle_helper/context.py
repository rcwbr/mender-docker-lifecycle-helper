import logging
import os
import shutil
import tempfile

from pathlib import Path

import git
import yaml

from mender_docker_lifecycle_helper.artifact_metadata import ArtifactMetadata
from mender_docker_lifecycle_helper.utils.image_cache import ImageCache
from mender_docker_lifecycle_helper.utils.container_utils import get_image_hash


LOG_LEVELS=["DEBUG", "INFO", "WARNING", "ERROR"]


class LifecycleHelperContext:
    """
    Representation of the context in which the helper is operating, including the args, input file, and available container images.
    """
    def __init__(self, args):
        self.artifact_filename = args.artifact_filename
        self.cache = args.cache
        self.delta = args.delta
        self.device_type = args.device_type
        self.platform = args.platform
        self.release = args.release
        self.service_files = args.service_files
        self.service_images = args.service_images

        self.logger = self._prep_logger(args.log_level)

        self.manifest_file = args.manifest_file.resolve()
        with open(self.manifest_file, "r") as f:
            self.manifest = yaml.safe_load(f.read())

        self.repo_root_dir = self._repo_root_dir(self.manifest_file)
        self.repo_version = self._repo_version(self.repo_root_dir)
        self._repo = git.Repo(self.repo_root_dir)
        self.commit_short_sha = self._repo.head.commit.hexsha[:7]

        self.manifest_name = (
            args.manifest_name
            if args.manifest_name
            else f"{self.repo_root_dir.name}-{self.manifest_file.parent.name}"
        )

        if self.cache:
            self.cache_dir = self._prep_cache_dir(args.cache_dir)
            self.temp_dir = self.cache_dir / "temp"
            self.temp_dir.mkdir()
            manifests_cache_dir = self.cache_dir / "manifests"
            manifests_cache_dir.mkdir(exist_ok=True)
            manifest_cache_dir = manifests_cache_dir / self.manifest_name
            manifest_cache_dir.mkdir(exist_ok=True)
            self.cache_artifact_metadata_file = manifest_cache_dir / "previous_artifact.json"
            self.image_cache = ImageCache(self.cache_dir / "images")

        if self.delta:
            self.previous_artifact_metadata = self._prep_previous_artifact_metadata(
                args.previous_version
            )

    def __del__(self):
        if self.cache:
            shutil.rmtree(self.temp_dir)
        # services_changed = False
        # for service_name, service in manifest.services.items():
        #     if (
        #         service_name not in previous_artifact_metadata.services
        #         or previous_artifact_metadata.services[service_name]["image"]["ref"] != service["image"]
        #     ):
        #         services_changed = True
        # TODO support manifest-only artifact if services not changed


    @staticmethod
    def _default_cache_dir(
        cache_dir_env_key: str = "MENDER_HELPER_CACHE_DIR",
        default_cache_dir_name: str = "mender-docker-lifecycle-helper"
    ) -> Path:
        return (
            Path(os.getenv(cache_dir_env_key))
            if os.getenv(cache_dir_env_key)
            else Path(os.getenv("XDG_CACHE_HOME")) / default_cache_dir_name
            if os.getenv("XDG_CACHE_HOME")
            else Path("~/.cache").expanduser() / default_cache_dir_name
        )


    @staticmethod
    def _prep_logger(log_level: str) -> logging.Logger:
        logger = logging.getLogger(__name__)
        handler = logging.StreamHandler()
        formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, log_level))
        return logger


    @staticmethod
    def _repo_root_dir(path: Path) -> Path:
        while path != Path("/"):
            if (path / ".git").exists():
                return path
            path = path.parent
        raise FileNotFoundError("Could not find the repository root directory.")


    def _prep_cache_dir(self, cache_dir: Path) -> Path:
        if cache_dir.exists():
            self.logger.debug(f"Using existing cache dir {cache_dir}")
        else:
            self.logger.warning(f"Cache dir {cache_dir} does not exist, will create...")
            cache_dir.mkdir(parents=True)
        return cache_dir


    @staticmethod
    def _repo_version(repo_dir: Path) -> str:
        VERSION_FILE_NAME = "VERSION"
        with open(repo_dir / VERSION_FILE_NAME, "r") as file:
            return file.read().strip()


    def _temp_repo_at_version(
        self,
        version: str,
    ) -> Path:
        temp_repo_dir = Path(tempfile.mkdtemp(dir=self.temp_dir))
        self.logger.debug(f"Preparing temporary repo at version {version}: {temp_repo_dir}")

        # Clone the repo from the local path to the temporary directory and checkout the specified version
        try:
            repo = git.Repo.clone_from(self.repo_root_dir, temp_repo_dir)
            repo.git.checkout(version)
            self.logger.debug(f"Cloned and checked out repo at {version} to {temp_repo_dir}")
        except Exception as e:
            self.logger.error(
                f"Failed to clone and checkout repo at {version} in {temp_repo_dir}: {e}"
            )
            raise e

        return temp_repo_dir


    def _artifact_services_metadata_from_compose(
        self,
        compose_file: Path
    ) -> dict[str, dict[str, dict[str, str]]]:
        with open(compose_file, "r") as f:
            return yaml.safe_load(f.read())

        return {
            service: {
                "image": {
                    "ref": config["image"],
                    "hash": get_image_hash(config["image"]),
                }
            }
            for service, config in compose["services"].items()
        }


    def _prep_previous_artifact_metadata(
        self,
        previous_version: str,
    ) -> ArtifactMetadata:
        if self.cache and self.cache_artifact_metadata_file.exists():
            self.logger.debug(f"Cached artifact metadata file {self.cache_artifact_metadata_file} found, will use this for previous artifact metadata.")
            return ArtifactMetadata.from_file(self.cache_artifact_metadata_file)

        if previous_version:
            # If a version/ref is provided, attempt to get the artifact info from that ref
            self.logger.info(
                f"Getting previous artifact info for arg-specified repo ref: {previous_version}"
            )
        elif self.release:
            previous_commit = self._repo.head.commit.parents[0].hexsha
            self.logger.info(
                f"Release context indicated, will read the previous version from the repo at ref {previous_commit}"
            )
            previous_version = self._repo_version(
                self._temp_repo_at_version(previous_commit)
            )
        else:
            previous_version = self.repo_version
            self.logger.debug(
                f"Getting previous artifact info from repo at version from VERSION file: {previous_version}"
            )


        previous_version_repo = self._temp_repo_at_version(previous_version)
        previous_manifest_file = previous_version_repo / self.manifest_file.relative_to(self.repo_root_dir)
        if not previous_manifest_file.exists():
            self.logger.error(f"Manifest file {previous_manifest_file} does not exist.")
            raise FileNotFoundError(
                "Manifest file {previous_manifest_file} does not exist."
            )

        return ArtifactMetadata(
            version=previous_version,
            services=self._artifact_services_metadata_from_compose(previous_manifest_file)
        )


    def match_or_find_hash(self, service_name: str, image_ref: str) -> str:
        """
        If the provided image ref matches that in the previous artifact metadata for the given service, return the corresponding hash from the previous artifact metadata. Otherwise, attempt to retrieve the image hash for the provided image ref.
        """

        image_hash = ""
        if (
            self.previous_artifact_metadata.services
                .get(service_name, {})["image"]["ref"] == image_ref
        ):
            image_hash = self.previous_artifact_metadata.services[service_name]["image"]["hash"]
            self.logger.debug(f"Image ref for service {service_name} matches previous artifact metadata. Skipping hash lookup and using previous hash {image_hash}.")
        else:
            image_hash = get_image_hash(image_ref, self.logger)

        return image_hash
