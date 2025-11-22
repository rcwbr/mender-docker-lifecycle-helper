# mender-docker-lifecycle-helper<a name="mender-docker-lifecycle-helper"></a>

[![GitHub Release](https://img.shields.io/github/v/release/rcwbr/mender-docker-lifecycle-helper?logo=semver&style=flat-square)](https://github.com/rcwbr/mender-docker-lifecycle-helper/releases/latest)
[![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/rcwbr/mender-docker-lifecycle-helper/push-workflow.yaml?logo=github&style=flat-square)](https://github.com/rcwbr/mender-docker-lifecycle-helper/actions/workflows/push-workflow.yaml?query=branch%3Amain)
[![codecov](https://codecov.io/github/rcwbr/mender-docker-lifecycle-helper/graph/badge.svg?token=3407T4QQ6C&style=flat-square)](https://codecov.io/github/rcwbr/mender-docker-lifecycle-helper)
[![Dive Docker efficiency](<https://img.shields.io/badge/dynamic/regex?label=dive%20efficiency&logo=docker&logoColor=white&style=flat-square&url=https%3A%2F%2Fgithub.com%2Frcwbr%2Fmender-docker-lifecycle-helper%2Freleases%2Flatest%2Fdownload%2Fdive.json&search=%22efficiencyScore%22%3A%20%5B0-9%5D%2B.(%5B0-9%5D%7B2%7D)(%5B0-9%5D%7B2%7D)&replace=%241.%242%25>)](https://github.com/wagoodman/dive)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white&style=flat-square)](https://github.com/pre-commit/pre-commit)
[![Commitlint](https://img.shields.io/badge/commitlint-enabled-navy?style=flat-square&logo=commitlint&logoColor=white)](https://commitlint.js.org/)
[![Conventional Commits](https://img.shields.io/badge/conventional_commits-compliant-pink?style=flat-square&logo=conventionalcommits&logoColor=white)](https://www.conventionalcommits.org/en/v1.0.0/)
[![Python Black](https://img.shields.io/badge/code_style-black-black?style=flat-square&logo=black&logoColor=white)](https://github.com/psf/black?tab=readme-ov-file)

Management tool for Mender Docker application workloads in local and CI development iteration and
release deployment processes.

<!-- mdformat-toc start --slug=github --maxlevel=6 --minlevel=1 -->

- [mender-docker-lifecycle-helper](#mender-docker-lifecycle-helper)
  - [Overview](#overview)
  - [mender-docker-lifecycle-helper-launcher](#mender-docker-lifecycle-helper-launcher)
    - [mender-docker-lifecycle-helper-launcher usage](#mender-docker-lifecycle-helper-launcher-usage)
  - [mender-docker-lifecycle-helper container](#mender-docker-lifecycle-helper-container)
    - [mender-docker-lifecycle-helper container usage](#mender-docker-lifecycle-helper-container-usage)
  - [mender-docker-lifecycle-helper core](#mender-docker-lifecycle-helper-core)
    - [mender-docker-lifecycle-helper core usage](#mender-docker-lifecycle-helper-core-usage)
      - [mender-docker-lifecycle-helper inputs](#mender-docker-lifecycle-helper-inputs)
      - [mender-docker-lifecycle-helper outputs](#mender-docker-lifecycle-helper-outputs)
      - [mender-docker-lifecycle-helper understanding delta artifacts](#mender-docker-lifecycle-helper-understanding-delta-artifacts)
      - [mender-docker-lifecycle-helper - mender-artifact contexts](#mender-docker-lifecycle-helper---mender-artifact-contexts)
        - [mender-artifact previous version conditions](#mender-artifact-previous-version-conditions)
        - [mender-artifact delta artifact conditions](#mender-artifact-delta-artifact-conditions)
  - [mender-docker-lifecycle-helper GitHub Actions workflow](#mender-docker-lifecycle-helper-github-actions-workflow)
    - [mender-docker-lifecycle-helper GitHub Actions workflow usage](#mender-docker-lifecycle-helper-github-actions-workflow-usage)
      - [mender-docker-lifecycle-helper GitHub Actions workflow inputs](#mender-docker-lifecycle-helper-github-actions-workflow-inputs)
  - [Contributing](#contributing)
    - [devcontainer](#devcontainer)
      - [devcontainer basic usage](#devcontainer-basic-usage)
      - [devcontainer Codespaces usage](#devcontainer-codespaces-usage)
      - [devcontainer pre-commit usage](#devcontainer-pre-commit-usage)
    - [CI/CD](#cicd)
    - [Codecov](#codecov)
    - [Settings](#settings)

<!-- mdformat-toc end -->

## Overview<a name="overview"></a>

![mender-docker-lifecycle-helper demo](https://github.com/user-attachments/assets/c2ac1d30-b873-4c3c-9e53-506c82472268)

The tool is a wrapper around
[Mender's mender-artifact tool](https://github.com/mendersoftware/mender-artifact) plus upload and
deployment of its produced artifact via [Mender server](https://docs.mender.io/server-installation).
It generates artifacts similarly to the
[app-gen tool](https://github.com/mendersoftware/app-update-module/tree/1.1.0/gen), but with
inference of artifact details from the execution context.

<b>In other words, use mender-docker-lifecycle-helper if you are deploying Docker artifacts with
Mender, but don't want to think about the version and dependency metadata to specify every time you
run `docker build` and <i>just want to see what it does live</i>.</b>

The artifact generation extracts the images and their versions from the provided
[Docker compose](https://docs.docker.com/compose/) manifest, and compares these with the same from
the previously-generated artifact to infer whether the images must be included in the artifact or if
a dependency on previous artifact may be used instead. Specifically, each image in the manifest is
included in the artifact only if the image or its version are changed relative to the artifact most
recently uploaded from the environment (in the case of local development iteration) or relative to
the manifest at the previous [semantic version](https://semver.org/spec/v2.0.0.html) release Git tag
of the repo.

The mechanism by which the previous semantic version tag of the repo may be inferred depends on the
versioning model used. It is recommended to use the
[release-it-gh-workflow](https://github.com/rcwbr/release-it-gh-workflow) with the
[release-it-docker file bumper](https://github.com/rcwbr/release-it-docker/tree/main?tab=readme-ov-file#file-bumper-image-usage)
image, as this automates establishment of the required conditions, namely that releases trigger a
bump of the `VERSION` file in the repo root as a commit to `main`, from which the tag is created.
Also expected is that an artifact is published with version specified as the contents of `VERSION`
file, on the commits that bump that version. It is recommended to automate this using the
[reusable workflow from this repo](#mender-docker-lifecycle-helper-github-actions-workflow).

## mender-docker-lifecycle-helper-launcher<a name="mender-docker-lifecycle-helper-launcher"></a>

The mender-docker-lifecycle-helper-launcher script is a convenience wrapper around the
[containerized tool](#mender-docker-lifecycle-helper-container) for the appropriate volume mounts
and run options. It may be used directly from this repo using `wget`:

### mender-docker-lifecycle-helper-launcher usage<a name="mender-docker-lifecycle-helper-launcher-usage"></a>

To run the mender-docker-lifecycle-helper-launcher script, and thus launch a Docker container of the
tool, run:

```bash
wget -qO - https://raw.githubusercontent.com/rcwbr/mender-docker-lifecycle-helper/refs/tags/0.1.1/mender-docker-lifecycle-helper-launcher | bash -s -- --help
```

## mender-docker-lifecycle-helper container<a name="mender-docker-lifecycle-helper-container"></a>

The mender-docker-lifecycle-helper tool is released as a Docker image under this repo. It may be
launched directly as a container, as opposed to likewise via
[the launcher](#mender-docker-lifecycle-helper-launcher), for greater control.

### mender-docker-lifecycle-helper container usage<a name="mender-docker-lifecycle-helper-container-usage"></a>

To launch a mender-docker-lifecycle-helper container, run:

```bash
docker run \
	--rm \
	-it \
	--name mender-docker-lifecycle-helper \
	-e MENDER_PAT \
	-e MENDER_HELPER_CACHE_DIR=/mender-helper-cache \
	-e DOCKER_CONFIG_JSON="$(cat ~/.docker/config.json)" \
	-v mender-helper-cache:/mender-helper-cache \
	-v "$(pwd):$(pwd)" \
	-v /var/run/docker.sock:/var/run/docker.sock \
	ghcr.io/rcwbr/mender-docker-lifecycle-helper:0.1.1 \
	--help
```

## mender-docker-lifecycle-helper core<a name="mender-docker-lifecycle-helper-core"></a>

The core implementation of the mender-docker-lifecycle-helper tool is a Python CLI script that wraps
[Mender's mender-artifact tool](https://github.com/mendersoftware/mender-artifact) and requests to
the [Mender Server Management API](https://docs.mender.io/api/?python#management-apis). For details
of the context provided to mender-artifact, see
[mender-docker-lifecycle-helper - mender-artifact contexts](#mender-docker-lifecycle-helper---mender-artifact-contexts).

### mender-docker-lifecycle-helper core usage<a name="mender-docker-lifecycle-helper-core-usage"></a>

To execute the core script directly, run the following from an environment in which the package is
installed:

```bash
mender-docker-lifecycle-helper --help
```

#### mender-docker-lifecycle-helper inputs<a name="mender-docker-lifecycle-helper-inputs"></a>

The environment variable inputs to the mender-docker-lifecycle-helper tool are as follows:

| Variable                  | Default                                                                                         | Effect                                                                                                                                                                                   |
| ------------------------- | ----------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DOCKER_CONFIG_JSON`      | N/A                                                                                             | Configuration in the `~/.docker/config.json` format, used to configure and authenticate Docker operations (if provided)                                                                  |
| `MENDER_PAT`              | N/A                                                                                             | Mender Server [Personal Access Token](https://docs.mender.io/server-integration/using-the-apis#personal-access-tokens) used to authenticate the artifact upload and deployment creation. |
| `MENDER_HELPER_CACHE_DIR` | `${XDG_CACHE_HOME}/mender-docker-lifecycle-helper` or `~/.cache/mender-docker-lifecycle-helper` | The cache dir to which the metadata for the previously uploaded aritfact is saved. May be overridden by the `--cache-dir` flag.                                                          |

The CLI flag inputs are as follows:

| Flag                 | Default                                                                                                       | Effect                                                                                                                                                                                       |
| -------------------- | ------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--cache-dir`        | `${XDG_CACHE_HOME}/mender-docker-lifecycle-helper` if defined, else `~/.cache/mender-docker-lifecycle-helper` | The cache dir to which the metadata for the previously uploaded aritfact is saved. Overrides the MENDER_HELPER_CACHE_DIR variable.                                                           |
| `--delta`            | `True`                                                                                                        | Generate the artifact as an update artifact, if applicable.                                                                                                                                  |
| `--device-type`      | N/A                                                                                                           | Device type for the artifact (required).                                                                                                                                                     |
| `--device-group`     | `None`                                                                                                        | Device group to which to deploy the artifact, or skip deployment if not defined.                                                                                                             |
| `--log-level`        | `INFO`                                                                                                        | Set logging level. One of "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL".                                                                                                                   |
| `--manifest-name`    | Immediate parent dir of `manifest_file`                                                                       | The application/software name for the artifact.                                                                                                                                              |
| `--mender-host`      | `https://hosted.mender.io`                                                                                    | Mender host URL for artifact upload and deployment.                                                                                                                                          |
| `--no-cache`         | `False`                                                                                                       | Skip reading previous artifact info from cache and always read from the repo at the previous version.                                                                                        |
| `--platform`         | N/A                                                                                                           | Platform with which the artifact is compatible (required, e.g., linux/arm/v7).                                                                                                               |
| `--previous-version` | Read from VERSION file                                                                                        | Repo ref from which to read image names and versions for comparison to the current state.                                                                                                    |
| `--release`          | `False`                                                                                                       | Create the artifact for a release, using the current value of the VERSION file as the artifact version and the value of the VERSION file at the previous commit as the `--previous-version`. |
| `--service-image`    | `None`                                                                                                        | Image name overrides for services in the `manifest_file`, as `[service]=[image]` (can be specified multiple times).                                                                          |
| `[manifest_file]`    | N/A                                                                                                           | (Required) Path to the manifest file for which to generate the artifact (e.g., docker-compose.yaml).                                                                                         |

#### mender-docker-lifecycle-helper outputs<a name="mender-docker-lifecycle-helper-outputs"></a>

The outputs of the tool are inferred from the execution context, with the intention of producing the
optimal artifact for that context. To that purpose, the version and depends for each artifact are
set according to the following conditions:

Constant attributes:

| Attribute     | Value                                                                     |
| ------------- | ------------------------------------------------------------------------- |
| Software name | `<name of the repository dir>-<name of the dir containing manifest_file>` |
| Base version  | `<value of VERSION file>`                                                 |

Conditional attributes:

| Condition        | Depends                                                                  | Software Name     | Version                                        |
| ---------------- | ------------------------------------------------------------------------ | ----------------- | ---------------------------------------------- |
| No cache present | `<software name>.version:<base version>`                                 | `<software name>` | `<base version>+<Git commit short SHA>+<uuid>` |
| Cache is present | `<software name>.version:<version from cache>`                           | `<software name>` | `<base version>+<Git commit short SHA>+<uuid>` |
| `--release` true | `<software name>.version:<value of VERSION file at the previous commit>` | `<software name>` | `<base version>`                               |

In this way, each artifact is generated as a delta relative to the most recent artifact known to
relate to the current context.

#### mender-docker-lifecycle-helper understanding delta artifacts<a name="mender-docker-lifecycle-helper-understanding-delta-artifacts"></a>

When the `--delta` flag is set to false, all images from the manifest are included in full in the
artifact, and the artifact is configured to have no dependency on another artifact.

Otherwise, any image included in the artifact is included as a delta, and conditionally based on
recent artifacts. The hashes of images are read from the local daemon image store, if available, or
from its registry otherwise. If metadata from a previous helper local execution is available, then
an image is included in the artifact if its current hash differs from that in the previous execution
metadata, and the artifact is configured to depend on that created by the previous execution. If
such metadata is not available, then an image is included in the artifact if its current hash
differs from that of the image per the manifest as of the repo version in the `VERSION` file (or the
`--previous-version` arg, if provided).

#### mender-docker-lifecycle-helper - mender-artifact contexts<a name="mender-docker-lifecycle-helper---mender-artifact-contexts"></a>

The context (args and files) provided to the mender-artifact call is computed from several inputs to
the mender-docker-lifecycle-helper invocation. These include the CLI options and environment
variables (see [inputs](#mender-docker-lifecycle-helper-inputs)), as well as local files, including
cache from previous executions of the tool and the repo `VERSION` file. This mapping is the core
logic of the tool.

##### mender-artifact previous version conditions<a name="mender-artifact-previous-version-conditions"></a>

The previous version of the artifact (used for delta artifact generation, see
[mender-artifact delta artifact conditions](#mender-artifact-delta-artifact-conditions)) is
specified differently for certain contexts. The value is as specified in this table, in order of
priority.

| Condition                           | Previous version value                              | Purpose                                                                                                                |
| ----------------------------------- | --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `--previous-version` flag specified | Flag value                                          | Custom delta artifact generation                                                                                       |
| `--release` flag set                | Contents of `VERSION` file at commit `HEAD~1`       | On release commits (i.e. that bump the `VERSION` file contents), generate an artifact relative to the previous release |
| Otherwise                           | Contents of the `VERSION` file in the current state | For non-releases, generate an artifact relative to the most recent release                                             |

##### mender-artifact delta artifact conditions<a name="mender-artifact-delta-artifact-conditions"></a>

When generating a delta artifact, the context provided to `mender-artifact` is described by this
table:

| mender-artifact input                                                                                                  | Cache matches                                                                         | Cache behind                                                                          | No cache                                                                              |
| ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| The `images` field of the file provided to `--meta-data` contains                                                      | ID of `<compose file>.<service 1>.image`, ID of `<compose file>.<service 2>.image`... | ID of `<compose file>.<service 1>.image`, ID of `<compose file>.<service 2>.image`... | ID of `<compose file>.<service 1>.image`, ID of `<compose file>.<service 2>.image`... |
| The image hash in each `<images>/sums-new.txt` belongs to the services defined in this version of the Compose file     | Current repo state                                                                    | Current repo state                                                                    | Current repo state                                                                    |
| The image ref in each `<images>/url-new.txt` belongs to the services defined in this version of the Compose file       | Current repo state                                                                    | Current repo state                                                                    | Current repo state                                                                    |
| The image hash in each `<images>/sums-current.txt` belongs to the services defined in this version of the Compose file | Latest cache state (same as current repo state)                                       | Latest cache state                                                                    | Repo state at [previous version](#mender-artifact-previous-version-conditions)        |
| The image ref in each `<images>/url-current.txt` belongs to the services defined in this version of the Compose file   | Latest cache state (same as current repo state)                                       | Latest cache state                                                                    | Repo state at [previous version](#mender-artifact-previous-version-conditions)        |
| `--depends rootfs-image.<repo name><manifest name>.version:` version ID                                                | Cache previous artifact version ID                                                    | Cache previous artifact version ID                                                    | [Previous version](#mender-artifact-previous-version-conditions)                      |

## mender-docker-lifecycle-helper GitHub Actions workflow<a name="mender-docker-lifecycle-helper-github-actions-workflow"></a>

This repo provides a GitHub Actions reusable workflow to apply the
[containerized tool](#mender-docker-lifecycle-helper-container) via CI. It expects semantic
versioning via a `VERSION` file and Git tags, per the
[release-it-gh-workflow](#https://github.com/rcwbr/release-it-gh-workflow) process, which informs
its use of [the `--release` arg](#mender-docker-lifecycle-helper-inputs).

It generates and (optionally) deploys Mender artifacts of the specified target. The artifact is
generated as `--release=false` and `--delta=true`, unless the ref for the workflow is a tag, in
which case one artifact is generated with `--release=true --delta=true` and one with
`--release=true --delta=false`. In this way, each release introduces a new baseline artifact that
devices may install from scratch, but iterations on branches are fast and lightweight.

### mender-docker-lifecycle-helper GitHub Actions workflow usage<a name="mender-docker-lifecycle-helper-github-actions-workflow-usage"></a>

To upload artifacts and trigger deployments on Mender Server, the workflow must be provided with a
[Mender Personal Access Token](https://docs.mender.io/server-integration/using-the-apis#personal-access-tokens)
as an
[Actions Secret](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).
To create the token, log on to Mender Server (e.g. https://hosted.mender.io/), and navigate to User
\> Settings > My profile > Personal access token management > Generate a token. Copy the generated
token, then navigate to GitHub repository Settings > Security > Secrets and variables > Actions >
New repository secret, and paste as the secret value. The name of the secret must be provided as the
`mender-pat-secret` input to the workflow (see below).

Workflow basic usage:

```yaml
on: push
jobs:
  mender-docker-lifecycle-helper:
    uses: 
      rcwbr/mender-docker-lifecycle-helper/.github/workflows/mender-docker-lifecycle-helper.yaml@0.1.1
    with:
      manifest-file: <path to docker-compose.yaml>
      device-type: <device type>
      platform: <platform>
    secrets:
      mender-pat-secret: ${{ secrets.<Actions secret name> }}
```

With the above configuration, the artifact will be uploaded but not deployed. To also deploy the
artifact, specify a device group to target for the deployment:

```yaml
on: push
jobs:
  mender-docker-lifecycle-helper:
    uses: rcwbr/mender-docker-lifecycle-helper/.github/workflows/mender-docker-lifecycle-helper.yaml@0.1.1
    with:
      device-group: <device group>
      ...
```

Most often, the tool should be integrated into the CI workflow such that it publishes an artifact
including the image just generated by the workflow. To achieve this, the contents of a compose
manifest in source may be overridden using the `service-images` input with a value set to the output
of a previous job. For example, the CI automation for this repo builds an image in a job named
`build-docker-images`, and uses output from that job as the `service-images` override for the
artifact it generates

```yaml
on: push
jobs:
  build-docker-images:
    ...
  mender-docker-lifecycle-helper:
    uses: rcwbr/mender-docker-lifecycle-helper/.github/workflows/mender-docker-lifecycle-helper.yaml@0.1.1
    with:
      ...
      service-images: ${{ format('["mdlh={0}"]', fromJSON(needs.build-docker-images.outputs.mender-docker-lifecycle-helper).uv-project['image.name']) }}
```

To be more precise, it overrides this way _unless the workflow is for a Git tag_ (indicating a
release). In that case, it does not override, as the `.release-it.json` configures automated version
bump in the example compose file, meaning that the ref in that file at any release tag is already
pointing to the same image version just built by the workflow. This configuration looks like this:

```yaml
on: push
jobs:
  build-docker-images:
    ...
  mender-docker-lifecycle-helper:
    uses: rcwbr/mender-docker-lifecycle-helper/.github/workflows/mender-docker-lifecycle-helper.yaml@0.1.1
    with:
      ...
      service-images: ${{ github.ref_type == 'tag' && '' || format('["mdlh={0}"]', fromJSON(needs.build-docker-images.outputs.mender-docker-lifecycle-helper).uv-project['image.name']) }}
```

#### mender-docker-lifecycle-helper GitHub Actions workflow inputs<a name="mender-docker-lifecycle-helper-github-actions-workflow-inputs"></a>

The full inputs for the workflow are as follows:

| Input                       | Required | Default                                                | Type   | Effect                                                                                                                     |
| --------------------------- | -------- | ------------------------------------------------------ | ------ | -------------------------------------------------------------------------------------------------------------------------- |
| `device-group`              | ✗        | `''`                                                   | string | Device group to which to deploy the artifact, or skip deployment if not defined.                                           |
| `device-type`               | ✓        | N/A                                                    | string | Device type for the artifact.                                                                                              |
| `manifest-file`             | ✓        | N/A                                                    | string | Path to the manifest file for which to generate the artifact (e.g., docker-compose.yaml).                                  |
| `mender-host`               | ✗        | `''`                                                   | string | Mender host URL for artifact upload and deployment.                                                                        |
| `platform`                  | ✓        | N/A                                                    | string | Platform with which the artifact is compatible (e.g., linux/arm/v7).                                                       |
| `service-images`            | ✗        | `''`                                                   | string | Image name overrides for services in the manifest_file, as a JSON array \["<service>=<image>", "<service>=<image>", ...\]. |
| `helper-image`              | ✗        | `'ghcr.io/rcwbr/mender-docker-lifecycle-helper:0.1.1'` | string | Docker image to use as mender-docker-lifecycle-helper.                                                                     |
| `secrets.mender-pat-secret` | ✓        | N/A                                                    | secret | Secret that contains the Mender server Personal Access Token to use for artifact upload and deployment.                    |

## Contributing<a name="contributing"></a>

### devcontainer<a name="devcontainer"></a>

This repo contains a [devcontainer definition](https://containers.dev/) in the `.devcontainer`
folder. It leverages the
[devcontainer cache build tool](https://github.com/rcwbr/devcontainer-cache-build) and
[layers defined in the dockerfile-partials repo](https://github.com/rcwbr/dockerfile-partials).

#### devcontainer basic usage<a name="devcontainer-basic-usage"></a>

The [devcontainer cache build tool](https://github.com/rcwbr/devcontainer-cache-build) requires
authentication to the GitHub package registry, as a token stored as
`MENDER_DOCKER_LIFECYCLE_HELPER_DEVCONTAINER_INITIALIZE` (see
[instructions](https://github.com/rcwbr/devcontainer-cache-build/tree/main?tab=readme-ov-file#initialize-script-github-container-registry-setup)).

#### devcontainer Codespaces usage<a name="devcontainer-codespaces-usage"></a>

For use with Codespaces, the `MENDER_DOCKER_LIFECYCLE_HELPER_DEVCONTAINER_INITIALIZE` token (see
[devcontainer basic usage](#devcontainer-basic-usage)) must be stored as a Codespaces secret (see
[instructions](https://github.com/rcwbr/devcontainer-cache-build/tree/main?tab=readme-ov-file#initialize-script-github-container-registry-setup)),
as must values for `USER`, and `UID` (see [useradd Codespaces usage](#useradd-codespaces-usage)).

#### devcontainer pre-commit usage<a name="devcontainer-pre-commit-usage"></a>

By default, the devcontainer configures [pre-commit](https://pre-commit.com/) hooks in the
repository to ensure commits pass basic testing. This includes enforcing
[conventional commit messages](https://www.conventionalcommits.org/en/v1.0.0/) as the standard for
this repository, via [commitlint](https://github.com/conventional-changelog/commitlint).

### CI/CD<a name="cicd"></a>

This repo uses the [release-it-gh-workflow](https://github.com/rcwbr/release-it-gh-workflow), with
the conventional-changelog image defined at any given ref, as its automation. It leverages the
[devcontainer-cache-build workflow](https://github.com/rcwbr/devcontainer-cache-build/blob/main/.github/workflows/devcontainer-cache-build.yaml)
to pre-generate devcontainer images, which are also used for the
[pre-commit workflow](https://github.com/rcwbr/dockerfile-partials/blob/main/.github/workflows/pre-commit.yaml).
Finally, a [Dive Docker image efficiency analysis](https://github.com/wagoodman/dive) job first
builds an image with all partials layers included, then analyses the storage efficiency of the
resulting image.

### Codecov<a name="codecov"></a>

This repo uses [Codecov](https://codecov.io/) for code coverage reporting, as uploaded by the CI/CD
workflow. Access is configured using [Codecov's GitHub App](https://github.com/apps/codecov), and
applying the Repository token value from Codecov as a Repository secret called `CODECOV_TOKEN` in
Settings > Secrets and variables > Actions. Optionally, the coverage may be viewed using
[Codecov's browser extension](https://chromewebstore.google.com/detail/codecov/gedikamndpbemklijjkncpnolildpbgo).

In devcontainers (including Codespaces), the
[Coverage Gutters extension](https://github.com/ryanluker/vscode-coverage-gutters) is enabled. It
may be activated using the `Coverage Gutters: Watch` command, and have inputs populated using the
`Pytest` task.

### Settings<a name="settings"></a>

The GitHub repo settings for this repo are defined as code using the
[Probot settings GitHub App](https://probot.github.io/apps/settings/). Settings values are defined
in the `.github/settings.yml` file. Enabling automation of settings via this file requires
installing the app.

The settings applied are as recommended in the
[release-it-gh-workflow usage](https://github.com/rcwbr/release-it-gh-workflow/blob/4dea4eaf328b60f92dab1b5bd2a63daefa85404b/README.md?plain=1#L58),
including tag and branch protections, GitHub App and environment authentication, and required
checks.
