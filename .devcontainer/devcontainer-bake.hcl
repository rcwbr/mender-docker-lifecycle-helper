variable "devcontainer_layers" {
  default = [
    "docker-client",
    "zsh-base",
    "zsh-thefuck-pyenv",
    "zsh",
    "tmux",
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
