import uuid

from pathlib import Path

from types import SimpleNamespace

from mender_docker_lifecycle_helper.utils.mender_server import call_mender_host_api
from mender_docker_lifecycle_helper.artifact_metadata import ArtifactMetadata
from mender_docker_lifecycle_helper.context import LifecycleHelperContext
from mender_docker_lifecycle_helper.artifact import LifecycleHelperArtifact


class LifecycleHelper:
    """
    Representation of the lifecycle helper execution.
    """

    def __init__(self, args: SimpleNamespace):
        """
        Construct a LifecycleHelper object.

        :param args: An object of the args for the helper execution. See cli.py.
        """
        self.context = LifecycleHelperContext(args)

    def create_artifact(
        self, artifact_metadata: ArtifactMetadata
    ) -> LifecycleHelperArtifact:
        """
        Generate the Mender artifact for the specified metadata.

        :param artifact_metadata: The metadata for the artifact to generate.

        :returns: The object representing the generated artifact.
        """
        artifact_name = f"{self.context.manifest_name}-{artifact_metadata.version}"
        artifact_filename = Path(
            self.context.artifact_filename
            if self.context.artifact_filename is not None
            else f"{artifact_name}.mender"
        ).resolve()
        artifact = LifecycleHelperArtifact(
            self.context, artifact_name, artifact_metadata, artifact_filename
        )
        self.context.logger.info(f"Generating artifact file {artifact_filename}")
        artifact.gen_artifact_file()
        self.context.logger.info("Artifact file generated successfully.")
        return artifact

    def upload_artifact(self, artifact: LifecycleHelperArtifact) -> None:
        """
        Upload the specified artifact file to the Mender server.

        :param artifact: The object of the artifact to upload to the Mender server.

        :returns: None
        """
        with open(artifact.filename, "rb") as file_contents:
            call_mender_host_api(
                self.context,
                "deployments/artifacts",
                {
                    "data": {
                        "size": artifact.filename.stat().st_size,
                        "description": "string",
                    },
                    "files": {"artifact": file_contents},
                },
            )
            self.context.logger.info(f"Uploaded artifact {artifact.filename}")

    def deploy_artifact(self, artifact: LifecycleHelperArtifact) -> None:
        """
        Issue a deployment of a pre-uploaded artifact.

        :returns: None
        """
        deployment_name = f"{artifact.name}-{self.context.device_group}"

        self.context.logger.debug(
            f"Creating deployment for artifact {artifact.name} to device group {self.context.device_group}"
        )
        call_mender_host_api(
            self.context,
            f"deployments/deployments/group/{self.context.device_group}",
            {
                "json": {
                    "name": deployment_name,
                    "artifact_name": artifact.name,
                }
            },
        )
        self.context.logger.info(f"Created deployment {deployment_name}")

    def prep_artifact(self) -> None:
        """
        Prepare the artifact, including creation, upload, and deployment as specified by provided args.

        :returns: None
        """
        artifact_version = None
        if self.context.release:
            self.context.logger.info(
                "Preparing an artifact for release, so using the repo version."
            )
            artifact_version = self.context.repo_version
        else:
            artifact_version = f"{self.context.repo_version}+{self.context.commit_short_sha}+{uuid.uuid4()}"
        self.context.logger.info(
            f"Preparing an artifact with the version {artifact_version}"
        )

        artifact_metadata = ArtifactMetadata(
            artifact_version,
            services=LifecycleHelperArtifact.gen_artifact_services(self.context),
        )
        artifact = self.create_artifact(artifact_metadata)
        self.upload_artifact(artifact)

        if self.context.device_group is not None:
            self.deploy_artifact(artifact)
            self.context.logger.debug(
                f"Artifact {artifact.name} deployed; updating cached metadata at {self.context.cache_artifact_metadata_file}"
            )
            artifact_metadata.to_file(self.context.cache_artifact_metadata_file)
        else:
            self.context.logger.debug(
                "No device group set; skipping deployment creation."
            )

        self.context.logger.info(f"Artifact {artifact.name} successfully processed!")
