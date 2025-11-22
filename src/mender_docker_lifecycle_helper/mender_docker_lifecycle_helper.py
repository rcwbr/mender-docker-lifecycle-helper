import argparse
import json
import logging
import os
import requests
import shutil
import sys
import tarfile


import uuid
import tempfile
import git
import yaml
import subprocess

from typing import Dict
from pathlib import Path

from mender_docker_lifecycle_helper.utils.deep_delta import deep_delta

logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

DOCKER_BIN = "docker"
MENDER_PAT_ENV_KEY = "MENDER_PAT"
MENDER_HELPER_CACHE_DIR_ENV_KEY = "MENDER_HELPER_CACHE_DIR"
VERSION_FILE_NAME = "VERSION"
TEMP_REPOS_DIR_NAME = "temp_repos"
TEMP_ARTIFACTS_DIR_NAME = "temp_artifacts"
DEFAULT_CACHE_DIR_NAME = "mender-docker-lifecycle-helper"
PREVIOUS_ARTIFACT_INFO_FILENAME = "previous_artifact_info.json"


class ArtifactInfo:
    def __init__(self, version: str = None, services: Dict[str, Dict[str, str]] = None):
        self.version = version
        self.services = services if services is not None else {}

    def to_dict(self):
        return {"version": self.version, "services": self.services}

    @classmethod
    def from_dict(cls, data):
        return cls(version=data.get("version"), services=data.get("services", {}))

    def write_to_file(self, file_path):
        os.makedirs(Path(file_path).parent, exist_ok=True)
        with open(file_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def read_from_file(cls, file_path):
        with open(file_path, "r") as f:
            data = json.load(f)
        return cls.from_dict(data)


class ManifestNotFoundException(Exception):
    pass


class MenderDockerLifecycleHelper:
    def __init__(self, args):
        # Map of version refs to temp dirs with the repo at that version
        # Defined first to ensure successful cleanup in __del__
        self.temp_repo_dirs = {}

        self.args = args
        self.service_images = self.key_value_arg(self.args.service_image)
        self.cache_dir = Path(self.get_cache_dir())
        self.repo_root_dir = self.get_repo_root_dir(
            Path(self.args.manifest_file)
            if Path(self.args.manifest_file).is_absolute()
            else Path.cwd() / self.args.manifest_file
        )
        self.manifest_file = (
            Path(self.args.manifest_file).resolve().relative_to(self.repo_root_dir)
        )
        self.manifest_name = (
            self.args.manifest_name
            if self.args.manifest_name
            else f"{self.repo_root_dir.name}-{Path(self.args.manifest_file).parent.name}"
        )
        self.previous_artifact_info_file = (
            self.cache_dir / self.manifest_name / PREVIOUS_ARTIFACT_INFO_FILENAME
        )
        self.repo = git.Repo(self.repo_root_dir)
        self.temp_repos_dir = self.cache_dir / TEMP_REPOS_DIR_NAME
        self.temp_repos_dir.mkdir(exist_ok=True)
        self.temp_artifacts_dir = self.cache_dir / TEMP_ARTIFACTS_DIR_NAME
        self.temp_artifacts_dir.mkdir(exist_ok=True)
        self.previous_version = None
        self.version = None
        self.artifact_name = None
        self.artifact_file = None

    @staticmethod
    def key_value_arg(arglist):
        result = {}
        if arglist:
            for arg in arglist:
                if "=" not in arg:
                    logger.error(f"Invalid key-value argument: {arg}")
                    sys.exit(1)
                key, value = arg.split("=", 1)
                result[key.strip()] = value.strip()
        return result

    @staticmethod
    def clean_up_temp_dirs(temp_dirs):
        for temp_dir in temp_dirs.values():
            if temp_dir.exists():
                logger.debug(f"Removing temporary repo directory: {temp_dir}")
                shutil.rmtree(temp_dir)
        temp_dirs.clear()

    def __del__(self):
        self.clean_up_temp_dirs(self.temp_repo_dirs)
        self.clean_up_temp_dirs({"temp_artifacts_dir": self.temp_artifacts_dir})

    def get_cache_dir(self):
        cache_dir = ""
        if self.args.cache_dir:
            cache_dir = Path(self.args.cache_dir)
        elif os.getenv(MENDER_HELPER_CACHE_DIR_ENV_KEY):
            cache_dir = Path(os.getenv(MENDER_HELPER_CACHE_DIR_ENV_KEY))
        elif os.getenv("XDG_CACHE_HOME"):
            cache_dir = Path(os.getenv("XDG_CACHE_HOME")) / DEFAULT_CACHE_DIR_NAME
        else:
            cache_dir = Path("~/.cache").expanduser() / DEFAULT_CACHE_DIR_NAME

        if not cache_dir.exists():
            cache_dir.mkdir(parents=True)

        logger.debug(f"Using cache directory: {cache_dir}")
        return cache_dir

    def get_repo_root_dir(self, path):
        while path != Path("/"):
            if (path / ".git").exists():
                return path
            path = path.parent
        logger.error("Could not find the repository root directory.")
        sys.exit(1)

    def get_temp_repo_at_version(self, repo_version):
        if repo_version in self.temp_repo_dirs:
            logger.debug(
                f"Temporary repo for version {repo_version} already exists at {self.temp_repo_dirs[repo_version]}"
            )
            return self.temp_repo_dirs[repo_version]

        temp_dir = Path(tempfile.mkdtemp(dir=self.temp_repos_dir))
        logger.debug(f"Prepared temporary repo at version {repo_version}: {temp_dir}")

        # Clone the repo from the local path to the temporary directory and checkout the specified version
        try:
            repo = git.Repo.clone_from(self.repo_root_dir, temp_dir)
            repo.git.checkout(repo_version)
            logger.debug(f"Cloned and checked out repo at {repo_version} to {temp_dir}")
        except Exception as e:
            logger.error(
                f"Failed to clone and checkout repo at {repo_version} in {temp_dir}: {e}"
            )
            raise

        self.temp_repo_dirs[repo_version] = temp_dir
        return temp_dir

    def get_version_from_repo(self, repo_dir):
        with open(repo_dir / VERSION_FILE_NAME, "r") as file:
            return file.read().strip()

    @staticmethod
    def get_image_hash_from_version(image):
        logger.debug(f"Getting image hash for image: {image}")
        image_hash = {}
        # Try docker inspect for local images
        try:
            image_id = subprocess.run(
                [DOCKER_BIN, "inspect", "--format", "{{.Id}}", image],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            if image_id:
                image_hash["local"] = image_id
        except subprocess.CalledProcessError as e:
            logger.debug(f"docker inspect failed for image {image}: {e}\n{e.stderr}")

        # Try docker buildx imagetools inspect for remote images
        try:
            image_digest = (
                subprocess.run(
                    [
                        DOCKER_BIN,
                        "buildx",
                        "imagetools",
                        "inspect",
                        image,
                        "--format",
                        '"{{json .Manifest.Digest}}"',
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                .stdout.strip()
                .strip('"')
            )
            if image_digest:
                image_hash["registry"] = image_digest
        except subprocess.CalledProcessError as e:
            logger.debug(
                f"docker buildx imagetools inspect failed for image {image}: {e}\n{e.stderr}"
            )

        if image_hash == {}:
            logger.error(f"Could not retrieve hash for image: {image}")
            sys.exit(1)
        else:
            return image_hash

    def get_artifact_info_from_compose(self, compose, version):
        if "services" not in compose:
            logger.error("No services found in the provided compose file content.")
            sys.exit(1)

        return ArtifactInfo.from_dict(
            {
                "version": version,
                "services": {
                    service: {
                        "ref": config["image"],
                        "hash": self.get_image_hash_from_version(config["image"]),
                    }
                    for service, config in compose["services"].items()
                },
            }
        )

    def get_artifact_info_from_repo(self, repo_dir, version):
        manifest_file = repo_dir / self.manifest_file
        if not manifest_file.exists():
            logger.warning(f"Manifest file {manifest_file} does not exist.")
            raise ManifestNotFoundException(
                "Manifest file {manifest_file} does not exist."
            )

        with open(manifest_file, "r") as file:
            return self.get_artifact_info_from_compose(
                yaml.safe_load(file.read()), version
            )

    def get_previous_version(self):
        previous_version = ""
        if self.args.previous_version:
            # If a version/ref is provided, attempt to get the artifact info from that ref
            logger.info(
                f"Getting previous artifact info for repo ref: {self.args.previous_version}"
            )
            previous_version = self.args.previous_version
        elif self.args.release:
            previous_commit = self.repo.head.commit.parents[0].hexsha
            logger.info(
                f"Release context indicated, will read the previous version from the repo at ref {previous_commit}"
            )
            previous_version = self.get_version_from_repo(
                self.get_temp_repo_at_version(previous_commit)
            )
        else:
            previous_version = self.get_version_from_repo(self.repo_root_dir)

        return previous_version

    def get_previous_artifact_info(self):
        if self.previous_artifact_info_file.exists() and not self.args.no_cache:
            logger.debug(
                f"Found previous artifact info file: {self.previous_artifact_info_file}"
            )
            return ArtifactInfo.read_from_file(self.previous_artifact_info_file)

        logger.debug(
            f"Will read previous artifact info from repo at version: {self.previous_version}"
        )
        return self.get_artifact_info_from_repo(
            self.get_temp_repo_at_version(self.previous_version), self.previous_version
        )

    def get_current_version(self):
        if self.args.release:
            return self.get_version_from_repo(self.repo_root_dir)
        else:
            return f"{self.previous_version}+{self.repo.head.commit.hexsha[:7]}+{uuid.uuid4()}"

    def get_current_artifact_info(self):
        artifact_info = self.get_artifact_info_from_repo(
            self.repo_root_dir, self.version
        )
        # Override image refs for service-images in the result
        for service_name, image in self.service_images.items():
            if service_name in artifact_info.services:
                logger.info(
                    f"Overriding image ref for service {service_name} to {image} in current artifact info"
                )
                artifact_info.services[service_name]["ref"] = image
                artifact_info.services[service_name]["hash"] = (
                    self.get_image_hash_from_version(image)
                )
            else:
                logger.error(
                    f"Service {service_name} provided as image override not found in manifest"
                )
        return artifact_info

    def pull_image(self, image):
        if "local" in image["hash"]:
            logger.debug(f"Image {image['ref']} already available locally.")
        else:
            logger.debug(f"Pulling image: {image['ref']}")
            try:
                result = subprocess.run(
                    [DOCKER_BIN, "pull", image["ref"]],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                logger.debug(
                    f"Successfully pulled image {image['ref']}: {result.stdout}"
                )
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to pull image {image['ref']}: {e}\n{e.stderr}")

        image["hash"] = self.get_image_hash_from_version(image["ref"])
        return image

    @staticmethod
    def save_image(image_id, file):
        try:
            subprocess.run(
                [DOCKER_BIN, "save", "-o", file, image_id],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to save image {image_id} to {file}: {e}\n{e.stderr}")
            sys.exit(1)

    def prep_image(self, image, delta_image=None):
        image = self.pull_image(image)
        image_id = image["hash"]["local"].removeprefix("sha256:")

        image_dir = self.prep_artifact_temp_dir / "images" / image_id
        image_dir.mkdir(parents=True, exist_ok=True)

        image_metadata_files_map = {
            "sums-new.txt": image_id,
            "url-new.txt": image["ref"],
            "sums-current.txt": image_id,
            "url-current.txt": image["ref"],
        }

        if delta_image:
            delta_image = self.pull_image(delta_image)
            delta_image_id = delta_image["hash"]["local"].removeprefix("sha256:")
            image_metadata_files_map["sums-current.txt"] = delta_image_id
            image_metadata_files_map["url-current.txt"] = delta_image["ref"]
            self.save_image(image_id, image_dir / "image-new.tar")
            self.save_image(delta_image_id, image_dir / "image-current.tar")
            # Generate delta between image and delta_image
            logger.debug(
                f"Generating delta for image {image_id} based on {delta_image_id}..."
            )
            deep_delta(
                image_dir,
                image_dir / "image-new.tar",
                image_dir / "image-current.tar",
                image_dir / "image.img",
                log_level=logger.level,
            )
            Path(image_dir, "deep_delta").touch()
        else:
            self.save_image(image_id, image_dir / "image.img")

        for filename, content in image_metadata_files_map.items():
            with open(image_dir / filename, "w") as f:
                f.write(content)
        return image_id

    def prep_delta_images(self, previous_artifact_info, current_artifact_info):
        image_ids = set()
        for service_name, current_image in current_artifact_info.to_dict()[
            "services"
        ].items():
            previous_image = previous_artifact_info.to_dict()["services"].get(
                service_name
            )
            if not previous_image:
                logger.debug(
                    f'Service {service_name} not found in previous artifact metadata. Including image {current_image["ref"]} in full in the artifact accordingly.'
                )
                image_ids.add(self.prep_image(current_image))
            else:
                logger.debug(
                    f'Service {service_name} found in previous artifact metadata. Including image {current_image["ref"]} as a delta in the artifact accordingly.'
                )
                image_ids.add(
                    self.prep_image(current_image, delta_image=previous_image)
                )

        return image_ids

    @staticmethod
    def cli_arg_strings(args):
        return [
            arg_string
            for arg_key, arg_value in args.items()
            for arg_string in (
                [f"--{arg_key}"]
                if arg_value is True
                else (
                    [
                        pair_item
                        for arg_value_item in arg_value
                        for pair_item in [f"--{arg_key}", str(arg_value_item)]
                    ]
                    if isinstance(arg_value, list)
                    else [f"--{arg_key}", str(arg_value)]
                )
            )
        ]

    @staticmethod
    def call_mender_artifact(arg_list):
        rendered_args = "\n  ".join(arg_list)
        logger.debug(f"Calling mender-artifact with args: \n  {rendered_args}")
        try:
            result = subprocess.run(
                ["mender-artifact", *arg_list],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.debug(f"mender-artifact output: {result.stdout}")
            return result.stdout
        except subprocess.CalledProcessError as e:
            logger.error(
                f"mender-artifact \n  {rendered_args} failed: {e.stdout} {e.stderr}"
            )
            sys.exit(1)

    def create_artifact_file(self, image_ids, depends={}):
        self.artifact_name = f"{self.manifest_name}-{self.version}"
        self.artifact_file = self.repo_root_dir / f"{self.artifact_name}.mender"
        images_tar = self.prep_artifact_temp_dir / "images.tar.gz"
        manifests_tar = self.prep_artifact_temp_dir / "manifests.tar.gz"
        image_ids.sort()  # Sort only for determinism

        logger.debug(f"Creating artifact file: {self.artifact_file}")
        metadata = {
            "application-name": self.manifest_name,
            "orchestrator": "docker-compose",
            "platform": self.args.platform,
            "version": self.version,
            "images": image_ids,
        }

        metadata_file = self.prep_artifact_temp_dir / "metadata.json"
        with open(metadata_file, "w") as f:
            json.dump(metadata, f)

        # Create images as an empty dir if it has not already been created by prep_image
        (self.prep_artifact_temp_dir / "images").mkdir(exist_ok=True)
        with tarfile.open(str(images_tar), "w|gz") as tar:
            tar.add(self.prep_artifact_temp_dir / "images", arcname="images")

        shutil.copytree(
            (self.repo_root_dir / self.manifest_file).parent,
            self.prep_artifact_temp_dir / "manifests",
        )
        if self.service_images != {}:
            artifact_manifest_file = (
                self.prep_artifact_temp_dir / "manifests" / self.manifest_file.name
            )
            with open(artifact_manifest_file, "r") as f:
                manifest = yaml.safe_load(f.read())
            for service_name, image in self.service_images.items():
                logger.debug(
                    f"Applying service image override {service_name} to {image} to manifest in artifact..."
                )
                if service_name in manifest.get("services", {}):
                    manifest["services"][service_name]["image"] = image
            with open(artifact_manifest_file, "w") as f:
                yaml.safe_dump(manifest, f)
        with tarfile.open(str(manifests_tar), "w|gz") as tar:
            tar.add(self.prep_artifact_temp_dir / "manifests", arcname="manifests")

        self.call_mender_artifact(
            ["write", "module-image"]
            + self.cli_arg_strings(
                {
                    "type": "app",
                    "device-type": self.args.device_type,
                    "output-path": self.artifact_file,
                    "artifact-name": self.artifact_name,
                    "meta-data": metadata_file,
                    "file": [manifests_tar, images_tar],
                    "software-name": self.manifest_name,
                    "software-version": self.version,
                    **depends,
                }
            )
        )

    def call_mender_host_api(self, mender_endpoint, request_args):
        r = requests.post(
            f"{self.args.mender_host}/{mender_endpoint}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {os.getenv(MENDER_PAT_ENV_KEY)}",
            },
            **request_args,
        )
        if r.status_code != 201:
            logger.error(
                f"Request failed for endpoint {mender_endpoint}: status={r.status_code}, text={r.text}, url={r.request.url}, headers={r.request.headers}"
            )
            r.raise_for_status()
        else:
            return r

    def upload_artifact(self):
        with open(self.artifact_file, "rb") as file_contents:
            self.call_mender_host_api(
                "api/management/v1/deployments/artifacts",
                {
                    "data": {
                        "size": self.artifact_file.stat().st_size,
                        "description": "string",
                    },
                    "files": {"artifact": file_contents},
                },
            )
            logger.info(f"Uploaded artifact {self.artifact_file}")

    def deploy_artifact(self):
        deployment_name = (
            self.artifact_name
            if self.args.device_group is None
            else f"{self.artifact_name}-{self.args.device_group}"
        )
        deployment_spec = {
            "json": {
                "name": deployment_name,
                "artifact_name": self.artifact_name,
            }
        }

        if self.args.device_group is not None:
            logger.debug(
                f"Creating deployment for artifact {self.artifact_name} to device group {self.args.device_group}"
            )
            self.call_mender_host_api(
                f"api/management/v1/deployments/deployments/group/{self.args.device_group}",
                deployment_spec,
            )
            logger.info(f"Created deployment {deployment_name}")
        else:
            logger.debug(f"No device group set; skipping deployment creation.")

    def prep_artifact(self):
        self.previous_version = self.get_previous_version()
        self.version = self.get_current_version()
        self.prep_artifact_temp_dir = Path(
            tempfile.mkdtemp(dir=self.temp_artifacts_dir)
        )
        current_artifact_info = self.get_current_artifact_info()
        logger.debug(
            "Current artifact info: "
            + json.dumps(current_artifact_info.to_dict(), indent=2)
        )
        generate_delta_artifact = False
        if self.args.delta:
            try:
                previous_artifact_info = self.get_previous_artifact_info()
                generate_delta_artifact = True
            except ManifestNotFoundException:
                logger.info(
                    "Previous manifest not found; creating full artifact without delta."
                )
        if generate_delta_artifact:
            logger.debug(
                "Previous artifact info: "
                + json.dumps(previous_artifact_info.to_dict(), indent=2)
            )
            logger.info(
                f'Resolved previous artifact info for delta generation. Will depend on {previous_artifact_info.to_dict()["version"]}'
            )
            self.create_artifact_file(
                list(
                    self.prep_delta_images(
                        previous_artifact_info, current_artifact_info
                    )
                ),
                depends={
                    "depends": f'rootfs-image.{self.manifest_name}.version:{previous_artifact_info.to_dict()["version"]}'
                },
            )
        else:
            artifact_image_ids = set()
            for artifact_image in current_artifact_info.to_dict()["services"].values():
                artifact_image_ids.add(self.prep_image(artifact_image))
            self.create_artifact_file(list(artifact_image_ids))

        self.upload_artifact()
        self.deploy_artifact()
        logger.debug(
            f"Writing current artifact info to file: {self.previous_artifact_info_file}"
        )
        current_artifact_info.write_to_file(self.previous_artifact_info_file)


def main():
    parser = argparse.ArgumentParser(description="Mender Docker Artifact Helper")
    parser.add_argument(
        "--cache-dir",
        type=str,
        required=False,
        help="The cache dir to which the metadata for the previously uploaded aritfact is saved. Overrides the MENDER_HELPER_CACHE_DIR variable (default: ${XDG_CACHE_HOME}/mender-docker-lifecycle-helper if defined, else ~/.cache/mender-docker-lifecycle-helper)",
    )
    parser.add_argument(
        "--delta",
        type=lambda x: x.lower() in ["true", "t", "yes", "1"],
        default=True,
        help="Generate the artifact as an update artifact, if applicable (default: True)",
    )
    parser.add_argument(
        "--device-type",
        type=str,
        required=True,
        help="Device type for the artifact (required)",
    )
    parser.add_argument(
        "--device-group",
        type=str,
        default=None,
        help="Device group to which to deploy the artifact, or skip deployment if not defined (default: None)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set logging level (defaul: INFO)",
    )
    parser.add_argument(
        "--manifest-name",
        type=str,
        required=False,
        help="The application/software name for the artifact (default: immediate parent dir of manifest_file)",
    )
    parser.add_argument(
        "--mender-host",
        type=str,
        default="https://hosted.mender.io",
        help="Mender host URL for artifact upload and deployment (default: https://hosted.mender.io)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip reading previous artifact info from cache and always read from the repo at the previous version (default: False)",
    )
    parser.add_argument(
        "--platform",
        type=str,
        required=True,
        help="Platform with which the artifact is compatible (required, e.g., linux/arm/v7)",
    )
    parser.add_argument(
        "--previous-version",
        type=str,
        required=False,
        help="Repo ref from which to read image names and versions for comparison to the current state (default: read from VERSION file)",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="Create the artifact for a release, using the current value of the VERSION file as the artifact version and the value of the VERSION file at the previous commit as the --previous-version (default: False)",
    )
    parser.add_argument(
        "--service-image",
        action="append",
        metavar="SERVICE=IMAGE",
        help="Image name overrides for services in the manifest_file, as [service]=[image] (can be specified multiple times).",
    )
    parser.add_argument(
        "manifest_file",
        type=str,
        help="Path to the manifest file for which to generate the artifact (e.g., docker-compose.yaml)",
    )
    args = parser.parse_args()

    logger.setLevel(getattr(logging, args.log_level))

    helper = MenderDockerLifecycleHelper(args)
    helper.prep_artifact()


if __name__ == "__main__":
    main()
