import uuid

from pathlib import Path

from types import SimpleNamespace

from mender_docker_lifecycle_helper.utils.mender_server import (
    call_mender_host_api,
    upload_artifact,
    wait_for_deployment,
)
from mender_docker_lifecycle_helper.artifact_metadata import ArtifactMetadata
from mender_docker_lifecycle_helper.context import LifecycleHelperContext
from mender_docker_lifecycle_helper.artifact import LifecycleHelperArtifact


class ArtifactDeployFailure(Exception):
    pass


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
        :return: The object representing the generated artifact.
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

    def deploy_artifact(self, artifact: LifecycleHelperArtifact) -> str:
        """
        Issue a deployment of a pre-uploaded artifact.

        :param artifact: The object of the artifact to deploy to the Mender server.
        :return: The deployment ID.
        """
        deployment_name = f"{artifact.name}-{self.context.device_group}"

        self.context.logger.debug(
            f"Creating deployment for artifact {artifact.name} to device group {self.context.device_group}"
        )
        response = call_mender_host_api(
            self.context,
            f"deployments/deployments/group/{self.context.device_group}",
            {
                "json": {
                    "name": deployment_name,
                    "artifact_name": artifact.name,
                }
            },
        )
        deployment_id = None
        if "Location" in response.headers:
            location = response.headers["Location"]
            # Location header format: /deployments/v1/deployments/{deploymentId}
            deployment_id = location.rstrip("/").split("/")[-1]
            self.context.logger.debug(
                f"Got deployment ID from Location header: {deployment_id}"
            )
        else:
            self.context.logger.error(
                f"Could not extract deployment ID from response. "
                f"Body: {response.text!r}, Headers: {dict(response.headers)}"
            )
            raise ValueError(
                "Could not determine deployment ID from Mender API response"
            )
        self.context.logger.info(
            f"Created deployment {deployment_name} (ID: {deployment_id})"
        )
        return deployment_id

    def update_cache_artifact_metadata(
        self, artifact_metadata: ArtifactMetadata
    ) -> None:
        """
        Write the specified artifact metadata to the cache previous metadata location, if applicable.

        :param artifact_metadata: The artifact metadata object to write to the cache.
        """
        if self.context.cache:
            self.context.logger.debug(
                f"Updating cached metadata at {self.context.cache_artifact_metadata_file}"
            )
            artifact_metadata.to_file(self.context.cache_artifact_metadata_file)

    def prep_artifact(self) -> None:
        """
        Prepare the artifact, including creation, upload, and deployment as specified by provided args.

        :return: None
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
        upload_artifact(self.context, artifact)

        if self.context.device_group is not None:
            deployment_id = self.deploy_artifact(artifact)

            if self.context.wait_for_deploy:
                self.context.logger.info(
                    f"Waiting for deployment {deployment_id} to complete..."
                )
                if wait_for_deployment(self.context, deployment_id):
                    self.context.logger.debug(
                        f"Deployment {deployment_id} for {artifact.name} succeeded."
                    )
                    self.update_cache_artifact_metadata(artifact_metadata)
                else:
                    raise ArtifactDeployFailure(
                        f"Deployment {deployment_id} did not succeed; "
                        "cached metadata will not be updated."
                    )
            else:
                self.context.logger.debug(f"Artifact {artifact.name} deployed.")
                self.update_cache_artifact_metadata(artifact_metadata)
        else:
            self.context.logger.debug(
                "No device group set; skipping deployment creation."
            )

        self.context.logger.info(f"Artifact {artifact.name} successfully processed!")
