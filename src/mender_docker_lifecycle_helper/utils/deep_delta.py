# Inspired by the deep_delta function from app-gen:
# https://github.com/mendersoftware/app-update-module/blob/29eb51169d1dc32ef1bd013e2414361f67195219/gen/app-gen#L377

import os
import logging
import tarfile
import shutil
import hashlib
import json
import tempfile
import subprocess

logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# Helper function to parse parent-child relationships from image layer metadata
# This reconstructs the layer tree structure for a given unpacked image directory
# It builds a directory tree under 'parent-child' to represent the parent/child relationships


def parse_parent_child(root_dir):
    parent_child_dir = os.path.join(root_dir, "parent-child")
    id2parent = {}
    parent2id = {}
    ids = []

    # Walk through all files, looking for 'json' files that describe layers
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename == "json":
                json_path = os.path.join(dirpath, filename)
                with open(json_path) as f:
                    data = json.load(f)
                parentid = data.get("parent")
                id = os.path.basename(os.path.dirname(json_path))
                id2parent[id] = parentid
                parent2id[parentid] = id
                if parentid != "null":
                    ids.append(id)

    # Find the root layer (parentid == 'null') and create its directory
    parentid = parent2id.get("null")
    if parentid:
        os.makedirs(os.path.join(parent_child_dir, parentid), exist_ok=True)
    i = 0
    # Build the parent-child directory tree
    while ids:
        id = ids[i]
        parentid = id2parent.get(id)
        if not parentid:
            break
        parentid_found = False
        # Find parent dir in the tree
        for dirpath, dirnames, _ in os.walk(parent_child_dir):
            if parentid in dirnames:
                parent_dir = os.path.join(dirpath, parentid)
                os.makedirs(os.path.join(parent_dir, id), exist_ok=True)
                ids.remove(id)
                i = 0
                parentid_found = True
                break
        if not parentid_found:
            i += 1
            if i >= len(ids):
                i = 0


def calc_image_layer_hashes(directory):
    id2sum = {}
    sum2path = {}

    # Find all layer.tar files and calculate their sha256 hashes for the directory image
    for dirpath, _, filenames in os.walk(directory):
        for filename in filenames:
            if filename == "layer.tar":
                layer_path = os.path.join(dirpath, filename)
                with open(layer_path, "rb") as f:
                    sum = hashlib.sha256(f.read()).hexdigest()
                id = os.path.basename(os.path.dirname(layer_path))
                id2sum[id] = sum
                sum2path[sum] = layer_path
    return id2sum, sum2path


# Main function to compute deep delta between two Docker images tar files
# Unpacks both images, reconstructs their layer trees, compares layers by hash
# For matching layers, marks them as unchanged; for differing layers, computes a delta
# Repacks the new image with delta layers and cleans up


def deep_delta(
    root_dir,
    current,
    new,
    output,
    log_level=logging.INFO,
    delta_cmd=["xdelta3", "-f", "-e", "-s"],
):
    logger.setLevel(log_level)

    current_dir = os.path.join(root_dir, "current-image")
    new_dir = os.path.join(root_dir, "new-image")
    id2sum_current = {}
    id2sum_new = {}
    sum2path_new = {}
    sum2path_current = {}

    tmp_file = tempfile.NamedTemporaryFile(delete=False).name

    # Clean and prepare directories
    if os.path.exists(current_dir):
        shutil.rmtree(current_dir)
    if os.path.exists(new_dir):
        shutil.rmtree(new_dir)
    os.makedirs(current_dir, exist_ok=True)
    os.makedirs(new_dir, exist_ok=True)

    # Unpack tar files for current and new images
    try:
        with tarfile.open(current) as tar:
            tar.extractall(current_dir, filter="tar")
    except Exception as e:
        logger.debug(f"ERROR errors unpacking {current}: {e}")
        return 1
    try:
        with tarfile.open(new) as tar:
            tar.extractall(new_dir, filter="tar")
    except Exception as e:
        logger.debug(f"ERROR errors unpacking {new}: {e}")
        return 1

    # Reconstruct parent-child layer trees for both images
    parse_parent_child(current_dir)
    parse_parent_child(new_dir)

    # Find all layer.tar files and calculate their sha256 hashes for current image
    id2sum_current, sum2path_current = calc_image_layer_hashes(current_dir)

    # Find all layer.tar files and calculate their sha256 hashes for new image
    id2sum_new, sum2path_new = calc_image_layer_hashes(new_dir)

    # Compare layers by hash, compute delta for changed layers
    max_level = min(len([p for p in sum2path_current]), len([p for p in sum2path_new]))
    current_ids = list(id2sum_current.keys())
    new_ids = list(id2sum_new.keys())

    for i in range(max_level):
        id_current = current_ids[i] if i < len(current_ids) else None
        id_new = new_ids[i] if i < len(new_ids) else None
        sum_current = id2sum_current.get(id_current)
        sum_new = id2sum_new.get(id_new)
        logger.debug(f"level {i} {id_new} {sum_new} {sum_current}")
        if sum_new == sum_current:
            logger.debug(f"      layers match sum:{sum_new}")
            with open(sum2path_new[sum_new] + ".sha256sum", "w") as f:
                f.write(sum_new)
            os.remove(sum2path_new[sum_new])
        else:
            logger.debug(f"      modified layer")
            logger.debug(
                f"{' '.join(delta_cmd)} {sum2path_current.get(sum_current)} {sum2path_new.get(sum_new)} {tmp_file}"
            )
            subprocess.run(
                [
                    *delta_cmd,
                    sum2path_current.get(sum_current),
                    sum2path_new.get(sum_new),
                    tmp_file,
                ],
                check=True,
            )
            shutil.move(tmp_file, sum2path_new[sum_new] + ".vcdiff")
            with open(sum2path_new[sum_new] + ".current.sha256sum", "w") as f:
                f.write(sum_current)
            with open(sum2path_new[sum_new] + ".new.sha256sum", "w") as f:
                f.write(sum_new)
            os.remove(sum2path_new[sum_new])

    # Clean up and repack the new image with delta layers
    if os.path.exists(output):
        os.remove(output)
    shutil.rmtree(os.path.join(current_dir, "parent-child"), ignore_errors=True)
    shutil.rmtree(os.path.join(new_dir, "parent-child"), ignore_errors=True)
    with tarfile.open(output, "w") as tar:
        tar.add(new_dir, arcname=".")
    shutil.rmtree(current_dir, ignore_errors=True)
    shutil.rmtree(new_dir, ignore_errors=True)
    os.remove(current)
    os.remove(new)
