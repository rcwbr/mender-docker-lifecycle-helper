import uuid

from pathlib import Path

from mender_docker_lifecycle_helper.artifact_metadata import ArtifactMetadata
from mender_docker_lifecycle_helper.context import LifecycleHelperContext
from mender_docker_lifecycle_helper.artifact import LifecycleHelperArtifact


class LifecycleHelper:
    def __init__(self, args):
        self.context = LifecycleHelperContext(args)

    def create_artifact(self, artifact_metadata: ArtifactMetadata) -> Path:
        """
        Generate the Mender artifact for the specified metadata.

        :param artifact_metadata: The metadata for the artifact to generate.

        :returns: The path to the generated artifact file.
        """
        artifact = LifecycleHelperArtifact(
            self.context,
            f"{self.context.manifest_name}-{artifact_metadata.version}",
            artifact_metadata
        )
        artifact_filename = (
            self.context.artifact_filename
            if self.context.artifact_filename is not None
            else f"{artifact.name}.mender"
        )
        self.context.logger.info(f"Generating artifact file {artifact_filename}")
        artifact.gen_artifact_file(artifact_filename)
        self.context.logger.info("Artifact file generated successfully.")
        return artifact_filename

    def upload_artifact(self):
        """
        Upload the specified artifact file
        """
        pass

    def deploy_artifact(self):
        pass

    def prep_artifact(self):
        artifact_version = None
        if self.context.release:
            self.context.logger.info("Preparing an artifact for release, so using the repo version.")
            artifact_version = self.context.repo_version
        else:
            artifact_version = f"{self.context.previous_artifact_metadata.version}+{self.context.commit_short_sha}+{uuid.uuid4()}"
        self.context.logger.info(f"Preparing an artifact with the version {artifact_version}")

        artifact_metadata = ArtifactMetadata(
            artifact_version,
            services=LifecycleHelperArtifact.gen_artifact_services(self.context)
        )
        artifact_filename = self.create_artifact(artifact_metadata)
        self.upload_artifact(artifact_filename)
        self.deploy_artifact()
        # TODO Write metadata to cache
