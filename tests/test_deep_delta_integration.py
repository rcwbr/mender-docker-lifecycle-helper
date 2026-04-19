import hashlib
import tarfile
from pathlib import Path

from mender_docker_lifecycle_helper.utils.image_cache import ImageCache


def test_oci_deep_delta_integration_busybox(tmp_path):
    """Integration test: generate delta between two busybox images and compare to expected layers."""
    # Create temporary cache directory
    cache_dir = tmp_path / "cache"

    # Initialize cache
    cache = ImageCache(cache_dir)

    # Use the two specific busybox image hashes
    from_hash = "3f9777e7e82e8591542f72b965ec7db7e8b3bdb59692976af1bb9b2850b05a4e"
    to_hash = "19b646668802469d968a05342a601e78da4322a414a7c09b1c9ee25165042138"

    # Generate delta file - this will pull images and extract them
    from_image = {
        "ref": "busybox:1.37.0-glibc",
        "hash": from_hash
    }
    to_image = {
        "ref": "busybox:1.37.0-musl",
        "hash": to_hash
    }
    delta_file = cache.delta(from_image, to_image)

    # Verify delta file was created with correct contents
    extract_dir = tmp_path / "delta_extract"
    extract_dir.mkdir()
    with tarfile.open(delta_file, "r:*") as tar:
        tar.extractall(
            path=extract_dir,
            filter="tar",
        )

    expected_dir = Path("tests/resources/deep_delta_integration/test_oci_deep_delta_integration_busybox")
    assert (extract_dir / "index.json").read_text() == (expected_dir / "index.json").read_text()
    assert (extract_dir / "oci-layout").read_text() == (expected_dir / "oci-layout").read_text()

    assert (
        extract_dir / "blobs" / "sha256" / "298efc24641ff8a1a285abdc555a0ce5ab7c42eb085e1be099f824188e069604"
    ).read_text() == (
        expected_dir / "blobs" / "sha256" / "298efc24641ff8a1a285abdc555a0ce5ab7c42eb085e1be099f824188e069604"
    ).read_text()

    assert (
        extract_dir / "blobs" / "sha256" / "0188a8de47ca89b720586f01da7d7f870bdcf5f770b19f740291d716235d3107"
    ).read_text() == (
        expected_dir / "blobs" / "sha256" / "0188a8de47ca89b720586f01da7d7f870bdcf5f770b19f740291d716235d3107"
    ).read_text()

    assert (
        extract_dir / "blobs" / "sha256" / "5bfa213ad2917fd7ef0d56c49b841de3a4788e60b3554ad86d616100e095c1f8.source"
    ).read_text() == (
        expected_dir / "blobs" / "sha256" / "5bfa213ad2917fd7ef0d56c49b841de3a4788e60b3554ad86d616100e095c1f8.source"
    ).read_text()

    # sha256sum compare of 5bfa213ad2917fd7ef0d56c49b841de3a4788e60b3554ad86d616100e095c1f8.vcdiff
    assert hashlib.sha256((
        extract_dir / "blobs" / "sha256" / "5bfa213ad2917fd7ef0d56c49b841de3a4788e60b3554ad86d616100e095c1f8.vcdiff"
    ).read_bytes()).hexdigest() == "b09f1c585797e15f60348f6a312e2e9a1918c639317665c1be48fb8fa9ddd078"
