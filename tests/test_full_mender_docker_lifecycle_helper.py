import os
import shutil
import sys
from tempfile import mkdtemp as real_mkdtemp
from pathlib import Path
from types import SimpleNamespace

import git
import pytest

import mender_docker_lifecycle_helper.mender_docker_lifecycle_helper as mdlh


class MenderRequestAsserts:
    def __init__(self, upload_request, deploy_request):
        self.upload_request = upload_request
        self.deploy_request = deploy_request
        self.upload_count = 0
        self.deploy_count = 0

    def assert_mender_request_equal(self, url, headers, **request_args):
        if url.endswith("deployments/artifacts"):
            assert url == self.upload_request["url"]
            assert headers == self.upload_request["headers"]
            assert (
                request_args["files"]["artifact"].name
                == self.upload_request["request_args"]["files"]["artifact"]
            )
            del request_args["files"]["artifact"]
            del self.upload_request["request_args"]["files"]["artifact"]
            assert request_args == self.upload_request["request_args"]
            self.upload_count += 1
        elif "deployments/deployments/group" in url:
            assert url == self.deploy_request["url"]
            assert headers == self.deploy_request["headers"]
            assert request_args == self.deploy_request["request_args"]
            self.deploy_count += 1
        response = SimpleNamespace()
        response.status_code = 201
        return response

    def assert_count_match(self, expected_upload_count, expected_deploy_count):
        assert (
            self.upload_count == expected_upload_count
        ), f"Upload count {self.upload_count} != expected {expected_upload_count}"
        assert (
            self.deploy_count == expected_deploy_count
        ), f"Deploy count {self.deploy_count} != expected {expected_deploy_count}"


def func_assert_list_equal(list):
    def assert_list_equal(_, compare_list):
        assert compare_list == list, f"Lists differ: {compare_list} != {list}"

    return assert_list_equal


@pytest.fixture
def app_repo(tmp_path_factory):
    repo_dir = tmp_path_factory.mktemp("repo")
    (repo_dir / "application").mkdir()
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    with open(yaml_path, "w") as f:
        f.write(
            # sha256-style tags only for test immutability
            "services:\n"
            "  svc1:\n"
            "    image: busybox:1.36.1-musl@sha256:faeb06dde6421d3dd02f59896bf47a64820f995458a42388277382010d208e1e\n"
            "  svc2:\n"
            "    image: busybox:1.36.1-glibc@sha256:8fe66e6f43e59abc326f16fa4491708d15591c42a17486235e55fabf18ba5cb6\n"
        )
    version_file = repo_dir / "VERSION"
    with open(version_file, "w") as f:
        f.write("0.1.0")
    # Initialize git repo
    repo = git.Repo.init(repo_dir)
    repo.index.add([yaml_path])
    repo.index.commit("add manifest yaml")
    repo.index.add([version_file])
    repo.index.commit("add version file")
    # Tag the commit
    repo.create_tag("0.1.0")
    return repo


FAKE_UUID = "42aec757-b640-4e96-a86c-da0141661599"


def mdlh_execute_with_mocks(
    repo_dir,
    args,
    expect_call_mender_artifact,
    expect_metadata_contents,
    expect_image_dirs_contents,
    expect_upload_request,
    expect_deploy_request,
):
    # Clear any Mender auth from the environment
    if "MENDER_PAT" in os.environ:
        del os.environ["MENDER_PAT"]
    temp_artifacts_dir = repo_dir / "temp_artifacts_space"
    temp_artifacts_dir.mkdir()

    def temp_artifacts_mkdtemp(dir):
        if dir is not None and str(dir).endswith("temp_artifacts"):
            return temp_artifacts_dir
        else:
            return real_mkdtemp(dir=dir)

    with pytest.MonkeyPatch.context() as m:
        m.setattr(mdlh.uuid, "uuid4", lambda: FAKE_UUID)
        m.setattr(mdlh.tempfile, "mkdtemp", temp_artifacts_mkdtemp)
        m.setattr(
            mdlh.MenderDockerLifecycleHelper,
            "call_mender_artifact",
            func_assert_list_equal(expect_call_mender_artifact),
        )
        request_asserts = MenderRequestAsserts(
            expect_upload_request, expect_deploy_request
        )
        m.setattr(mdlh.requests, "post", request_asserts.assert_mender_request_equal)
        sys.argv = ["prog"] + args
        mdlh.main()
        with open(temp_artifacts_dir / "metadata.json", "r") as f:
            assert f.read() == expect_metadata_contents
        for image_id, expected_files in expect_image_dirs_contents.items():
            for expected_file, expected_file_content in expected_files.items():
                with open(
                    temp_artifacts_dir / "images" / image_id / expected_file, "r"
                ) as f:
                    assert f.read() == expected_file_content

        request_asserts.assert_count_match(
            expect_upload_request["count"], expect_deploy_request["count"]
        )
    shutil.rmtree(temp_artifacts_dir)


def test_basic(app_repo):
    repo_dir = Path(app_repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    os.environ["MENDER_HELPER_CACHE_DIR"] = str(repo_dir / ".cache")
    with open(yaml_path, "w") as f:
        f.write(
            "services:\n"
            "  svc1:\n"
            "    image: busybox:1.37.0-musl@sha256:ef13e7482851632be3faf5bd1d28d4727c0810901d564b35416f309975a12a30\n"
            "  svc2:\n"
            "    image: busybox:1.37.0-glibc@sha256:3bf024f5b91b256d55fcecaa910a7f671bdd2b6bb5bb22ac6b774cc4678f2093\n"
        )
    (
        repo_dir
        / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
    ).write_text("dummy mender artifact content")
    mdlh_execute_with_mocks(
        repo_dir,
        [
            "--device-type",
            "test",
            "--device-group",
            "test-group",
            "--platform",
            "linux/amd64",
            str(yaml_path),
        ],
        [
            "write",
            "module-image",
            "--type",
            "app",
            "--device-type",
            "test",
            "--output-path",
            str(
                repo_dir
                / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
            ),
            "--artifact-name",
            f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
            "--meta-data",
            str(repo_dir / "temp_artifacts_space" / "metadata.json"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "manifests.tar.gz"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "images.tar.gz"),
            "--software-name",
            f"{repo_dir.name}-application",
            "--software-version",
            f"0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
            "--depends",
            f"rootfs-image.{repo_dir.name}-application.version:0.1.0",
        ],
        (
            "{"
            f'"application_name": "{repo_dir.name}-application", '
            '"orchestrator": "docker-compose", '
            '"platform": "linux/amd64", '
            f'"version": "0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}", '
            '"images": ['
            '"08ef35a1c3f050afbbd64194ffd1b8d5878659f5491567f26d1c814513ae9649", '
            '"4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010"'
            "]"
            "}"
        ),
        {
            "08ef35a1c3f050afbbd64194ffd1b8d5878659f5491567f26d1c814513ae9649": {
                "sums-new.txt": "08ef35a1c3f050afbbd64194ffd1b8d5878659f5491567f26d1c814513ae9649",
                "url-new.txt": "busybox:1.37.0-glibc@sha256:3bf024f5b91b256d55fcecaa910a7f671bdd2b6bb5bb22ac6b774cc4678f2093",
                "sums-current.txt": "f0fd628b15e8cf167f7d467e031c1a15193d7db6e75c61b4fe9965d88e461a4a",
                "url-current.txt": "busybox:1.36.1-glibc@sha256:8fe66e6f43e59abc326f16fa4491708d15591c42a17486235e55fabf18ba5cb6",
            },
            "4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010": {
                "sums-new.txt": "4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010",
                "url-new.txt": "busybox:1.37.0-musl@sha256:ef13e7482851632be3faf5bd1d28d4727c0810901d564b35416f309975a12a30",
                "sums-current.txt": "b8e94f8a8ece76012619069971f9b63bde0d8b94188dafc4108aa761acb30e5a",
                "url-current.txt": "busybox:1.36.1-musl@sha256:faeb06dde6421d3dd02f59896bf47a64820f995458a42388277382010d208e1e",
            },
        },
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/artifacts",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "files": {
                    "artifact": str(
                        repo_dir
                        / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
                    )
                },
                "data": {"size": 29, "description": "string"},
            },
            "count": 1,
        },
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/deployments/group/test-group",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "json": {
                    "name": f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}-test-group",
                    "artifact_name": f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
                }
            },
            "count": 1,
        },
    )


def test_subsequent_executions(app_repo):
    repo_dir = Path(app_repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    os.environ["MENDER_HELPER_CACHE_DIR"] = str(repo_dir / ".cache")
    with open(yaml_path, "w") as f:
        f.write(
            "services:\n"
            "  svc1:\n"
            "    image: busybox:1.37.0-musl@sha256:ef13e7482851632be3faf5bd1d28d4727c0810901d564b35416f309975a12a30\n"
            "  svc2:\n"
            "    image: busybox:1.36.1-glibc@sha256:8fe66e6f43e59abc326f16fa4491708d15591c42a17486235e55fabf18ba5cb6\n"
        )
    app_repo.index.add([yaml_path])
    app_repo.index.commit("update musl image")
    (
        repo_dir
        / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
    ).write_text("dummy mender artifact content")
    mdlh_execute_with_mocks(
        repo_dir,
        [
            "--device-type",
            "test",
            "--device-group",
            "test-group",
            "--platform",
            "linux/amd64",
            str(yaml_path),
        ],
        [
            "write",
            "module-image",
            "--type",
            "app",
            "--device-type",
            "test",
            "--output-path",
            str(
                repo_dir
                / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
            ),
            "--artifact-name",
            f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
            "--meta-data",
            str(repo_dir / "temp_artifacts_space" / "metadata.json"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "manifests.tar.gz"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "images.tar.gz"),
            "--software-name",
            f"{repo_dir.name}-application",
            "--software-version",
            f"0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
            "--depends",
            f"rootfs-image.{repo_dir.name}-application.version:0.1.0",
        ],
        (
            "{"
            f'"application_name": "{repo_dir.name}-application", '
            '"orchestrator": "docker-compose", '
            '"platform": "linux/amd64", '
            f'"version": "0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}", '
            '"images": ['
            '"4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010", '
            '"f0fd628b15e8cf167f7d467e031c1a15193d7db6e75c61b4fe9965d88e461a4a"'
            "]"
            "}"
        ),
        {
            "f0fd628b15e8cf167f7d467e031c1a15193d7db6e75c61b4fe9965d88e461a4a": {
                "sums-new.txt": "f0fd628b15e8cf167f7d467e031c1a15193d7db6e75c61b4fe9965d88e461a4a",
                "url-new.txt": "busybox:1.36.1-glibc@sha256:8fe66e6f43e59abc326f16fa4491708d15591c42a17486235e55fabf18ba5cb6",
                "sums-current.txt": "f0fd628b15e8cf167f7d467e031c1a15193d7db6e75c61b4fe9965d88e461a4a",
                "url-current.txt": "busybox:1.36.1-glibc@sha256:8fe66e6f43e59abc326f16fa4491708d15591c42a17486235e55fabf18ba5cb6",
            },
            "4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010": {
                "sums-new.txt": "4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010",
                "url-new.txt": "busybox:1.37.0-musl@sha256:ef13e7482851632be3faf5bd1d28d4727c0810901d564b35416f309975a12a30",
                "sums-current.txt": "b8e94f8a8ece76012619069971f9b63bde0d8b94188dafc4108aa761acb30e5a",
                "url-current.txt": "busybox:1.36.1-musl@sha256:faeb06dde6421d3dd02f59896bf47a64820f995458a42388277382010d208e1e",
            },
        },
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/artifacts",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "files": {
                    "artifact": str(
                        repo_dir
                        / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
                    )
                },
                "data": {"size": 29, "description": "string"},
            },
            "count": 1,
        },
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/deployments/group/test-group",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "json": {
                    "name": f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}-test-group",
                    "artifact_name": f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
                }
            },
            "count": 1,
        },
    )
    prev_commit_hash = app_repo.git.rev_parse("HEAD", short=7)
    with open(yaml_path, "w") as f:
        f.write(
            "services:\n"
            "  svc1:\n"
            "    image: busybox:1.37.0-musl@sha256:ef13e7482851632be3faf5bd1d28d4727c0810901d564b35416f309975a12a30\n"
            "  svc2:\n"
            "    image: busybox:1.37.0-glibc@sha256:3bf024f5b91b256d55fcecaa910a7f671bdd2b6bb5bb22ac6b774cc4678f2093\n"
        )
    app_repo.index.add([yaml_path])
    app_repo.index.commit("update glib image")
    (
        repo_dir
        / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
    ).write_text("dummy mender artifact content")
    mdlh_execute_with_mocks(
        repo_dir,
        [
            "--device-type",
            "test",
            "--device-group",
            "test-group",
            "--platform",
            "linux/amd64",
            str(yaml_path),
        ],
        [
            "write",
            "module-image",
            "--type",
            "app",
            "--device-type",
            "test",
            "--output-path",
            str(
                repo_dir
                / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
            ),
            "--artifact-name",
            f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
            "--meta-data",
            str(repo_dir / "temp_artifacts_space" / "metadata.json"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "manifests.tar.gz"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "images.tar.gz"),
            "--software-name",
            f"{repo_dir.name}-application",
            "--software-version",
            f"0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
            "--depends",
            f"rootfs-image.{repo_dir.name}-application.version:0.1.0+{prev_commit_hash}+{FAKE_UUID}",
        ],
        (
            "{"
            f'"application_name": "{repo_dir.name}-application", '
            '"orchestrator": "docker-compose", '
            '"platform": "linux/amd64", '
            f'"version": "0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}", '
            '"images": ['
            '"08ef35a1c3f050afbbd64194ffd1b8d5878659f5491567f26d1c814513ae9649", '
            '"4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010"'
            "]"
            "}"
        ),
        {
            "08ef35a1c3f050afbbd64194ffd1b8d5878659f5491567f26d1c814513ae9649": {
                "sums-new.txt": "08ef35a1c3f050afbbd64194ffd1b8d5878659f5491567f26d1c814513ae9649",
                "url-new.txt": "busybox:1.37.0-glibc@sha256:3bf024f5b91b256d55fcecaa910a7f671bdd2b6bb5bb22ac6b774cc4678f2093",
                "sums-current.txt": "f0fd628b15e8cf167f7d467e031c1a15193d7db6e75c61b4fe9965d88e461a4a",
                "url-current.txt": "busybox:1.36.1-glibc@sha256:8fe66e6f43e59abc326f16fa4491708d15591c42a17486235e55fabf18ba5cb6",
            },
            "4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010": {
                "sums-new.txt": "4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010",
                "url-new.txt": "busybox:1.37.0-musl@sha256:ef13e7482851632be3faf5bd1d28d4727c0810901d564b35416f309975a12a30",
                "sums-current.txt": "4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010",
                "url-current.txt": "busybox:1.37.0-musl@sha256:ef13e7482851632be3faf5bd1d28d4727c0810901d564b35416f309975a12a30",
            },
        },
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/artifacts",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "files": {
                    "artifact": str(
                        repo_dir
                        / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
                    )
                },
                "data": {"size": 29, "description": "string"},
            },
            "count": 1,
        },
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/deployments/group/test-group",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "json": {
                    "name": f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}-test-group",
                    "artifact_name": f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
                }
            },
            "count": 1,
        },
    )


def test_manifest_only(app_repo):
    repo_dir = Path(app_repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    os.environ["MENDER_HELPER_CACHE_DIR"] = str(repo_dir / ".cache")
    with open(yaml_path, "w") as f:
        f.write(
            "services:\n"
            "  svc1:\n"
            "    image: busybox:1.36.1-musl@sha256:faeb06dde6421d3dd02f59896bf47a64820f995458a42388277382010d208e1e\n"
            "    network: host\n"
            "  svc2:\n"
            "    image: busybox:1.36.1-glibc@sha256:8fe66e6f43e59abc326f16fa4491708d15591c42a17486235e55fabf18ba5cb6\n"
        )
    (
        repo_dir
        / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
    ).write_text("dummy mender artifact content")
    mdlh_execute_with_mocks(
        repo_dir,
        [
            "--device-type",
            "test",
            "--device-group",
            "test-group",
            "--platform",
            "linux/amd64",
            str(yaml_path),
        ],
        [
            "write",
            "module-image",
            "--type",
            "app",
            "--device-type",
            "test",
            "--output-path",
            str(
                repo_dir
                / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
            ),
            "--artifact-name",
            f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
            "--meta-data",
            str(repo_dir / "temp_artifacts_space" / "metadata.json"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "manifests.tar.gz"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "images.tar.gz"),
            "--software-name",
            f"{repo_dir.name}-application",
            "--software-version",
            f"0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
            "--depends",
            f"rootfs-image.{repo_dir.name}-application.version:0.1.0",
        ],
        (
            "{"
            f'"application_name": "{repo_dir.name}-application", '
            '"orchestrator": "docker-compose", '
            '"platform": "linux/amd64", '
            f'"version": "0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}", '
            '"images": ['
            '"b8e94f8a8ece76012619069971f9b63bde0d8b94188dafc4108aa761acb30e5a", '
            '"f0fd628b15e8cf167f7d467e031c1a15193d7db6e75c61b4fe9965d88e461a4a"'
            "]"
            "}"
        ),
        {},
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/artifacts",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "files": {
                    "artifact": str(
                        repo_dir
                        / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
                    )
                },
                "data": {"size": 29, "description": "string"},
            },
            "count": 1,
        },
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/deployments/group/test-group",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "json": {
                    "name": f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}-test-group",
                    "artifact_name": f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
                }
            },
            "count": 1,
        },
    )


def test_release(app_repo):
    repo_dir = Path(app_repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    os.environ["MENDER_HELPER_CACHE_DIR"] = str(repo_dir / ".cache")
    with open(yaml_path, "w") as f:
        f.write(
            "services:\n"
            "  svc1:\n"
            "    image: busybox:1.37.0-musl@sha256:ef13e7482851632be3faf5bd1d28d4727c0810901d564b35416f309975a12a30\n"
            "  svc2:\n"
            "    image: busybox:1.37.0-glibc@sha256:3bf024f5b91b256d55fcecaa910a7f671bdd2b6bb5bb22ac6b774cc4678f2093\n"
        )
    app_repo.index.add([yaml_path])
    app_repo.index.commit("update images")
    version_path = repo_dir / "VERSION"
    with open(version_path, "w") as f:
        f.write("0.2.0")
    app_repo.index.add([version_path])
    app_repo.index.commit("release 0.2.0")
    app_repo.create_tag("0.2.0")
    (repo_dir / f"{repo_dir.name}-application-0.2.0.mender").write_text(
        "dummy mender artifact content"
    )
    mdlh_execute_with_mocks(
        repo_dir,
        [
            "--release",
            "--device-type",
            "test",
            "--device-group",
            "test-group",
            "--platform",
            "linux/amd64",
            str(yaml_path),
        ],
        [
            "write",
            "module-image",
            "--type",
            "app",
            "--device-type",
            "test",
            "--output-path",
            str(repo_dir / f"{repo_dir.name}-application-0.2.0.mender"),
            "--artifact-name",
            f"{repo_dir.name}-application-0.2.0",
            "--meta-data",
            str(repo_dir / "temp_artifacts_space" / "metadata.json"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "manifests.tar.gz"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "images.tar.gz"),
            "--software-name",
            f"{repo_dir.name}-application",
            "--software-version",
            f"0.2.0",
            "--depends",
            f"rootfs-image.{repo_dir.name}-application.version:0.1.0",
        ],
        (
            "{"
            f'"application_name": "{repo_dir.name}-application", '
            '"orchestrator": "docker-compose", '
            '"platform": "linux/amd64", '
            f'"version": "0.2.0", '
            '"images": ['
            '"08ef35a1c3f050afbbd64194ffd1b8d5878659f5491567f26d1c814513ae9649", '
            '"4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010"'
            "]"
            "}"
        ),
        {
            "08ef35a1c3f050afbbd64194ffd1b8d5878659f5491567f26d1c814513ae9649": {
                "sums-new.txt": "08ef35a1c3f050afbbd64194ffd1b8d5878659f5491567f26d1c814513ae9649",
                "url-new.txt": "busybox:1.37.0-glibc@sha256:3bf024f5b91b256d55fcecaa910a7f671bdd2b6bb5bb22ac6b774cc4678f2093",
                "sums-current.txt": "f0fd628b15e8cf167f7d467e031c1a15193d7db6e75c61b4fe9965d88e461a4a",
                "url-current.txt": "busybox:1.36.1-glibc@sha256:8fe66e6f43e59abc326f16fa4491708d15591c42a17486235e55fabf18ba5cb6",
            },
            "4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010": {
                "sums-new.txt": "4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010",
                "url-new.txt": "busybox:1.37.0-musl@sha256:ef13e7482851632be3faf5bd1d28d4727c0810901d564b35416f309975a12a30",
                "sums-current.txt": "b8e94f8a8ece76012619069971f9b63bde0d8b94188dafc4108aa761acb30e5a",
                "url-current.txt": "busybox:1.36.1-musl@sha256:faeb06dde6421d3dd02f59896bf47a64820f995458a42388277382010d208e1e",
            },
        },
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/artifacts",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "files": {
                    "artifact": str(
                        repo_dir / f"{repo_dir.name}-application-0.2.0.mender"
                    )
                },
                "data": {"size": 29, "description": "string"},
            },
            "count": 1,
        },
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/deployments/group/test-group",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "json": {
                    "name": f"{repo_dir.name}-application-0.2.0-test-group",
                    "artifact_name": f"{repo_dir.name}-application-0.2.0",
                }
            },
            "count": 1,
        },
    )


def test_no_delta(app_repo):
    repo_dir = Path(app_repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    os.environ["MENDER_HELPER_CACHE_DIR"] = str(repo_dir / ".cache")
    (
        repo_dir
        / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
    ).write_text("dummy mender artifact content")
    mdlh_execute_with_mocks(
        repo_dir,
        [
            "--delta",
            "false",
            "--device-type",
            "test",
            "--device-group",
            "test-group",
            "--platform",
            "linux/amd64",
            str(yaml_path),
        ],
        [
            "write",
            "module-image",
            "--type",
            "app",
            "--device-type",
            "test",
            "--output-path",
            str(
                repo_dir
                / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
            ),
            "--artifact-name",
            f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
            "--meta-data",
            str(repo_dir / "temp_artifacts_space" / "metadata.json"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "manifests.tar.gz"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "images.tar.gz"),
            "--software-name",
            f"{repo_dir.name}-application",
            "--software-version",
            f"0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
        ],
        (
            "{"
            f'"application_name": "{repo_dir.name}-application", '
            '"orchestrator": "docker-compose", '
            '"platform": "linux/amd64", '
            f'"version": "0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}", '
            '"images": ['
            '"b8e94f8a8ece76012619069971f9b63bde0d8b94188dafc4108aa761acb30e5a", '
            '"f0fd628b15e8cf167f7d467e031c1a15193d7db6e75c61b4fe9965d88e461a4a"'
            "]"
            "}"
        ),
        {
            "f0fd628b15e8cf167f7d467e031c1a15193d7db6e75c61b4fe9965d88e461a4a": {
                "sums-new.txt": "f0fd628b15e8cf167f7d467e031c1a15193d7db6e75c61b4fe9965d88e461a4a",
                "url-new.txt": "busybox:1.36.1-glibc@sha256:8fe66e6f43e59abc326f16fa4491708d15591c42a17486235e55fabf18ba5cb6",
                "sums-current.txt": "f0fd628b15e8cf167f7d467e031c1a15193d7db6e75c61b4fe9965d88e461a4a",
                "url-current.txt": "busybox:1.36.1-glibc@sha256:8fe66e6f43e59abc326f16fa4491708d15591c42a17486235e55fabf18ba5cb6",
            },
            "b8e94f8a8ece76012619069971f9b63bde0d8b94188dafc4108aa761acb30e5a": {
                "sums-new.txt": "b8e94f8a8ece76012619069971f9b63bde0d8b94188dafc4108aa761acb30e5a",
                "url-new.txt": "busybox:1.36.1-musl@sha256:faeb06dde6421d3dd02f59896bf47a64820f995458a42388277382010d208e1e",
                "sums-current.txt": "b8e94f8a8ece76012619069971f9b63bde0d8b94188dafc4108aa761acb30e5a",
                "url-current.txt": "busybox:1.36.1-musl@sha256:faeb06dde6421d3dd02f59896bf47a64820f995458a42388277382010d208e1e",
            },
        },
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/artifacts",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "files": {
                    "artifact": str(
                        repo_dir
                        / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
                    )
                },
                "data": {"size": 29, "description": "string"},
            },
            "count": 1,
        },
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/deployments/group/test-group",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "json": {
                    "name": f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}-test-group",
                    "artifact_name": f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
                }
            },
            "count": 1,
        },
    )


def test_service_images(app_repo):
    repo_dir = Path(app_repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    os.environ["MENDER_HELPER_CACHE_DIR"] = str(repo_dir / ".cache")
    (
        repo_dir
        / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
    ).write_text("dummy mender artifact content")
    mdlh_execute_with_mocks(
        repo_dir,
        [
            "--service-image",
            "svc1=busybox:1.37.0-musl@sha256:ef13e7482851632be3faf5bd1d28d4727c0810901d564b35416f309975a12a30",
            "--service-image",
            "svc2=busybox:1.37.0-glibc@sha256:3bf024f5b91b256d55fcecaa910a7f671bdd2b6bb5bb22ac6b774cc4678f2093",
            "--device-type",
            "test",
            "--device-group",
            "test-group",
            "--platform",
            "linux/amd64",
            str(yaml_path),
        ],
        [
            "write",
            "module-image",
            "--type",
            "app",
            "--device-type",
            "test",
            "--output-path",
            str(
                repo_dir
                / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
            ),
            "--artifact-name",
            f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
            "--meta-data",
            str(repo_dir / "temp_artifacts_space" / "metadata.json"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "manifests.tar.gz"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "images.tar.gz"),
            "--software-name",
            f"{repo_dir.name}-application",
            "--software-version",
            f"0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
            "--depends",
            f"rootfs-image.{repo_dir.name}-application.version:0.1.0",
        ],
        (
            "{"
            f'"application_name": "{repo_dir.name}-application", '
            '"orchestrator": "docker-compose", '
            '"platform": "linux/amd64", '
            f'"version": "0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}", '
            '"images": ['
            '"08ef35a1c3f050afbbd64194ffd1b8d5878659f5491567f26d1c814513ae9649", '
            '"4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010"'
            "]"
            "}"
        ),
        {
            "08ef35a1c3f050afbbd64194ffd1b8d5878659f5491567f26d1c814513ae9649": {
                "sums-new.txt": "08ef35a1c3f050afbbd64194ffd1b8d5878659f5491567f26d1c814513ae9649",
                "url-new.txt": "busybox:1.37.0-glibc@sha256:3bf024f5b91b256d55fcecaa910a7f671bdd2b6bb5bb22ac6b774cc4678f2093",
                "sums-current.txt": "f0fd628b15e8cf167f7d467e031c1a15193d7db6e75c61b4fe9965d88e461a4a",
                "url-current.txt": "busybox:1.36.1-glibc@sha256:8fe66e6f43e59abc326f16fa4491708d15591c42a17486235e55fabf18ba5cb6",
            },
            "4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010": {
                "sums-new.txt": "4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010",
                "url-new.txt": "busybox:1.37.0-musl@sha256:ef13e7482851632be3faf5bd1d28d4727c0810901d564b35416f309975a12a30",
                "sums-current.txt": "b8e94f8a8ece76012619069971f9b63bde0d8b94188dafc4108aa761acb30e5a",
                "url-current.txt": "busybox:1.36.1-musl@sha256:faeb06dde6421d3dd02f59896bf47a64820f995458a42388277382010d208e1e",
            },
        },
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/artifacts",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "files": {
                    "artifact": str(
                        repo_dir
                        / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
                    )
                },
                "data": {"size": 29, "description": "string"},
            },
            "count": 1,
        },
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/deployments/group/test-group",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "json": {
                    "name": f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}-test-group",
                    "artifact_name": f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
                }
            },
            "count": 1,
        },
    )


def test_new_service(app_repo):
    repo_dir = Path(app_repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    os.environ["MENDER_HELPER_CACHE_DIR"] = str(repo_dir / ".cache")
    with open(yaml_path, "w") as f:
        f.write(
            "services:\n"
            "  svc1:\n"
            "    image: busybox:1.36.1-musl@sha256:faeb06dde6421d3dd02f59896bf47a64820f995458a42388277382010d208e1e\n"
            "  svc2:\n"
            "    image: busybox:1.36.1-glibc@sha256:8fe66e6f43e59abc326f16fa4491708d15591c42a17486235e55fabf18ba5cb6\n"
            "  svc3:\n"
            "    image: busybox:1.37.0-glibc@sha256:3bf024f5b91b256d55fcecaa910a7f671bdd2b6bb5bb22ac6b774cc4678f2093\n"
        )
    (
        repo_dir
        / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
    ).write_text("dummy mender artifact content")
    mdlh_execute_with_mocks(
        repo_dir,
        [
            "--device-type",
            "test",
            "--device-group",
            "test-group",
            "--platform",
            "linux/amd64",
            str(yaml_path),
        ],
        [
            "write",
            "module-image",
            "--type",
            "app",
            "--device-type",
            "test",
            "--output-path",
            str(
                repo_dir
                / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
            ),
            "--artifact-name",
            f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
            "--meta-data",
            str(repo_dir / "temp_artifacts_space" / "metadata.json"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "manifests.tar.gz"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "images.tar.gz"),
            "--software-name",
            f"{repo_dir.name}-application",
            "--software-version",
            f"0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
            "--depends",
            f"rootfs-image.{repo_dir.name}-application.version:0.1.0",
        ],
        (
            "{"
            f'"application_name": "{repo_dir.name}-application", '
            '"orchestrator": "docker-compose", '
            '"platform": "linux/amd64", '
            f'"version": "0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}", '
            '"images": ['
            '"08ef35a1c3f050afbbd64194ffd1b8d5878659f5491567f26d1c814513ae9649", '
            '"b8e94f8a8ece76012619069971f9b63bde0d8b94188dafc4108aa761acb30e5a", '
            '"f0fd628b15e8cf167f7d467e031c1a15193d7db6e75c61b4fe9965d88e461a4a"'
            "]"
            "}"
        ),
        {
            "f0fd628b15e8cf167f7d467e031c1a15193d7db6e75c61b4fe9965d88e461a4a": {
                "sums-new.txt": "f0fd628b15e8cf167f7d467e031c1a15193d7db6e75c61b4fe9965d88e461a4a",
                "url-new.txt": "busybox:1.36.1-glibc@sha256:8fe66e6f43e59abc326f16fa4491708d15591c42a17486235e55fabf18ba5cb6",
                "sums-current.txt": "f0fd628b15e8cf167f7d467e031c1a15193d7db6e75c61b4fe9965d88e461a4a",
                "url-current.txt": "busybox:1.36.1-glibc@sha256:8fe66e6f43e59abc326f16fa4491708d15591c42a17486235e55fabf18ba5cb6",
            },
            "b8e94f8a8ece76012619069971f9b63bde0d8b94188dafc4108aa761acb30e5a": {
                "sums-new.txt": "b8e94f8a8ece76012619069971f9b63bde0d8b94188dafc4108aa761acb30e5a",
                "url-new.txt": "busybox:1.36.1-musl@sha256:faeb06dde6421d3dd02f59896bf47a64820f995458a42388277382010d208e1e",
                "sums-current.txt": "b8e94f8a8ece76012619069971f9b63bde0d8b94188dafc4108aa761acb30e5a",
                "url-current.txt": "busybox:1.36.1-musl@sha256:faeb06dde6421d3dd02f59896bf47a64820f995458a42388277382010d208e1e",
            },
        },
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/artifacts",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "files": {
                    "artifact": str(
                        repo_dir
                        / f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
                    )
                },
                "data": {"size": 29, "description": "string"},
            },
            "count": 1,
        },
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/deployments/group/test-group",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "json": {
                    "name": f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}-test-group",
                    "artifact_name": f"{repo_dir.name}-application-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
                }
            },
            "count": 1,
        },
    )


def test_new_manifest(app_repo):
    repo_dir = Path(app_repo.working_dir)
    (repo_dir / "new").mkdir()
    yaml_path = repo_dir / "new" / "docker-compose.yaml"
    os.environ["MENDER_HELPER_CACHE_DIR"] = str(repo_dir / ".cache")
    with open(yaml_path, "w") as f:
        f.write(
            "services:\n"
            "  svc1:\n"
            "    image: busybox:1.37.0-musl@sha256:ef13e7482851632be3faf5bd1d28d4727c0810901d564b35416f309975a12a30\n"
            "  svc2:\n"
            "    image: busybox:1.37.0-glibc@sha256:3bf024f5b91b256d55fcecaa910a7f671bdd2b6bb5bb22ac6b774cc4678f2093\n"
        )
    (
        repo_dir
        / f"{repo_dir.name}-new-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
    ).write_text("dummy mender artifact content")
    mdlh_execute_with_mocks(
        repo_dir,
        [
            "--device-type",
            "test",
            "--device-group",
            "test-group",
            "--platform",
            "linux/amd64",
            str(yaml_path),
        ],
        [
            "write",
            "module-image",
            "--type",
            "app",
            "--device-type",
            "test",
            "--output-path",
            str(
                repo_dir
                / f"{repo_dir.name}-new-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
            ),
            "--artifact-name",
            f"{repo_dir.name}-new-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
            "--meta-data",
            str(repo_dir / "temp_artifacts_space" / "metadata.json"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "manifests.tar.gz"),
            "--file",
            str(repo_dir / "temp_artifacts_space" / "images.tar.gz"),
            "--software-name",
            f"{repo_dir.name}-new",
            "--software-version",
            f"0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
        ],
        (
            "{"
            f'"application_name": "{repo_dir.name}-new", '
            '"orchestrator": "docker-compose", '
            '"platform": "linux/amd64", '
            f'"version": "0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}", '
            '"images": ['
            '"08ef35a1c3f050afbbd64194ffd1b8d5878659f5491567f26d1c814513ae9649", '
            '"4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010"'
            "]"
            "}"
        ),
        {
            "08ef35a1c3f050afbbd64194ffd1b8d5878659f5491567f26d1c814513ae9649": {
                "sums-new.txt": "08ef35a1c3f050afbbd64194ffd1b8d5878659f5491567f26d1c814513ae9649",
                "url-new.txt": "busybox:1.37.0-glibc@sha256:3bf024f5b91b256d55fcecaa910a7f671bdd2b6bb5bb22ac6b774cc4678f2093",
                "sums-current.txt": "08ef35a1c3f050afbbd64194ffd1b8d5878659f5491567f26d1c814513ae9649",
                "url-current.txt": "busybox:1.37.0-glibc@sha256:3bf024f5b91b256d55fcecaa910a7f671bdd2b6bb5bb22ac6b774cc4678f2093",
            },
            "4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010": {
                "sums-new.txt": "4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010",
                "url-new.txt": "busybox:1.37.0-musl@sha256:ef13e7482851632be3faf5bd1d28d4727c0810901d564b35416f309975a12a30",
                "sums-current.txt": "4d80875717585106cfbd0e434bdabbb63020a040acd1f61740d7a21fe0dfe010",
                "url-current.txt": "busybox:1.37.0-musl@sha256:ef13e7482851632be3faf5bd1d28d4727c0810901d564b35416f309975a12a30",
            },
        },
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/artifacts",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "files": {
                    "artifact": str(
                        repo_dir
                        / f"{repo_dir.name}-new-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}.mender"
                    )
                },
                "data": {"size": 29, "description": "string"},
            },
            "count": 1,
        },
        {
            "url": "https://hosted.mender.io/api/management/v1/deployments/deployments/group/test-group",
            "headers": {"Accept": "application/json", "Authorization": "Bearer None"},
            "request_args": {
                "json": {
                    "name": f"{repo_dir.name}-new-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}-test-group",
                    "artifact_name": f"{repo_dir.name}-new-0.1.0+{app_repo.git.rev_parse('HEAD', short=7)}+{FAKE_UUID}",
                }
            },
            "count": 1,
        },
    )
