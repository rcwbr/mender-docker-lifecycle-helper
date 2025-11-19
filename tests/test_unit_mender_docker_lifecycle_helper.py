import json
from types import SimpleNamespace
from pathlib import Path

import git
import pytest

import mender_docker_lifecycle_helper.mender_docker_lifecycle_helper as mdlh


def test_artifactinfo_roundtrip(tmp_path):
    ai = mdlh.ArtifactInfo(
        version="1.2.3",
        services={"svc": {"ref": "img", "hash": {"local": "sha256:aaa"}}},
    )
    p = tmp_path / "prev.json"
    ai.write_to_file(p)
    assert p.exists()
    loaded = mdlh.ArtifactInfo.read_from_file(p)
    assert loaded.version == "1.2.3"
    assert loaded.services["svc"]["ref"] == "img"


def test_key_value_arg_valid_and_invalid():
    assert mdlh.MenderDockerLifecycleHelper.key_value_arg(["a=1", "b=2"]) == {
        "a": "1",
        "b": "2",
    }
    # invalid entry should cause SystemExit
    with pytest.raises(SystemExit):
        mdlh.MenderDockerLifecycleHelper.key_value_arg(["noequals"])


def test_clean_up_temp_dirs(tmp_path):
    d1 = tmp_path / "d1"
    d2 = tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()
    temp_map = {"a": d1, "b": d2}
    mdlh.MenderDockerLifecycleHelper.clean_up_temp_dirs(temp_map)
    assert not d1.exists()
    assert not d2.exists()
    assert temp_map == {}


def test_cli_arg_strings():
    args = {"flag": True, "single": "val", "mult": ["a", "b"]}
    out = mdlh.MenderDockerLifecycleHelper.cli_arg_strings(args)
    # order is deterministic given dict iteration in python3.7+ for this literal
    assert "--flag" in out
    assert "--single" in out and "val" in out
    assert out.count("--mult") == 2 and "a" in out and "b" in out


def test_get_image_hash_from_version_uses_both_sources(monkeypatch):
    calls = []

    responses = [
        SimpleNamespace(stdout="sha256:LOCALID\n", stderr="", returncode=0),
        SimpleNamespace(stdout='"sha256:REGDIGEST"', stderr="", returncode=0),
    ]

    def fake_run(args, capture_output, text, check):
        calls.append(args)
        return responses.pop(0)

    monkeypatch.setattr(
        mdlh, "subprocess", SimpleNamespace(run=fake_run, CalledProcessError=Exception)
    )

    res = mdlh.MenderDockerLifecycleHelper.get_image_hash_from_version("busybox:latest")
    assert "local" in res and res["local"].startswith("sha256:")
    assert "registry" in res and res["registry"].startswith("sha256:")


def _make_repo_with_manifest(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "application").mkdir()
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    yaml_path.write_text("services:\n  s: \n    image: img:1@sha256:deadbeef\n")
    version_path = repo_dir / "VERSION"
    version_path.write_text("0.0.1")
    repo = git.Repo.init(repo_dir)
    repo.index.add([str(yaml_path)])
    repo.index.commit("add manifest")
    repo.index.add([str(version_path)])
    repo.index.commit("add version")
    return repo


def test_get_repo_root_and_version_and_artifact_info(tmp_path, monkeypatch):
    repo = _make_repo_with_manifest(tmp_path)
    repo_dir = Path(repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    args = SimpleNamespace(
        service_image=None,
        cache_dir=None,
        manifest_file=str(yaml_path),
        manifest_name=None,
        no_cache=False,
        release=False,
        device_type="dt",
        device_group=None,
        platform="linux/amd64",
        previous_version=None,
        mender_host="https://hosted.mender.io",
        delta=True,
        log_level="INFO",
    )
    helper = mdlh.MenderDockerLifecycleHelper(args)
    # get_version_from_repo reads VERSION
    v = helper.get_version_from_repo(repo_dir)
    assert v == "0.0.1"

    # monkeypatch get_image_hash_from_version to avoid docker calls
    monkeypatch.setattr(
        helper, "get_image_hash_from_version", lambda image: {"local": "sha256:abc"}
    )
    info = helper.get_artifact_info_from_repo(repo_dir, "v1")
    assert info.version == "v1"
    assert "s" in info.services


def test_call_mender_artifact_and_host_api(monkeypatch):
    # call_mender_artifact success
    def fake_run_success(args, capture_output, text, check):
        return SimpleNamespace(stdout="ok", stderr="", returncode=0)

    monkeypatch.setattr(
        mdlh,
        "subprocess",
        SimpleNamespace(run=fake_run_success, CalledProcessError=Exception),
    )
    out = mdlh.MenderDockerLifecycleHelper.call_mender_artifact(["--foo", "bar"])
    assert "ok" in out

    # call_mender_host_api success / failure
    class FakeResp:
        def __init__(self, code=201, text="x", request=None):
            self.status_code = code
            self.text = text
            self.request = SimpleNamespace(url="u", headers={})

        def raise_for_status(self):
            raise RuntimeError("bad")

    def fake_post_success(url, headers, **kwargs):
        return FakeResp(201)

    def fake_post_fail(url, headers, **kwargs):
        return FakeResp(500)

    monkeypatch.setattr(mdlh.requests, "post", fake_post_success)
    # prepare helper args for call
    args = SimpleNamespace(
        service_image=None,
        cache_dir=None,
        manifest_file="/dev/null",
        manifest_name=None,
        no_cache=False,
        release=False,
        device_type="dt",
        device_group=None,
        platform="p",
        previous_version=None,
        mender_host="https://hosted.mender.io",
        delta=True,
        log_level="INFO",
    )
    # minimal repo setup for constructor
    # create a repo dir with .git to satisfy get_repo_root_dir
    import tempfile

    td = Path(tempfile.mkdtemp())
    git.Repo.init(td)
    args.manifest_file = str(td / "m")
    helper = mdlh.MenderDockerLifecycleHelper(args)
    # success does not raise
    resp = helper.call_mender_host_api("api/endpoint", {"json": {}})
    assert resp.status_code == 201

    monkeypatch.setattr(mdlh.requests, "post", fake_post_fail)
    with pytest.raises(Exception):
        helper.call_mender_host_api("api/endpoint", {"json": {}})


def test_get_cache_dir_precedence(tmp_path, monkeypatch):
    # If args.cache_dir is set it should be used
    repo = _make_repo_with_manifest(tmp_path)
    repo_dir = Path(repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    args = SimpleNamespace(
        service_image=None,
        cache_dir=str(tmp_path / "mycache"),
        manifest_file=str(yaml_path),
        manifest_name=None,
        no_cache=False,
        release=False,
        device_type="dt",
        device_group=None,
        platform="p",
        previous_version=None,
        mender_host="https://hosted.mender.io",
        delta=True,
        log_level="INFO",
    )
    helper = mdlh.MenderDockerLifecycleHelper(args)
    assert str(helper.cache_dir).endswith("mycache")


def test_get_temp_repo_at_version_uses_clone_and_caches(monkeypatch, tmp_path):
    repo = _make_repo_with_manifest(tmp_path)
    repo_dir = Path(repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    args = SimpleNamespace(
        service_image=None,
        cache_dir=None,
        manifest_file=str(yaml_path),
        manifest_name=None,
        no_cache=False,
        release=False,
        device_type="dt",
        device_group=None,
        platform="p",
        previous_version=None,
        mender_host="https://hosted.mender.io",
        delta=True,
        log_level="INFO",
    )
    helper = mdlh.MenderDockerLifecycleHelper(args)

    # fake clone_from to record parameters and simulate a repo object
    recorded = {}

    def fake_clone_from(src, dst):
        recorded["src"] = src
        recorded["dst"] = dst

        class FakeRepo:
            def __init__(self):
                self.git = SimpleNamespace(checkout=lambda v: None)

        return FakeRepo()

    monkeypatch.setattr(mdlh.git.Repo, "clone_from", staticmethod(fake_clone_from))
    temp1 = helper.get_temp_repo_at_version("deadbeef")
    temp2 = helper.get_temp_repo_at_version("deadbeef")
    assert temp1 == temp2
    assert recorded["src"] == helper.repo_root_dir


def test_save_image_error_raises_systemexit(monkeypatch):
    # simulate subprocess.run raising CalledProcessError
    def fake_run(*a, **k):
        raise mdlh.subprocess.CalledProcessError(1, "cmd", output=b"", stderr=b"err")

    monkeypatch.setattr(mdlh, "subprocess", mdlh.subprocess)
    monkeypatch.setattr(mdlh.subprocess, "run", fake_run)
    # call save_image and expect SystemExit
    with pytest.raises(SystemExit):
        mdlh.MenderDockerLifecycleHelper.save_image("imgid", "/tmp/out.tar")


def test_prep_image_with_delta_creates_files(tmp_path, monkeypatch):
    repo = _make_repo_with_manifest(tmp_path)
    repo_dir = Path(repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    args = SimpleNamespace(
        service_image=None,
        cache_dir=None,
        manifest_file=str(yaml_path),
        manifest_name=None,
        no_cache=False,
        release=False,
        device_type="dt",
        device_group=None,
        platform="p",
        previous_version=None,
        mender_host="https://hosted.mender.io",
        delta=True,
        log_level="INFO",
    )
    helper = mdlh.MenderDockerLifecycleHelper(args)
    helper.prep_artifact_temp_dir = tmp_path / "prep"
    helper.prep_artifact_temp_dir.mkdir()

    # fake pull_image to return image dicts
    def fake_pull(image):
        return {
            "ref": image.get("ref", "img"),
            "hash": {"local": image.get("hash_local", "sha256:aaa")},
        }

    monkeypatch.setattr(helper, "pull_image", fake_pull)

    # fake save_image to create files
    def fake_save(image_id, file):
        p = Path(file)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("data")

    monkeypatch.setattr(
        mdlh.MenderDockerLifecycleHelper, "save_image", staticmethod(fake_save)
    )

    # fake deep_delta to create image.img
    def fake_deep_delta(image_dir, new_tar, current_tar, out_img, log_level):
        Path(out_img).write_text("img")

    monkeypatch.setattr(mdlh, "deep_delta", fake_deep_delta)

    image = {"ref": "i:1", "hash": {"local": "sha256:newid"}}
    delta_image = {"ref": "i:0", "hash": {"local": "sha256:oldid"}}
    image_id = helper.prep_image(image, delta_image=delta_image)
    # check that image dir exists with expected files
    image_dir = helper.prep_artifact_temp_dir / "images" / image_id
    assert (image_dir / "image-new.tar").exists()
    assert (image_dir / "image-current.tar").exists()
    assert (image_dir / "image.img").exists()
    assert (image_dir / "deep_delta").exists()


def test_get_repo_root_dir_no_git_raises():
    # path with no .git in ancestors should cause SystemExit
    p = Path("/tmp/some/random/path/that/does/not/exist")
    with pytest.raises(SystemExit):
        mdlh.MenderDockerLifecycleHelper.get_repo_root_dir(None, p)


def test_get_image_hash_from_version_both_methods_fail(monkeypatch):
    # both docker inspect and buildx fail -> SystemExit
    def fake_run_fail(*a, **k):
        raise mdlh.subprocess.CalledProcessError(1, "cmd", output=b"", stderr=b"err")

    monkeypatch.setattr(mdlh, "subprocess", mdlh.subprocess)
    monkeypatch.setattr(mdlh.subprocess, "run", fake_run_fail)
    with pytest.raises(SystemExit):
        mdlh.MenderDockerLifecycleHelper.get_image_hash_from_version("busybox:fail")


def test_get_artifact_info_from_compose_no_services(tmp_path):
    # create a repo so helper can initialize (it requires a repo root)
    repo = _make_repo_with_manifest(tmp_path)
    repo_dir = Path(repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    args = SimpleNamespace(
        service_image=None,
        cache_dir=None,
        manifest_file=str(yaml_path),
        manifest_name=None,
        no_cache=False,
        release=False,
        device_type="dt",
        device_group=None,
        platform="p",
        previous_version=None,
        mender_host="https://hosted.mender.io",
        delta=True,
        log_level="INFO",
    )
    helper = mdlh.MenderDockerLifecycleHelper(args)
    with pytest.raises(SystemExit):
        helper.get_artifact_info_from_compose({}, "v")


def test_get_previous_artifact_info_reads_cache(tmp_path):
    repo = _make_repo_with_manifest(tmp_path)
    repo_dir = Path(repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    args = SimpleNamespace(
        service_image=None,
        cache_dir=str(tmp_path / ".cache"),
        manifest_file=str(yaml_path),
        manifest_name="test-manifest",
        no_cache=False,
        release=False,
        device_type="dt",
        device_group=None,
        platform="p",
        previous_version=None,
        mender_host="https://hosted.mender.io",
        delta=True,
        log_level="INFO",
    )
    helper = mdlh.MenderDockerLifecycleHelper(args)
    # create cache file
    cache_file = helper.previous_artifact_info_file
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    ai = mdlh.ArtifactInfo(version="pv", services={})
    ai.write_to_file(cache_file)
    got = helper.get_previous_artifact_info()
    assert got.version == "pv"


def test_get_current_version_release_and_nonrelease(tmp_path, monkeypatch):
    repo = _make_repo_with_manifest(tmp_path)
    repo_dir = Path(repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    # release true
    args = SimpleNamespace(
        service_image=None,
        cache_dir=None,
        manifest_file=str(yaml_path),
        manifest_name=None,
        no_cache=False,
        release=True,
        device_type="dt",
        device_group=None,
        platform="p",
        previous_version=None,
        mender_host="https://hosted.mender.io",
        delta=True,
        log_level="INFO",
    )
    helper = mdlh.MenderDockerLifecycleHelper(args)
    rv = helper.get_current_version()
    assert rv == helper.get_version_from_repo(helper.repo_root_dir)

    # non-release
    args.release = False
    helper = mdlh.MenderDockerLifecycleHelper(args)
    helper.previous_version = "pv"
    head = SimpleNamespace(commit=SimpleNamespace(hexsha="abcdef1234567890"))
    # Repo.head is a read-only property, replace the repo object with a simple stub
    helper.repo = SimpleNamespace(head=head)
    monkeypatch.setattr(mdlh.uuid, "uuid4", lambda: "fixeduuid")
    cur = helper.get_current_version()
    assert "pv+abcdef1+fixeduuid" in cur


def test_pull_image_calls_pull_when_not_local(monkeypatch, tmp_path):
    repo = _make_repo_with_manifest(tmp_path)
    yaml_path = Path(repo.working_dir) / "application" / "docker-compose.yaml"
    args = SimpleNamespace(
        service_image=None,
        cache_dir=None,
        manifest_file=str(yaml_path),
        manifest_name=None,
        no_cache=False,
        release=False,
        device_type="dt",
        device_group=None,
        platform="p",
        previous_version=None,
        mender_host="https://hosted.mender.io",
        delta=True,
        log_level="INFO",
    )
    helper = mdlh.MenderDockerLifecycleHelper(args)
    image = {"ref": "img:1", "hash": {}}

    def fake_run(args, capture_output, text, check):
        return SimpleNamespace(stdout="pulled", stderr="", returncode=0)

    monkeypatch.setattr(
        mdlh,
        "subprocess",
        SimpleNamespace(
            run=fake_run, CalledProcessError=mdlh.subprocess.CalledProcessError
        ),
    )
    monkeypatch.setattr(
        helper, "get_image_hash_from_version", lambda ref: {"local": "sha256:abc"}
    )
    got = helper.pull_image(image)
    assert got["hash"]["local"].startswith("sha256:")


def test_save_image_success(monkeypatch, tmp_path):
    def fake_run(args, capture_output, text, check):
        return SimpleNamespace(stdout="ok", stderr="", returncode=0)

    monkeypatch.setattr(
        mdlh, "subprocess", SimpleNamespace(run=fake_run, CalledProcessError=Exception)
    )
    # should not raise
    mdlh.MenderDockerLifecycleHelper.save_image("imgid", tmp_path / "out.tar")


def test_create_artifact_file_service_override_applied(tmp_path, monkeypatch):
    repo = _make_repo_with_manifest(tmp_path)
    repo_dir = Path(repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    args = SimpleNamespace(
        service_image=["s=override:1"],
        cache_dir=None,
        manifest_file=str(yaml_path),
        manifest_name=None,
        no_cache=False,
        release=False,
        device_type="dt",
        device_group=None,
        platform="p",
        previous_version=None,
        mender_host="https://hosted.mender.io",
        delta=True,
        log_level="INFO",
    )
    helper = mdlh.MenderDockerLifecycleHelper(args)
    helper.version = "vtest"
    helper.manifest_name = "appname"
    helper.prep_artifact_temp_dir = tmp_path / "prep"
    helper.prep_artifact_temp_dir.mkdir()
    # create manifests dir and manifest file to be modified
    (repo_dir / "application" / "man").write_text("services:\n  s:\n    image: old:1\n")
    helper.manifest_file = Path("application") / "man"
    # stub call_mender_artifact
    monkeypatch.setattr(
        mdlh.MenderDockerLifecycleHelper,
        "call_mender_artifact",
        staticmethod(lambda a: "ok"),
    )
    helper.create_artifact_file(["imgid"])
    # read modified manifest in prep dir
    modified = (
        helper.prep_artifact_temp_dir / "manifests" / helper.manifest_file.name
    ).read_text()
    assert "override:1" in modified


def test_deploy_artifact_skips_when_no_device_group(monkeypatch, tmp_path):
    repo = _make_repo_with_manifest(tmp_path)
    yaml_path = Path(repo.working_dir) / "application" / "docker-compose.yaml"
    args = SimpleNamespace(
        service_image=None,
        cache_dir=None,
        manifest_file=str(yaml_path),
        manifest_name=None,
        no_cache=False,
        release=False,
        device_type="dt",
        device_group=None,
        platform="p",
        previous_version=None,
        mender_host="https://hosted.mender.io",
        delta=True,
        log_level="INFO",
    )
    helper = mdlh.MenderDockerLifecycleHelper(args)
    helper.artifact_name = "a"
    called = []

    def fake_post(url, headers, **kwargs):
        called.append(url)
        return SimpleNamespace(status_code=201)

    monkeypatch.setattr(mdlh.requests, "post", fake_post)
    helper.deploy_artifact()
    # no deployments/group call expected
    assert not any("deployments/deployments/group" in c for c in called)


def test_prep_delta_images_calls_prep_image(monkeypatch, tmp_path):
    repo = _make_repo_with_manifest(tmp_path)
    repo_dir = Path(repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    args = SimpleNamespace(
        service_image=None,
        cache_dir=None,
        manifest_file=str(yaml_path),
        manifest_name=None,
        no_cache=False,
        release=False,
        device_type="dt",
        device_group=None,
        platform="p",
        previous_version=None,
        mender_host="https://hosted.mender.io",
        delta=True,
        log_level="INFO",
    )
    helper = mdlh.MenderDockerLifecycleHelper(args)
    prev = mdlh.ArtifactInfo(
        version="v0", services={"s": {"ref": "i:0", "hash": {"local": "sha256:old"}}}
    )
    cur = mdlh.ArtifactInfo(
        version="v1", services={"s": {"ref": "i:1", "hash": {"local": "sha256:new"}}}
    )
    monkeypatch.setattr(helper, "prep_image", lambda img, delta_image=None: "imgid")
    ids = helper.prep_delta_images(prev, cur)
    assert "imgid" in ids


def test_create_artifact_file_invokes_mender_artifact(tmp_path, monkeypatch):
    repo = _make_repo_with_manifest(tmp_path)
    repo_dir = Path(repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    args = SimpleNamespace(
        service_image=None,
        cache_dir=None,
        manifest_file=str(yaml_path),
        manifest_name=None,
        no_cache=False,
        release=False,
        device_type="dt",
        device_group=None,
        platform="p",
        previous_version=None,
        mender_host="https://hosted.mender.io",
        delta=True,
        log_level="INFO",
    )
    helper = mdlh.MenderDockerLifecycleHelper(args)
    helper.version = "vtest"
    helper.manifest_name = "appname"
    helper.prep_artifact_temp_dir = tmp_path / "prep"
    helper.prep_artifact_temp_dir.mkdir()
    # create a manifests dir to be copied
    (repo_dir / "application" / "other").mkdir()
    # call_mender_artifact should be invoked with proper args
    called = {}

    def fake_call(args_list):
        called["args"] = args_list
        return "ok"

    monkeypatch.setattr(
        mdlh.MenderDockerLifecycleHelper,
        "call_mender_artifact",
        staticmethod(fake_call),
    )
    # ensure manifest parent exists so copytree works
    helper.create_artifact_file(["imgid"])
    assert "args" in called


def test_upload_and_deploy_artifact_calls_requests(monkeypatch, tmp_path):
    repo = _make_repo_with_manifest(tmp_path)
    repo_dir = Path(repo.working_dir)
    yaml_path = repo_dir / "application" / "docker-compose.yaml"
    args = SimpleNamespace(
        service_image=None,
        cache_dir=None,
        manifest_file=str(yaml_path),
        manifest_name=None,
        no_cache=False,
        release=False,
        device_type="dt",
        device_group="grp",
        platform="p",
        previous_version=None,
        mender_host="https://hosted.mender.io",
        delta=True,
        log_level="INFO",
    )
    helper = mdlh.MenderDockerLifecycleHelper(args)
    # create dummy artifact file
    helper.artifact_file = repo_dir / "a.mender"
    helper.artifact_file.write_text("x")

    posts = []

    def fake_post(url, headers, **kwargs):
        posts.append((url, headers, kwargs))
        resp = SimpleNamespace()
        resp.status_code = 201
        return resp

    monkeypatch.setattr(mdlh.requests, "post", fake_post)
    helper.upload_artifact()
    helper.deploy_artifact()
    assert any("artifacts" in p[0] for p in posts)
    assert any("deployments/group" in p[0] for p in posts)


def test_get_cache_dir_uses_env_vars(tmp_path, monkeypatch):
    # When MENDER_HELPER_CACHE_DIR env var is set it should be used
    repo = _make_repo_with_manifest(tmp_path)
    yaml_path = Path(repo.working_dir) / "application" / "docker-compose.yaml"
    # set env var and ensure helper picks it up during init
    env_cache = tmp_path / "envcache"
    monkeypatch.setenv(mdlh.MENDER_HELPER_CACHE_DIR_ENV_KEY, str(env_cache))
    args = SimpleNamespace(
        service_image=None,
        cache_dir=None,
        manifest_file=str(yaml_path),
        manifest_name=None,
        no_cache=False,
        release=False,
        device_type="dt",
        device_group=None,
        platform="p",
        previous_version=None,
        mender_host="https://hosted.mender.io",
        delta=True,
        log_level="INFO",
    )
    helper = mdlh.MenderDockerLifecycleHelper(args)
    assert helper.cache_dir == Path(env_cache)


def test_get_temp_repo_at_version_clone_failure(monkeypatch, tmp_path):
    repo = _make_repo_with_manifest(tmp_path)
    yaml_path = Path(repo.working_dir) / "application" / "docker-compose.yaml"
    args = SimpleNamespace(
        service_image=None,
        cache_dir=None,
        manifest_file=str(yaml_path),
        manifest_name=None,
        no_cache=False,
        release=False,
        device_type="dt",
        device_group=None,
        platform="p",
        previous_version=None,
        mender_host="https://hosted.mender.io",
        delta=True,
        log_level="INFO",
    )
    helper = mdlh.MenderDockerLifecycleHelper(args)

    def fake_clone_from(src, dst):
        raise Exception("clone failed")

    monkeypatch.setattr(mdlh.git.Repo, "clone_from", staticmethod(fake_clone_from))
    with pytest.raises(Exception):
        helper.get_temp_repo_at_version("deadbeef")


def test_call_mender_artifact_failure_raises(monkeypatch):
    # simulate subprocess.run raising CalledProcessError inside call_mender_artifact
    def fake_run(args, capture_output, text, check):
        raise mdlh.subprocess.CalledProcessError(1, args, output=b"", stderr=b"err")

    monkeypatch.setattr(mdlh, "subprocess", mdlh.subprocess)
    monkeypatch.setattr(mdlh.subprocess, "run", fake_run)
    with pytest.raises(SystemExit):
        mdlh.MenderDockerLifecycleHelper.call_mender_artifact(["write", "module-image"])
