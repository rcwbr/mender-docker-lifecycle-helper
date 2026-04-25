# Examples

## Deployment to devcontainer

This example use of the mender-docker-lifecyle-helper tool targets deployment of the nginx manifest
in this directory to the devcontainer for this repo (see
[devcontainer in the README for bringup instructions](../README.md#devcontainer)) acting as a Mender
target device.

### Deployment to devcontainer setup

1. Provide a
   [Mender Personal Access Token](https://docs.mender.io/server-integration/using-the-apis#personal-access-tokens)
   to the environment as `MENDER_PAT`. If using Codespaces, this is best achieved by saving it as an
   [account-specific Codespace secret](https://docs.github.com/en/codespaces/managing-your-codespaces/managing-your-account-specific-secrets-for-github-codespaces#adding-a-secret).
1. From within the devcontainer, run `./examples/client-launch`
1. In the [hosted.mender.io web UI](https://hosted.mender.io/), navigate to
   [pending devices](https://hosted.mender.io/ui/devices/pending), and accept the auth request that
   matches your devcontainer.
1. From Device actions, select Add selected device to a group
1. Type "mender-docker-lifecycle-helper-example" as the group name, and select Create group

### Deployment to devcontainer execution

To deploy the example for the first time, run:

```
./examples/deploy-example [example folder] --no-delta
```

### Deployment to devcontainer update

After a successful deployment, run without `--no-delta` flag:

```
./examples/deploy-example [example folder]
```
