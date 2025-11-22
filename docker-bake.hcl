// Expected to be used with https://github.com/rcwbr/dockerfile-partials/blob/main/github-cache-bake.hcl
// For example, docker buildx bake -f github-cache-bake.hcl -f uv-project/docker-bake.hcl -f cwd://docker-bake.hcl https://github.com/rcwbr/dockerfile-partials.git#0.12.1

group "default" {
  targets = [
    "uv-project"
  ]
}

target "docker-client" {
  dockerfile = "docker-client/Dockerfile"
  contexts = {
    base_context = "docker-image://python:3.12.4"
    docker_image = "docker-image://docker:27.3.1-cli"
  }

  // Adapted from https://github.com/rcwbr/dockerfile-partials/blob/main/github-cache-bake.hcl
  cache-from = [
    // Always pull cache from main
    "type=registry,ref=${IMAGE_REF}-cache-docker-client:main",
    "type=registry,ref=${IMAGE_REF}-cache-docker-client:${VERSION}"
  ]
  cache-to = [
    "type=registry,rewrite-timestamp=true,mode=max,ref=${IMAGE_REF}-cache-docker-client:${VERSION}"
  ]
  output = []
}

target "deps" {
  dockerfile = "cwd://Dockerfile"
  contexts = {
    base_context = "target:docker-client"
  }

  // Adapted from https://github.com/rcwbr/dockerfile-partials/blob/main/github-cache-bake.hcl
  cache-from = [
    // Always pull cache from main
    "type=registry,ref=${IMAGE_REF}-cache-deps:main",
    "type=registry,ref=${IMAGE_REF}-cache-deps:${VERSION}"
  ]
  cache-to = [
    "type=registry,rewrite-timestamp=true,mode=max,ref=${IMAGE_REF}-cache-deps:${VERSION}"
  ]
  output = []
}

target "uv-project" {
  inherits = ["default"]
  contexts = {
    base_context      = "target:deps"
    dep_docker_client = "target:docker-client"
  }
  args = {
    UV_PACKAGE_NAME = "mender_docker_lifecycle_helper"
  }
}
