import tarfile
import tempfile
import os
from pathlib import Path

import pytest

from mender_docker_lifecycle_helper.utils import deep_delta as dd


def _make_image_tar(
    tar_path: Path, layer_name: str, json_parent: str, layer_content: bytes
):
    # Create a temporary dir structure with one layer containing json and layer.tar
    tmp = tar_path.parent / (tar_path.stem + "_src")
    if tmp.exists():
        # clean
        for p in tmp.rglob("*"):
            try:
                if p.is_file():
                    p.unlink()
                else:
                    p.rmdir()
            except Exception:
                pass
    tmp.mkdir(parents=True, exist_ok=True)
    layer_dir = tmp / layer_name
    layer_dir.mkdir(parents=True, exist_ok=True)
    # write json file expected by parse_parent_child
    json_path = layer_dir / "json"
    json_path.write_text(f'{{"parent": "{json_parent}"}}')
    # write layer.tar
    layer_tar = layer_dir / "layer.tar"
    layer_tar.write_bytes(layer_content)

    # pack into tar
    with tarfile.open(str(tar_path), "w") as tar:
        tar.add(tmp, arcname=".")


def test_deep_delta_unpack_error(tmp_path):
    # current is not a tar -> should return 1
    root_dir = tmp_path / "root"
    root_dir.mkdir()
    current = tmp_path / "current_invalid.tar"
    current.write_text("not a tar")
    new = tmp_path / "new.tar"
    _make_image_tar(new, "layer1", "null", b"content")
    output = tmp_path / "out.tar"

    res = dd.deep_delta(root_dir, str(current), str(new), str(output))
    assert res == 1


def test_deep_delta_matching_layers_creates_output(tmp_path):
    # both images have identical layer content -> should succeed and produce output tar
    root_dir = tmp_path / "root2"
    root_dir.mkdir()
    current = tmp_path / "current2.tar"
    new = tmp_path / "new2.tar"
    # same content -> matching branch
    _make_image_tar(current, "layerA", "null", b"samecontent")
    _make_image_tar(new, "layerA", "null", b"samecontent")
    output = tmp_path / "out2.tar"

    # should not raise and should produce an output tar
    ret = dd.deep_delta(root_dir, str(current), str(new), str(output))
    assert ret is None
    assert output.exists()
    assert output.stat().st_size > 0


def test_deep_delta_modified_layers_calls_delta_cmd(tmp_path, monkeypatch):
    # Make current and new with different layer contents so delta_cmd path is used
    root_dir = tmp_path / "root3"
    root_dir.mkdir()
    current = tmp_path / "current3.tar"
    new = tmp_path / "new3.tar"
    _make_image_tar(current, "layerX", "null", b"old")
    _make_image_tar(new, "layerX", "null", b"new")
    output = tmp_path / "out3.tar"

    called = {"args": None}

    def fake_run(args, check=True, **kwargs):
        # the last element is the tmp_file path; create it so shutil.move succeeds
        tmp_file = args[-1]
        with open(tmp_file, "wb") as f:
            f.write(b"vcdiff")
        called["args"] = args

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(dd, "subprocess", dd.subprocess)
    monkeypatch.setattr(dd.subprocess, "run", fake_run)

    # run and assert output exists and contains a .vcdiff entry (repacked)
    ret = dd.deep_delta(root_dir, str(current), str(new), str(output))
    assert ret is None
    assert output.exists()

    # Inspect tar contents to ensure a .vcdiff file was included
    with tarfile.open(str(output), "r") as tf:
        names = tf.getnames()
    assert any(name.endswith(".vcdiff") for name in names)


def test_parse_parent_child_and_calc_hashes(tmp_path):
    # create a directory tree mimicking extracted image dirs
    root = tmp_path / "pc"
    root.mkdir()
    # layer1 is root (parent null)
    l1 = root / "layer1"
    l1.mkdir()
    (l1 / "json").write_text('{"parent": "null"}')
    (l1 / "layer.tar").write_bytes(b"data1")
    # layer2 has parent layer1
    l2 = root / "layer2"
    l2.mkdir()
    (l2 / "json").write_text('{"parent": "layer1"}')
    (l2 / "layer.tar").write_bytes(b"data2")

    # call parse_parent_child and ensure folder structure created
    dd.parse_parent_child(str(root))
    pc_dir = root / "parent-child"
    assert (pc_dir / "layer1" / "layer2").exists()

    # call calc_image_layer_hashes and check hashes map
    id2sum, sum2path = dd.calc_image_layer_hashes(str(root))
    assert "layer1" in id2sum and "layer2" in id2sum
    # sums should map back to a path that ends with layer.tar
    for s, p in sum2path.items():
        assert p.endswith("layer.tar")


def test_deep_delta_new_unpack_error(tmp_path):
    # current valid, new invalid -> returns 1
    root_dir = tmp_path / "root_err"
    root_dir.mkdir()
    current = tmp_path / "current_ok.tar"
    new = tmp_path / "new_invalid.tar"
    _make_image_tar(current, "la", "null", b"ok")
    new.write_text("not a tar")
    output = tmp_path / "out_err.tar"

    res = dd.deep_delta(root_dir, str(current), str(new), str(output))
    assert res == 1
