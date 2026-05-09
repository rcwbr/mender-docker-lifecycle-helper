import shutil

from pathlib import Path

import git


def prepare_repo(tmp_path, repo_name="repo", manifest_name="prebuilt"):
    """Prepare a git repository with VERSION file and manifests for testing.

    Args:
        tmp_path: pytest temporary path
        repo_name: Name of the repository directory
        manifest_name: Name of the manifest subdirectory

    Returns:
        tuple of (repo_dir, repo)
    """

    repo_dir = tmp_path / repo_name
    repo = git.Repo.init(repo_dir)
    (repo_dir / "VERSION").write_text("1.0.0")

    shutil.copytree(
        Path(f"tests/resources/manifests/{manifest_name}"), repo_dir / manifest_name
    )

    repo.index.add(repo_dir / "VERSION")
    repo.index.add(repo_dir / manifest_name)
    repo.index.commit("init")
    repo.create_tag("1.0.0")

    return repo_dir, repo
