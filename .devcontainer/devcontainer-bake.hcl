variable "devcontainer_layers" {
  default = [
    "docker-client",
    "zsh-base",
    "zsh-thefuck-pyenv",
    "zsh",
    "tmux",
    "uv-project",
    "mender-docker-lifecycle-helper",
    "useradd",
    "pre-commit-base",
    "pre-commit-tool-image",
    "pre-commit",
  ]
}

target "docker-client" {
  contexts = {
    base_context = "docker-image://python:3.12.4"
  }
}

target "uv-project" {
  args = {
    UV_PACKAGE_NAME = "mender-docker-lifecycle-helper"
  }
}

target "mender-docker-lifecycle-helper" {
  dockerfile = "cwd://Dockerfile"
}
