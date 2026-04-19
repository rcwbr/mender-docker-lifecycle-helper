import json
import pytest
from pathlib import Path

from mender_docker_lifecycle_helper.artifact_metadata import ArtifactMetadata


def test_init_with_version_and_services():
    """Test ArtifactMetadata initialization with version and services."""
    version = "1.0.0"
    services = {
        "serviceA": {
            "image": {
                "ref": "my-image:latest",
                "hash": "abc123"
            }
        }
    }
    metadata = ArtifactMetadata(version, services)
    assert metadata.version == version
    assert metadata.services == services


def test_init_with_version_only():
    """Test ArtifactMetadata initialization with version only (services defaults to empty dict)."""
    version = "1.0.0"
    metadata = ArtifactMetadata(version, None)
    assert metadata.version == version
    assert metadata.services == {}


def test_init_with_empty_services():
    """Test ArtifactMetadata initialization with empty services dict."""
    version = "1.0.0"
    services = {}
    metadata = ArtifactMetadata(version, services)
    assert metadata.version == version
    assert metadata.services == services


def test_from_dict_basic():
    """Test ArtifactMetadata.from_dict with basic data."""
    data = {
        "version": "2.0.0",
        "services": {
            "serviceB": {
                "image": {
                    "ref": "nginx:alpine",
                    "hash": "def456"
                }
            }
        }
    }
    metadata = ArtifactMetadata.from_dict(data)
    assert metadata.version == data["version"]
    assert metadata.services == data["services"]


def test_from_dict_with_empty_services():
    """Test ArtifactMetadata.from_dict with empty services."""
    data = {
        "version": "3.0.0",
        "services": {}
    }
    metadata = ArtifactMetadata.from_dict(data)
    assert metadata.version == data["version"]
    assert metadata.services == data["services"]


def test_from_dict_with_missing_services():
    """Test ArtifactMetadata.from_dict when services key is missing."""
    data = {
        "version": "4.0.0"
    }
    metadata = ArtifactMetadata.from_dict(data)
    assert metadata.version == data["version"]
    assert metadata.services == {}


def test_from_dict_with_missing_version():
    """Test ArtifactMetadata.from_dict when version key is missing."""
    data = {
        "services": {
            "serviceC": {
                "image": {
                    "ref": "redis:latest",
                    "hash": "ghi789"
                }
            }
        }
    }
    metadata = ArtifactMetadata.from_dict(data)
    assert metadata.version is None
    assert metadata.services == data["services"]


def test_from_file_basic(tmp_path):
    """Test ArtifactMetadata.from_file with a basic JSON file."""
    file_path = tmp_path / "metadata.json"
    data = {
        "version": "5.0.0",
        "services": {
            "serviceD": {
                "image": {
                    "ref": "postgres:13",
                    "hash": "jkl012"
                }
            }
        }
    }
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)

    metadata = ArtifactMetadata.from_file(file_path)
    assert metadata.version == data["version"]
    assert metadata.services == data["services"]


def test_to_dict_roundtrip():
    """Test that to_dict produces the expected structure."""
    version = "6.0.0"
    services = {
        "serviceE": {
            "image": {
                "ref": "mongo:5.0",
                "hash": "mno345"
            }
        },
        "serviceF": {
            "image": {
                "ref": "elasticsearch:8.0",
                "hash": "pqr678"
            }
        }
    }
    metadata = ArtifactMetadata(version, services)
    result = metadata.to_dict()

    assert result["version"] == version
    assert result["services"] == services


def test_to_file_roundtrip(tmp_path):
    """Test that to_file creates a file that can be read back correctly."""
    file_path = tmp_path / "output.json"
    version = "7.0.0"
    services = {
        "serviceG": {
            "image": {
                "ref": "kafka:latest",
                "hash": "stu901"
            }
        }
    }
    original_metadata = ArtifactMetadata(version, services)

    # Write to file
    original_metadata.to_file(file_path)

    # Read back
    loaded_metadata = ArtifactMetadata.from_file(file_path)

    assert loaded_metadata.version == original_metadata.version
    assert loaded_metadata.services == original_metadata.services


def test_to_file_creates_directories(tmp_path):
    """Test that to_file creates parent directories if they don't exist."""
    nested_path = tmp_path / "nested" / "deep" / "metadata.json"
    version = "8.0.0"
    services = {}
    metadata = ArtifactMetadata(version, services)

    metadata.to_file(nested_path)

    assert nested_path.exists()
    loaded_metadata = ArtifactMetadata.from_file(nested_path)
    assert loaded_metadata.version == version
    assert loaded_metadata.services == services


def test_empty_initialization():
    """Test ArtifactMetadata initialization with empty/None values."""
    metadata = ArtifactMetadata("", None)
    assert metadata.version == ""
    assert metadata.services == {}


if __name__ == "__main__":
    pytest.main([__file__])