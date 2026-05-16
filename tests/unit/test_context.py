"""Unit tests for the LifecycleHelperContext class."""

import git
import json
import logging
import os
import pytest
import subprocess
import yaml

from pathlib import Path
from types import SimpleNamespace

from mender_docker_lifecycle_helper.context import LifecycleHelperContext


@pytest.fixture
def dummy_args():
    return SimpleNamespace(
        artifact_filename="artifact_filename",
        cache="cache",
        cache_dir="cache_dir",
        delta="delta",
        device_type="device_type",
        device_group="device_group",
        log_level="log_level",
        manifest_file=Path("manifest_file"),
        manifest_name="manifest_name",
        mender_host="https://hosted.mender.io",
        platform="platform",
        previous_version="previous_version",
        release="release",
        service_files="service_files",
        service_images="service_images",
        wait_for_deploy=True,
    )


@pytest.fixture
def mender_pat_env(monkeypatch):
    monkeypatch.setenv("MENDER_PAT", "test-pat-token")
    return "test-pat-token"


class TestLifecycleHelperContextInitMock:
    """Tests for LifecycleHelperContext initialization with mocks."""

    def test_init_minimal(self, tmp_path, dummy_args: SimpleNamespace, mender_pat_env):
        """Test __init__ minimal case with mocking."""
        dummy_args.manifest_file = tmp_path / dummy_args.manifest_file.name
        dummy_args.manifest_file.touch()
        dummy_args.cache = False
        dummy_args.delta = False

        repo = git.Repo.init(tmp_path)
        repo.index.add(dummy_args.manifest_file.name)
        repo.index.commit("init")

        context = SimpleNamespace(
            _prep_logger=lambda log_level: log_level,
            _repo_root_dir=lambda file: tmp_path,
            _repo_version=lambda folder: folder,
            _compose_content_from_file=lambda file: None,
            manifest_file=None,
        )
        LifecycleHelperContext.__init__(
            context,
            dummy_args,
        )

        assert context.logger == "log_level"
        assert context.artifact_filename == "artifact_filename"
        assert context.cache == False
        assert context.commit_short_sha == repo.head.commit.hexsha[:7]
        assert context.delta == False
        assert context.device_type == "device_type"
        assert context.device_group == "device_group"
        assert (
            context.manifest_file
            == (tmp_path / dummy_args.manifest_file.name).resolve()
        )
        assert context.manifest == None
        assert context.manifest_name == "manifest_name"
        assert context.mender_host == "https://hosted.mender.io"
        assert context.mender_pat == "test-pat-token"
        assert context.platform == "platform"
        assert context.release == "release"
        assert context.repo_root_dir == tmp_path
        assert context.repo_version == tmp_path
        assert context.service_files == "service_files"
        assert context.service_images == "service_images"

    def test_init_infer_manifest_name(
        self, tmp_path, dummy_args: SimpleNamespace, mender_pat_env
    ):
        """Test __init__ inferred manifest_name case with mocking."""
        tmp_path = tmp_path / "test-repo"
        app_dir = tmp_path / "my-app"
        app_dir.mkdir(parents=True)
        dummy_args.manifest_file = app_dir / dummy_args.manifest_file.name
        dummy_args.manifest_file.touch()
        dummy_args.cache = False
        dummy_args.delta = False
        dummy_args.manifest_name = None

        repo = git.Repo.init(tmp_path)
        repo.index.add(app_dir.name)
        repo.index.commit("init")

        context = SimpleNamespace(
            _prep_logger=lambda log_level: log_level,
            _repo_root_dir=lambda file: tmp_path,
            _repo_version=lambda folder: folder,
            _compose_content_from_file=lambda file: None,
            manifest_file=None,
        )
        LifecycleHelperContext.__init__(
            context,
            dummy_args,
        )

        assert context.logger == "log_level"
        assert context.artifact_filename == "artifact_filename"
        assert context.cache == False
        assert context.commit_short_sha == repo.head.commit.hexsha[:7]
        assert context.delta == False
        assert context.device_type == "device_type"
        assert context.device_group == "device_group"
        assert (
            context.manifest_file == (app_dir / dummy_args.manifest_file.name).resolve()
        )
        assert context.manifest == None
        assert context.manifest_name == "test-repo-my-app"
        assert context.mender_host == "https://hosted.mender.io"
        assert context.mender_pat == "test-pat-token"
        assert context.platform == "platform"
        assert context.release == "release"
        assert context.repo_root_dir == tmp_path
        assert context.repo_version == tmp_path
        assert context.service_files == "service_files"
        assert context.service_images == "service_images"

    def test_init_new_cache(
        self, tmp_path, dummy_args: SimpleNamespace, mender_pat_env
    ):
        """Test __init__ new cache case with mocking."""
        dummy_args.manifest_file = tmp_path / dummy_args.manifest_file.name
        dummy_args.manifest_file.touch()
        dummy_args.cache = True
        dummy_args.cache_dir = tmp_path / "cache"
        dummy_args.delta = False

        repo = git.Repo.init(tmp_path)
        repo.index.add(dummy_args.manifest_file.name)
        repo.index.commit("init")

        context = SimpleNamespace(
            _prep_logger=lambda log_level: log_level,
            _prep_cache_dir=lambda cache_dir: LifecycleHelperContext._prep_cache_dir(
                SimpleNamespace(logger=logging.Logger("test_logger")), cache_dir
            ),
            _repo_root_dir=lambda file: tmp_path,
            _repo_version=lambda folder: folder,
            _compose_content_from_file=lambda file: None,
            manifest_file=None,
        )
        LifecycleHelperContext.__init__(
            context,
            dummy_args,
        )

        assert context.logger == "log_level"
        assert context.artifact_filename == "artifact_filename"
        assert context.cache == True
        assert context.cache_dir == dummy_args.cache_dir
        assert context.cache_artifact_metadata_file == (
            dummy_args.cache_dir
            / "manifests"
            / "manifest_name"
            / "previous_artifact.json"
        )
        assert context.commit_short_sha == repo.head.commit.hexsha[:7]
        assert context.delta == False
        assert context.device_type == "device_type"
        assert context.device_group == "device_group"
        assert (
            context.manifest_file
            == (tmp_path / dummy_args.manifest_file.name).resolve()
        )
        assert context.manifest == None
        assert context.manifest_name == "manifest_name"
        assert context.mender_host == "https://hosted.mender.io"
        assert context.mender_pat == "test-pat-token"
        assert context.platform == "platform"
        assert context.release == "release"
        assert context.repo_root_dir == tmp_path
        assert context.repo_version == tmp_path
        assert context.service_files == "service_files"
        assert context.service_images == "service_images"
        assert context.temp_dir == dummy_args.cache_dir / "temp"

        assert dummy_args.cache_dir.exists()
        assert dummy_args.cache_dir.is_dir()
        assert (dummy_args.cache_dir / "temp").exists()
        assert (dummy_args.cache_dir / "temp").is_dir()
        assert (dummy_args.cache_dir / "manifests").exists()
        assert (dummy_args.cache_dir / "manifests").is_dir()
        assert (dummy_args.cache_dir / "manifests" / "manifest_name").exists()
        assert (dummy_args.cache_dir / "manifests" / "manifest_name").is_dir()

    def test_init_existing_cache(
        self, tmp_path, dummy_args: SimpleNamespace, mender_pat_env
    ):
        """Test __init__ existing cache case with mocking."""
        dummy_args.manifest_file = tmp_path / dummy_args.manifest_file.name
        dummy_args.manifest_file.touch()
        dummy_args.cache = True
        dummy_args.cache_dir = tmp_path / "cache"
        dummy_args.cache_dir.mkdir()
        (dummy_args.cache_dir / "manifests" / "manifest_name").mkdir(parents=True)
        dummy_args.delta = False

        repo = git.Repo.init(tmp_path)
        repo.index.add(dummy_args.manifest_file.name)
        repo.index.commit("init")

        context = SimpleNamespace(
            _prep_logger=lambda log_level: log_level,
            _prep_cache_dir=lambda cache_dir: LifecycleHelperContext._prep_cache_dir(
                SimpleNamespace(logger=logging.Logger("test_logger")), cache_dir
            ),
            _repo_root_dir=lambda file: tmp_path,
            _repo_version=lambda folder: folder,
            _compose_content_from_file=lambda file: None,
            manifest_file=None,
        )
        LifecycleHelperContext.__init__(
            context,
            dummy_args,
        )

        assert context.logger == "log_level"
        assert context.artifact_filename == "artifact_filename"
        assert context.cache == True
        assert context.cache_dir == dummy_args.cache_dir
        assert context.cache_artifact_metadata_file == (
            dummy_args.cache_dir
            / "manifests"
            / "manifest_name"
            / "previous_artifact.json"
        )
        assert context.commit_short_sha == repo.head.commit.hexsha[:7]
        assert context.delta == False
        assert context.device_type == "device_type"
        assert context.device_group == "device_group"
        assert (
            context.manifest_file
            == (tmp_path / dummy_args.manifest_file.name).resolve()
        )
        assert context.manifest == None
        assert context.manifest_name == "manifest_name"
        assert context.mender_host == "https://hosted.mender.io"
        assert context.mender_pat == "test-pat-token"
        assert context.platform == "platform"
        assert context.release == "release"
        assert context.repo_root_dir == tmp_path
        assert context.repo_version == tmp_path
        assert context.service_files == "service_files"
        assert context.service_images == "service_images"
        assert context.temp_dir == dummy_args.cache_dir / "temp"

        assert dummy_args.cache_dir.exists()
        assert dummy_args.cache_dir.is_dir()
        assert (dummy_args.cache_dir / "temp").exists()
        assert (dummy_args.cache_dir / "temp").is_dir()
        assert (dummy_args.cache_dir / "manifests").exists()
        assert (dummy_args.cache_dir / "manifests").is_dir()
        assert (dummy_args.cache_dir / "manifests" / "manifest_name").exists()
        assert (dummy_args.cache_dir / "manifests" / "manifest_name").is_dir()

    def test_init_delta(self, tmp_path, dummy_args: SimpleNamespace, mender_pat_env):
        """Test __init__ delta case with mocking."""
        dummy_args.manifest_file = tmp_path / dummy_args.manifest_file.name
        dummy_args.manifest_file.touch()
        dummy_args.cache = False
        dummy_args.delta = True

        repo = git.Repo.init(tmp_path)
        repo.index.add(dummy_args.manifest_file.name)
        repo.index.commit("init")

        context = SimpleNamespace(
            _prep_logger=lambda log_level: log_level,
            _prep_previous_artifact_metadata=lambda version: version,
            _repo_root_dir=lambda file: tmp_path,
            _repo_version=lambda folder: folder,
            _compose_content_from_file=lambda file: None,
            manifest_file=None,
        )
        LifecycleHelperContext.__init__(
            context,
            dummy_args,
        )

        assert context.logger == "log_level"
        assert context.artifact_filename == "artifact_filename"
        assert context.cache == False
        assert context.commit_short_sha == repo.head.commit.hexsha[:7]
        assert context.delta == True
        assert context.device_type == "device_type"
        assert context.device_group == "device_group"
        assert (
            context.manifest_file
            == (tmp_path / dummy_args.manifest_file.name).resolve()
        )
        assert context.manifest == None
        assert context.manifest_name == "manifest_name"
        assert context.mender_host == "https://hosted.mender.io"
        assert context.mender_pat == "test-pat-token"
        assert context.platform == "platform"
        assert context.previous_artifact_metadata == "previous_version"
        assert context.release == "release"
        assert context.repo_root_dir == tmp_path
        assert context.repo_version == tmp_path
        assert context.service_files == "service_files"
        assert context.service_images == "service_images"


class TestLifecycleHelperContextInitIntegration:
    """Tests for LifecycleHelperContext initialization as full integration."""

    def test_init_existing_previous_metadata(self, tmp_path, monkeypatch):
        """Test __init__ existing previous_metadata case."""
        monkeypatch.setenv("MENDER_PAT", "test-pat-token")
        repo_dir = tmp_path / "test-repo"
        manifest_dir = repo_dir / "my-app"
        manifest_dir.mkdir(parents=True)
        cache_dir = tmp_path / "cache"
        previous_artifact_cache_dir = cache_dir / "manifests" / "test-repo-my-app"
        previous_artifact_cache_dir.mkdir(parents=True)

        manifest_file = manifest_dir / "docker-compose.yaml"
        manifest_contents = {
            "services": {"server": {"image": "my-server", "ports": ["8080"]}}
        }
        manifest_file.write_text(yaml.dump(manifest_contents))

        version_file = repo_dir / "VERSION"
        version_file.write_text("1.0.0")

        previous_artifact_cache_file = (
            previous_artifact_cache_dir / "previous_artifact.json"
        )
        previous_artifact_metadata = {
            "version": "1.0.0+abcdef1234356",
            "services": {
                "server": {"image": {"ref": "my-server", "hash": "987656fedcba"}}
            },
        }
        previous_artifact_cache_file.write_text(json.dumps(previous_artifact_metadata))

        repo = git.Repo.init(repo_dir)
        repo.index.add(manifest_file)
        repo.index.add(version_file)
        repo.index.commit("init")

        context = LifecycleHelperContext(
            SimpleNamespace(
                artifact_filename=None,
                cache=True,
                cache_dir=cache_dir,
                delta=True,
                device_type="virtual",
                device_group="test-group",
                log_level="DEBUG",
                manifest_file=manifest_file,
                manifest_name=None,
                mender_host="https://hosted.mender.io",
                platform="platform",
                previous_version=None,
                release=False,
                service_files=None,
                service_images=None,
                wait_for_deploy=True,
            )
        )
        assert context.artifact_filename == None
        assert context.cache == True
        assert context.cache_artifact_metadata_file == previous_artifact_cache_file
        assert context.commit_short_sha == repo.head.commit.hexsha[:7]
        assert context.delta == True
        assert context.device_type == "virtual"
        assert context.device_group == "test-group"
        assert context.image_cache.delta_cache_dir == cache_dir / "images" / "delta"
        assert context.image_cache.extract_cache_dir == cache_dir / "images" / "extract"
        assert context.image_cache.save_cache_dir == cache_dir / "images" / "save"
        assert context.logger.level == getattr(logging, "DEBUG")
        assert context.manifest_file == manifest_file
        assert context.manifest == {
            "name": "my-app",
            "networks": {
                "default": {
                    "name": "my-app_default",
                }
            },
            "services": {
                "server": {
                    "image": "my-server",
                    "networks": {"default": None},
                    "ports": [{"mode": "ingress", "protocol": "tcp", "target": 8080}],
                }
            },
        }
        assert context.manifest_name == "test-repo-my-app"
        assert context.mender_host == "https://hosted.mender.io"
        assert context.mender_pat == "test-pat-token"
        assert context.platform == "platform"
        assert (
            context.previous_artifact_metadata.to_dict() == previous_artifact_metadata
        )
        assert context.release == False
        assert context.repo_root_dir == repo_dir
        assert context.repo_version == "1.0.0"
        assert context.service_files == None
        assert context.service_images == None
        assert context.temp_dir == cache_dir / "temp"

    def test_init_no_cache(self, tmp_path, monkeypatch):
        """Test __init__ no cache case."""
        monkeypatch.setenv("MENDER_PAT", "test-pat-token")
        repo_dir = tmp_path / "test-repo"
        manifest_dir = repo_dir / "my-app"
        manifest_dir.mkdir(parents=True)
        cache_dir = tmp_path / "cache"
        previous_artifact_cache_dir = cache_dir / "manifests" / "test-repo-my-app"
        previous_artifact_cache_dir.mkdir(parents=True)

        manifest_file = manifest_dir / "docker-compose.yaml"
        manifest_contents = {
            "services": {"server": {"image": "my-server", "ports": ["8080"]}}
        }
        manifest_file.write_text(yaml.dump(manifest_contents))

        version_file = repo_dir / "VERSION"
        version_file.write_text("1.0.0")

        previous_artifact_cache_file = (
            previous_artifact_cache_dir / "previous_artifact.json"
        )
        previous_artifact_metadata = {
            "version": "1.0.0+abcdef1234356",
            "services": {
                "server": {"image": {"ref": "my-server", "hash": "987656fedcba"}}
            },
        }
        previous_artifact_cache_file.write_text(json.dumps(previous_artifact_metadata))

        repo = git.Repo.init(repo_dir)
        repo.index.add(manifest_file)
        repo.index.add(version_file)
        repo.index.commit("init")
        repo.create_tag("1.0.0")

        manifest_contents_new = {
            "services": {"server": {"image": "my-server-new", "ports": ["8081"]}}
        }
        manifest_file.write_text(yaml.dump(manifest_contents_new))
        repo.index.add(manifest_file)
        repo.index.commit("update")

        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.context.get_image_hash",
            lambda ref, logger: "abcd1243",
        )
        context = LifecycleHelperContext(
            SimpleNamespace(
                artifact_filename=None,
                cache=False,
                cache_dir=cache_dir,
                delta=True,
                device_type="virtual",
                device_group="test-group",
                log_level="DEBUG",
                manifest_file=manifest_file,
                manifest_name=None,
                mender_host="https://hosted.mender.io",
                platform="platform",
                previous_version=None,
                release=False,
                service_files=None,
                service_images=None,
                wait_for_deploy=True,
            )
        )
        assert context.artifact_filename == None
        assert context.cache == False
        assert context.commit_short_sha == repo.head.commit.hexsha[:7]
        assert context.delta == True
        assert context.device_type == "virtual"
        assert context.device_group == "test-group"
        assert context.logger.level == getattr(logging, "DEBUG")
        assert context.manifest_file == manifest_file
        assert context.manifest == {
            "name": "my-app",
            "networks": {
                "default": {
                    "name": "my-app_default",
                }
            },
            "services": {
                "server": {
                    "image": "my-server-new",
                    "networks": {"default": None},
                    "ports": [{"mode": "ingress", "protocol": "tcp", "target": 8081}],
                }
            },
        }
        assert context.manifest_name == "test-repo-my-app"
        assert context.mender_host == "https://hosted.mender.io"
        assert context.mender_pat == "test-pat-token"
        assert context.platform == "platform"
        assert context.previous_artifact_metadata.to_dict() == {
            "version": "1.0.0",
            "services": {"server": {"image": {"ref": "my-server", "hash": "abcd1243"}}},
        }
        assert context.release == False
        assert context.repo_root_dir == repo_dir
        assert context.repo_version == "1.0.0"
        assert context.service_files == None
        assert context.service_images == None

    def test_init_release(self, tmp_path, monkeypatch):
        """Test __init__ release case."""
        monkeypatch.setenv("MENDER_PAT", "test-pat-token")
        repo_dir = tmp_path / "test-repo"
        manifest_dir = repo_dir / "my-app"
        manifest_dir.mkdir(parents=True)
        cache_dir = tmp_path / "cache"
        previous_artifact_cache_dir = cache_dir / "manifests" / "test-repo-my-app"
        previous_artifact_cache_dir.mkdir(parents=True)

        manifest_file = manifest_dir / "docker-compose.yaml"
        manifest_contents = {
            "services": {"server": {"image": "my-server", "ports": ["8080"]}}
        }
        manifest_file.write_text(yaml.dump(manifest_contents))

        version_file = repo_dir / "VERSION"
        version_file.write_text("1.0.0")

        previous_artifact_cache_file = (
            previous_artifact_cache_dir / "previous_artifact.json"
        )
        previous_artifact_metadata = {
            "version": "1.0.0+abcdef1234356",
            "services": {
                "server": {"image": {"ref": "my-server", "hash": "987656fedcba"}}
            },
        }
        previous_artifact_cache_file.write_text(json.dumps(previous_artifact_metadata))

        repo = git.Repo.init(repo_dir, initial_branch="main")
        repo.index.add(manifest_file)
        repo.index.add(version_file)
        repo.index.commit("init")
        repo.create_tag("1.0.0")

        manifest_contents_new = {
            "services": {"server": {"image": "my-server-new", "ports": ["8081"]}}
        }
        manifest_file.write_text(yaml.dump(manifest_contents_new))
        version_file.write_text("1.1.0")
        branch = repo.create_head("feature").checkout()
        repo.index.add(manifest_file)
        repo.index.add(version_file)
        repo.index.commit("update")
        repo.merge_base(branch, repo.heads.main)

        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.context.get_image_hash",
            lambda ref, logger: "abcd1243",
        )
        context = LifecycleHelperContext(
            SimpleNamespace(
                artifact_filename=None,
                cache=False,
                cache_dir=cache_dir,
                delta=True,
                device_type="virtual",
                device_group="test-group",
                log_level="DEBUG",
                manifest_file=manifest_file,
                manifest_name=None,
                mender_host="https://hosted.mender.io",
                platform="platform",
                previous_version=None,
                release=True,
                service_files=None,
                service_images=None,
                wait_for_deploy=True,
            )
        )
        assert context.artifact_filename == None
        assert context.cache == False
        assert context.commit_short_sha == repo.head.commit.hexsha[:7]
        assert context.delta == True
        assert context.device_type == "virtual"
        assert context.device_group == "test-group"
        assert context.logger.level == getattr(logging, "DEBUG")
        assert context.manifest_file == manifest_file
        assert context.manifest == {
            "name": "my-app",
            "networks": {
                "default": {
                    "name": "my-app_default",
                }
            },
            "services": {
                "server": {
                    "image": "my-server-new",
                    "networks": {"default": None},
                    "ports": [{"mode": "ingress", "protocol": "tcp", "target": 8081}],
                }
            },
        }
        assert context.manifest_name == "test-repo-my-app"
        assert context.mender_host == "https://hosted.mender.io"
        assert context.mender_pat == "test-pat-token"
        assert context.platform == "platform"
        assert context.previous_artifact_metadata.to_dict() == {
            "version": "1.0.0",
            "services": {"server": {"image": {"ref": "my-server", "hash": "abcd1243"}}},
        }
        assert context.release == True
        assert context.repo_root_dir == repo_dir
        assert context.repo_version == "1.1.0"
        assert context.service_files == None
        assert context.service_images == None


class TestMenderPAT:
    """Tests for the mender_pat field."""

    def test_mender_pat_from_env(self, tmp_path, monkeypatch):
        """Test that mender_pat is read from MENDER_PAT env var."""
        monkeypatch.setenv("MENDER_PAT", "my-pat-token")
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        context = LifecycleHelperContext.__new__(LifecycleHelperContext)
        context.mender_pat = os.getenv("MENDER_PAT")
        context.cache = True  # Avoid __del__ attempting to remove cache_dir
        context.temp_dir = temp_dir  # Use real temp_dir for __del__ cleanup
        assert context.mender_pat == "my-pat-token"

    def test_mender_pat_not_set(self, tmp_path, monkeypatch):
        """Test that mender_pat is None when MENDER_PAT is not set."""
        monkeypatch.delenv("MENDER_PAT", raising=False)
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        context = LifecycleHelperContext.__new__(LifecycleHelperContext)
        context.mender_pat = os.getenv("MENDER_PAT")
        context.cache = True  # Avoid __del__ attempting to remove cache_dir
        context.temp_dir = temp_dir  # Use real temp_dir for __del__ cleanup
        assert context.mender_pat is None


class TestLifecycleHelperContextDel:
    """Tests for the LifecycleHelperContext deletion."""

    def test_del_cache(self, tmp_path):
        temp_dir = tmp_path / "cache" / "temp"
        temp_dir.mkdir(parents=True)
        LifecycleHelperContext.__del__(SimpleNamespace(cache=True, temp_dir=temp_dir))
        assert not temp_dir.exists()


class TestDefaultCacheDir:
    """Tests for the _default_cache_dir static method."""

    def test_default_cache_dir_default_home(self):
        """Test the _default_cache_dir default case."""
        # Ensure override is unset
        os.environ.pop("MENDER_HELPER_CACHE_DIR", None)
        # Ensure cache home is unset
        os.environ.pop("XDG_CACHE_HOME", None)
        result = LifecycleHelperContext._default_cache_dir()
        assert isinstance(result, Path)
        assert (
            result == Path("~/.cache").expanduser() / "mender-docker-lifecycle-helper"
        )

    def test_default_cache_dir_xdg_cache_home(self, tmp_path):
        """Test the _default_cache_dir case when xdg cache home var is set."""
        # Ensure override is unset
        os.environ.pop("MENDER_HELPER_CACHE_DIR", None)
        os.environ["XDG_CACHE_HOME"] = str(tmp_path)
        result = LifecycleHelperContext._default_cache_dir()
        assert isinstance(result, Path)
        assert result == tmp_path / "mender-docker-lifecycle-helper"

    def test_default_cache_dir_name_override(self, tmp_path):
        """Test the _default_cache_dir case when cache dir name is overridden."""
        # Ensure override is unset
        os.environ.pop("MENDER_HELPER_CACHE_DIR", None)
        os.environ["XDG_CACHE_HOME"] = str(tmp_path)
        result = LifecycleHelperContext._default_cache_dir(
            default_cache_dir_name="this-cache"
        )
        assert isinstance(result, Path)
        assert result == tmp_path / "this-cache"


class TestPrepLogger:
    """Tests for the _prep_logger static method."""

    def test_prep_logger_debug_level(self):
        """Test that _prep_logger uses DEBUG level if specified."""
        result = LifecycleHelperContext._prep_logger("DEBUG")
        assert isinstance(result, logging.Logger)
        assert result.level == logging.DEBUG

    def test_prep_logger_info_level(self):
        """Test that _prep_logger uses INFO level if specified."""
        result = LifecycleHelperContext._prep_logger("INFO")
        assert isinstance(result, logging.Logger)
        assert result.level == logging.INFO


class TestRepoRootDir:
    """Tests for the _repo_root_dir static method."""

    def test_repo_root_dir_from_root(self, tmp_path):
        """Test that _repo_root_dir finds the git root directory."""
        # Create a temp git repo structure
        repo_root = tmp_path / "repo"
        (repo_root / ".git").mkdir(parents=True)

        result = LifecycleHelperContext._repo_root_dir(repo_root)
        assert result == repo_root

    def test_repo_root_dir_from_subdir(self, tmp_path):
        """Test that _repo_root_dir finds the git root directory."""
        # Create a temp git repo structure
        repo_root = tmp_path / "repo"
        (repo_root / ".git").mkdir(parents=True)
        subdir = repo_root / "sub"

        result = LifecycleHelperContext._repo_root_dir(subdir)
        assert result == repo_root

    def test_repo_root_dir_no_git(self):
        """Test that _repo_root_dir raises FileNotFoundError when not in a git repo."""
        with pytest.raises(FileNotFoundError):
            LifecycleHelperContext._repo_root_dir(Path("/tmp"))


class TestRepoVersion:
    """Tests for the _repo_version static method."""

    def test_repo_version_reads_file(self, tmp_path):
        """Test that _repo_version reads VERSION file from repo root."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        version_file = repo_root / "VERSION"
        version_file.write_text("1.2.3\n\n\n")

        result = LifecycleHelperContext._repo_version(repo_root)
        assert result == "1.2.3"

    def test_repo_version_no_newline(self, tmp_path):
        """Test that _repo_version reads VERSION file with no newline."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        version_file = repo_root / "VERSION"
        version_file.write_text("1.4.0")

        result = LifecycleHelperContext._repo_version(repo_root)
        assert result == "1.4.0"

    def test_repo_version_missing_file(self, tmp_path):
        """Test that _repo_version raises FileNotFoundError when VERSION file is missing."""
        with pytest.raises(FileNotFoundError):
            LifecycleHelperContext._repo_version(tmp_path)


class TestPrepCacheDir:
    """Tests for the _prep_cache_dir instance method."""

    def test_prep_cache_dir_creates_directory(self, tmp_path):
        """Test that _prep_cache_dir creates the cache directory."""
        cache_dir = tmp_path / "cache"
        LifecycleHelperContext._prep_cache_dir(
            SimpleNamespace(logger=logging.Logger("test_logger")), cache_dir
        )
        assert cache_dir.exists()
        assert cache_dir.is_dir()

    def test_prep_cache_dir_existing_directory(self, tmp_path):
        """Test that _prep_cache_dir handles existing directory."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        LifecycleHelperContext._prep_cache_dir(
            SimpleNamespace(logger=logging.Logger("test_logger")), cache_dir
        )
        assert cache_dir.exists()
        assert cache_dir.is_dir()


class TestTempRepoAtVersion:
    """Tests for the _temp_repo_at_version instance method."""

    def test_temp_repo_at_version_current(self, tmp_path):
        """Test that _temp_repo_at_version creates a temporary repo at the current version."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir(parents=True)
        temp_dir = tmp_path / "cache" / "temp"
        temp_dir.mkdir(parents=True)
        repo = git.Repo.init(repo_root)
        (repo_root / "VERSION").write_text("1.0.0\n")
        repo.index.add("VERSION")
        repo.index.commit("Initial commit")
        repo.create_tag("1.0.0")

        result = LifecycleHelperContext._temp_repo_at_version(
            SimpleNamespace(
                logger=logging.Logger("test_logger"),
                repo_root_dir=repo_root,
                temp_dir=temp_dir,
            ),
            "1.0.0",
        )

        assert isinstance(result, Path)
        assert result.is_relative_to(temp_dir)
        assert (result / "VERSION").read_text() == "1.0.0\n"
        assert git.Repo(result).head.commit.message == "Initial commit"

    def test_temp_repo_at_version_previous(self, tmp_path):
        """Test that _temp_repo_at_version creates a temporary repo at a previous version."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir(parents=True)
        temp_dir = tmp_path / "cache" / "temp"
        temp_dir.mkdir(parents=True)
        repo = git.Repo.init(repo_root)
        (repo_root / "VERSION").write_text("1.0.0\n")
        repo.index.add("VERSION")
        repo.index.commit("Initial commit")
        repo.create_tag("1.0.0")
        (repo_root / "test").write_text("test")
        repo.index.add("test")
        repo.index.commit("Another commit")

        result = LifecycleHelperContext._temp_repo_at_version(
            SimpleNamespace(
                logger=logging.Logger("test_logger"),
                repo_root_dir=repo_root,
                temp_dir=temp_dir,
            ),
            "1.0.0",
        )

        assert isinstance(result, Path)
        assert result.is_relative_to(temp_dir)
        assert (result / "VERSION").read_text() == "1.0.0\n"
        assert not (result / "test").exists()
        assert git.Repo(result).head.commit.message == "Initial commit"

    def test_temp_repo_at_version_non_existent(self, tmp_path):
        """Test that _temp_repo_at_version fails to create a temporary repo at version that does not exist."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir(parents=True)
        temp_dir = tmp_path / "cache" / "temp"
        temp_dir.mkdir(parents=True)
        repo = git.Repo.init(repo_root)
        (repo_root / "VERSION").write_text("1.0.0\n")
        repo.index.add("VERSION")
        repo.index.commit("Initial commit")
        repo.create_tag("1.0.0")

        with pytest.raises(git.exc.GitCommandError):
            LifecycleHelperContext._temp_repo_at_version(
                SimpleNamespace(
                    logger=logging.Logger("test_logger"),
                    repo_root_dir=repo_root,
                    temp_dir=temp_dir,
                ),
                "1.1.0",
            )


class TestArtifactServicesMetadataFromCompose:
    """Tests for the _artifact_services_metadata_from_compose instance method."""

    def test_parse_compose_file(self, tmp_path):
        """Test that _artifact_services_metadata_from_compose parses compose file."""
        # Create a git repo so _repo_root_dir can find it
        compose_content = {
            "services": {
                "serviceA": {
                    "image": "busybox:1.37.0-musl@sha256:19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138"
                },
                "serviceB": {"image": "redis:7"},
            }
        }
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(yaml.dump(compose_content))

        result = LifecycleHelperContext._artifact_services_metadata_from_compose(
            SimpleNamespace(
                logger=logging.Logger("test_logger"),
                _compose_content_from_file=lambda file: compose_content,
            ),
            compose_file,
        )

        assert result["serviceA"] == {
            "image": {
                "ref": "busybox:1.37.0-musl@sha256:19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138",
                "hash": "19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138",
            }
        }
        assert result["serviceB"]["image"]["ref"] == "redis:7"


class TestPrepPreviousArtifactMetadata:
    """Tests for the _prep_previous_artifact_metadata instance method."""

    def test_prep_previous_artifact_metadata_from_cache(self, tmp_path):
        """Test that previous artifact metadata is loaded from cache."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cache_artifact_metadata_file = cache_dir / "previous-artifact.json"
        cache_artifact_metadata_file.write_text(
            json.dumps(
                {
                    "version": "1.0.0",
                    "services": {
                        "serviceA": {
                            "image": {"ref": "nginx:1.19", "hash": "abcdef0123456789"}
                        }
                    },
                }
            )
        )

        result = LifecycleHelperContext._prep_previous_artifact_metadata(
            SimpleNamespace(
                cache=True,
                cache_artifact_metadata_file=cache_artifact_metadata_file,
                logger=logging.Logger("test_logger"),
            ),
            None,
        )

        assert result.version == "1.0.0"
        assert result.services == {
            "serviceA": {"image": {"ref": "nginx:1.19", "hash": "abcdef0123456789"}}
        }

    def test_prep_previous_artifact_metadata_from_previous_version(self, tmp_path):
        """Test that previous artifact metadata is loaded from a specified previous version."""
        manifest_file = tmp_path / "manifest"
        prev_dir = tmp_path / "1.0.0"
        prev_dir.mkdir()
        previous_version_manifest_file = prev_dir / "manifest"
        previous_version_manifest_file.touch()

        result = LifecycleHelperContext._prep_previous_artifact_metadata(
            SimpleNamespace(
                cache=False,
                logger=logging.Logger("test_logger"),
                manifest_file=manifest_file,
                repo_root_dir=tmp_path,
                # Don't actually extract the file contents, just feed back the filename
                _artifact_services_metadata_from_compose=lambda file: file,
                # Don't actually get a repo at the version, rather provide just the test path
                # containing the manifest
                _temp_repo_at_version=lambda version: tmp_path / version,
            ),
            "1.0.0",
        )

        assert result.version == "1.0.0"
        # Ensure that the correct file would be read, if not for the above mocking
        assert result.services == previous_version_manifest_file

    def test_prep_previous_artifact_metadata_release(self, tmp_path):
        """Test that previous artifact metadata is loaded from the correct version in the case of a release."""
        manifest_file = tmp_path / "manifest"
        prev_dir = tmp_path / "0.0.0+abcd1234"
        prev_dir.mkdir(parents=True)
        previous_version_manifest_file = prev_dir / "manifest"
        previous_version_manifest_file.touch()

        result = LifecycleHelperContext._prep_previous_artifact_metadata(
            SimpleNamespace(
                cache=False,
                logger=logging.Logger("test_logger"),
                manifest_file=manifest_file,
                release=True,
                repo_root_dir=tmp_path,
                # Don't actually extract the file contents, just feed back the filename
                _artifact_services_metadata_from_compose=lambda file: file,
                _repo=SimpleNamespace(
                    head=SimpleNamespace(
                        commit=SimpleNamespace(
                            parents=[SimpleNamespace(hexsha="abcd1234")]
                        )
                    )
                ),
                _repo_version=lambda path: f"0.0.0+{path.name}",
                # Don't actually get a repo at the version, rather provide just the test path
                # containing the manifest
                _temp_repo_at_version=lambda version: tmp_path / version,
            ),
            None,
        )

        assert result.version == "0.0.0+abcd1234"
        # Ensure that the correct file would be read, if not for the above mocking
        assert result.services == previous_version_manifest_file

    def test_prep_previous_artifact_metadata_from_repo_version(self, tmp_path):
        """Test that previous artifact metadata is loaded from the version currently indicated in the repo."""
        manifest_file = tmp_path / "manifest"
        prev_dir = tmp_path / "2.0.0"
        prev_dir.mkdir()
        previous_version_manifest_file = prev_dir / "manifest"
        previous_version_manifest_file.touch()

        result = LifecycleHelperContext._prep_previous_artifact_metadata(
            SimpleNamespace(
                cache=False,
                logger=logging.Logger("test_logger"),
                manifest_file=manifest_file,
                release=False,
                repo_root_dir=tmp_path,
                repo_version="2.0.0",
                # Don't actually extract the file contents, just feed back the filename
                _artifact_services_metadata_from_compose=lambda file: file,
                # Don't actually get a repo at the version, rather provide just the test path
                # containing the manifest
                _temp_repo_at_version=lambda version: tmp_path / version,
            ),
            None,
        )

        assert result.version == "2.0.0"
        # Ensure that the correct file would be read, if not for the above mocking
        assert result.services == previous_version_manifest_file

    def test_prep_previous_artifact_metadata_file_not_existent(self, tmp_path):
        """Test that previous artifact metadata raises an execption if the manifest file cannot be found."""
        manifest_file = tmp_path / "manifest"
        prev_dir = tmp_path / "0.0.0"
        prev_dir.mkdir()
        # No touch of manifest file

        with pytest.raises(FileNotFoundError):
            LifecycleHelperContext._prep_previous_artifact_metadata(
                SimpleNamespace(
                    cache=False,
                    logger=logging.Logger("test_logger"),
                    manifest_file=manifest_file,
                    release=False,
                    repo_root_dir=tmp_path,
                    repo_version="0.0.0",
                    # Don't actually extract the file contents, just feed back the filename
                    _artifact_services_metadata_from_compose=lambda file: file,
                    # Don't actually get a repo at the version, rather provide just the test path
                    # containing the manifest
                    _temp_repo_at_version=lambda version: tmp_path / version,
                ),
                None,
            )


class TestMatchOrFindHash:
    """Tests for the match_or_find_hash instance method."""

    def test_match_or_find_hash_existing(self):
        """Test that match_or_find_hash returns existing hash when available."""
        result = LifecycleHelperContext.match_or_find_hash(
            SimpleNamespace(
                logger=logging.Logger("test_logger"),
                previous_artifact_metadata=SimpleNamespace(
                    services={
                        "server": {"image": {"ref": "nginx:latest", "hash": "abc123"}}
                    }
                ),
            ),
            "server",
            "nginx:latest",
        )

        assert result == "abc123"

    def test_match_or_find_hash_not_found(self, monkeypatch: pytest.MonkeyPatch):
        """Test that match_or_find_hash returns None when hash not found."""
        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.context.get_image_hash",
            lambda ref, logger: ref,
        )

        result = LifecycleHelperContext.match_or_find_hash(
            SimpleNamespace(
                logger=logging.Logger("test_logger"),
                previous_artifact_metadata=SimpleNamespace(
                    services={
                        "server": {"image": {"ref": "nginx:latest", "hash": "abc123"}}
                    }
                ),
            ),
            "other",
            "my-image:1234",
        )

        # Expect ref as result, per the above get_image_hash mock
        assert result == "my-image:1234"


class TestComposeContentFromFile:
    """Tests for the _compose_content_from_file method.

    The function calls `docker compose --file <compose_file> config` to resolve
    compose-spec directives and return normalized YAML output.

    Per compose-spec:
    - include: Merges multiple compose files into one
    - extends: Resolves service inheritance (parent config merged into child)
    - env_file: Loads environment variables from file into environment section

    See: https://github.com/compose-spec/compose-spec/blob/main/spec.md
    """

    def _create_context(self, tmp_path):
        """Helper to create a context with required attributes for testing."""
        context = LifecycleHelperContext.__new__(LifecycleHelperContext)
        context.logger = logging.Logger("test_logger")
        context.temp_dir = tmp_path
        return context

    def test_compose_content_simple(self, tmp_path):
        """Test _compose_content_from_file with a simple compose file."""
        compose_file = tmp_path / "docker-compose.yaml"
        compose_file.write_text(
            yaml.dump({"services": {"web": {"image": "nginx:latest"}}})
        )

        context = self._create_context(tmp_path)

        result = LifecycleHelperContext._compose_content_from_file(
            context, compose_file
        )
        expected = {
            "name": tmp_path.name,
            "networks": {
                "default": {
                    "name": f"{tmp_path.name}_default",
                }
            },
            "services": {
                "web": {"image": "nginx:latest", "networks": {"default": None}}
            },
        }
        assert result == expected

    def test_compose_content_with_include_resolved(self, tmp_path):
        """Test _compose_content_from_file with include directive resolved.

        Per compose-spec, include merges multiple files.
        See: https://github.com/compose-spec/compose-spec/blob/main/spec.md#include
        """
        compose_file = tmp_path / "docker-compose.yaml"
        compose_file.write_text(
            yaml.dump(
                {
                    "include": ["./shared.yaml"],
                    "services": {"web": {"image": "nginx:latest"}},
                }
            )
        )

        # Create the included file
        (tmp_path / "shared.yaml").write_text(
            yaml.dump({"services": {"db": {"image": "postgres:15"}}})
        )

        context = self._create_context(tmp_path)

        result = LifecycleHelperContext._compose_content_from_file(
            context, compose_file
        )
        expected = {
            "name": tmp_path.name,
            "networks": {
                "default": {
                    "name": f"{tmp_path.name}_default",
                }
            },
            "services": {
                "db": {"image": "postgres:15", "networks": {"default": None}},
                "web": {"image": "nginx:latest", "networks": {"default": None}},
            },
        }
        assert result == expected

    def test_compose_content_with_extends_resolved(self, tmp_path):
        """Test _compose_content_from_file with extends directive resolved.

        Per compose-spec, extends allows service inheritance.
        See: https://github.com/compose-spec/compose-spec/blob/main/spec.md#extends
        """
        compose_file = tmp_path / "docker-compose.yaml"
        compose_file.write_text(
            yaml.dump(
                {
                    "services": {
                        "base": {"image": "nginx:latest", "ports": ["8080:80"]},
                        "web-dev": {
                            "extends": {"service": "base"},
                            "environment": {"DEBUG": "true"},
                        },
                    }
                }
            )
        )

        context = self._create_context(tmp_path)

        result = LifecycleHelperContext._compose_content_from_file(
            context, compose_file
        )
        expected = {
            "name": tmp_path.name,
            "networks": {
                "default": {
                    "name": f"{tmp_path.name}_default",
                }
            },
            "services": {
                "base": {
                    "image": "nginx:latest",
                    "networks": {"default": None},
                    "ports": [
                        {
                            "mode": "ingress",
                            "protocol": "tcp",
                            "published": "8080",
                            "target": 80,
                        }
                    ],
                },
                "web-dev": {
                    "environment": {"DEBUG": "true"},
                    "image": "nginx:latest",
                    "networks": {"default": None},
                    "ports": [
                        {
                            "mode": "ingress",
                            "protocol": "tcp",
                            "published": "8080",
                            "target": 80,
                        }
                    ],
                },
            },
        }
        assert result == expected

    def test_compose_content_with_env_file_resolved(self, tmp_path):
        """Test _compose_content_from_file with env_file directive resolved.

        Per compose-spec, env_file loads environment variables from a file.
        See: https://github.com/compose-spec/compose-spec/blob/main/spec.md#env_file
        """
        compose_file = tmp_path / "docker-compose.yaml"
        compose_file.write_text(
            yaml.dump(
                {"services": {"app": {"image": "myapp:latest", "env_file": ".env"}}}
            )
        )

        # Create the env file
        (tmp_path / ".env").write_text(
            "DATABASE_URL=postgres://localhost/db\nDEBUG=false\nPORT=8080\n"
        )

        context = self._create_context(tmp_path)

        result = LifecycleHelperContext._compose_content_from_file(
            context, compose_file
        )
        expected = {
            "name": tmp_path.name,
            "networks": {
                "default": {
                    "name": f"{tmp_path.name}_default",
                }
            },
            "services": {
                "app": {
                    "environment": {
                        "DATABASE_URL": "postgres://localhost/db",
                        "DEBUG": "false",
                        "PORT": "8080",
                    },
                    "image": "myapp:latest",
                    "networks": {"default": None},
                }
            },
        }
        assert result == expected

    def test_compose_content_with_multiple_directives(self, tmp_path):
        """Test _compose_content_from_file with multiple directives resolved together."""
        compose_file = tmp_path / "docker-compose.yaml"
        compose_file.write_text(
            yaml.dump(
                {
                    "include": ["./base.yaml"],
                    "services": {
                        "frontend": {"build": {"context": "."}},
                        "backend-base": {
                            "image": "python:latest",
                            "environment": {"DB": "postgres"},
                        },
                        "backend": {"extends": {"service": "backend-base"}},
                    },
                }
            )
        )

        # Included file provides nginx service
        (tmp_path / "base.yaml").write_text(
            yaml.dump({"services": {"nginx": {"image": "nginx:latest"}}})
        )

        context = self._create_context(tmp_path)

        result = LifecycleHelperContext._compose_content_from_file(
            context, compose_file
        )
        expected = {
            "name": tmp_path.name,
            "networks": {
                "default": {
                    "name": f"{tmp_path.name}_default",
                }
            },
            "services": {
                "backend": {
                    "environment": {"DB": "postgres"},
                    "image": "python:latest",
                    "networks": {"default": None},
                },
                "backend-base": {
                    "environment": {"DB": "postgres"},
                    "image": "python:latest",
                    "networks": {"default": None},
                },
                "frontend": {
                    "build": {"context": str(tmp_path), "dockerfile": "Dockerfile"},
                    "networks": {"default": None},
                },
                "nginx": {"image": "nginx:latest", "networks": {"default": None}},
            },
        }
        assert result == expected

    def test_compose_content_propagates_docker_error(self, tmp_path, monkeypatch):
        """Test _compose_content_from_file propagates docker compose config errors."""

        compose_file = tmp_path / "docker-compose.yaml"
        compose_file.write_text(yaml.dump({"services": {"web": {"image": "nginx"}}}))

        context = self._create_context(tmp_path)

        def mock_run(cmd, *args, **kwargs):
            raise subprocess.CalledProcessError(
                1, "docker compose config", stderr="not a valid compose file"
            )

        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.context.subprocess.run", mock_run
        )

        with pytest.raises(subprocess.CalledProcessError):
            LifecycleHelperContext._compose_content_from_file(context, compose_file)
