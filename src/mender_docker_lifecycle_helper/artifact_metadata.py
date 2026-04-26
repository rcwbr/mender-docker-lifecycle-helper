import json

from pathlib import Path
from typing import Optional


class ArtifactMetadata:
    def __init__(
        self, version: str, services: Optional[dict[str, dict[str, dict[str, str]]]]
    ):
        """
        Construct an ArtifactMetadata object.

        :param version: The version identifier for the artifact.
        :param services: The metadata of the services included in the artifact. The structure of this metadata is:
            {
                serviceName: {
                    image: {
                        ref: str,
                        hash: str
                    }
                }
            }
        """
        self.version = version
        self.services = services if services is not None else {}

    @classmethod
    def from_dict(cls, data: dict[str, dict[str, dict[str, dict[str, str]]]]):
        """
        Construct an ArtifactMetadata object directly from a dict.

        :param data: The metadata for the artifact, structured as the to_dict return value.
        :return: An object constructed from the provided data.
        """
        return cls(version=data.get("version"), services=data.get("services", {}))

    @classmethod
    def from_file(cls, file_path: Path):
        """
        Construct an ArtifactMetadata object directly from a file.

        :param file_path: The path to a JSON file containing the artifact metadata, structured as the to_dict return value.
        :return: An object constructed from the provided file.
        """
        with open(file_path, "r") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def to_dict(self):
        """
        Dump the contents of the artifact metadata as a dict.

        :return: The metadata of the artifact, structured as:
            {
                version: str,
                services: {
                    ... (see services param in __init__)
                }
            }
        """
        return {"version": self.version, "services": self.services}

    def to_file(self, file_path: Path):
        """
        Dump the contents of the artifact metadata to a file, as JSON structured as the to_dict return value.

        :param file_path: The path to which to dump the metadata of the artifact.
        :return: None
        """
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
