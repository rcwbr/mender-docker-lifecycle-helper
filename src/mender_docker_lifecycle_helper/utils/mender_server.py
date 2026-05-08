import time

import requests

from mender_docker_lifecycle_helper.context import LifecycleHelperContext
from mender_docker_lifecycle_helper.artifact import LifecycleHelperArtifact


def call_mender_host_api(
    context: LifecycleHelperContext,
    mender_endpoint: str,
    request_args: dict,
    max_retries: int = 0,
    base_delay: int = 5,
) -> requests.Response:
    """
    Calls the Mender server API at the specified endpoint with provided args.

    :param context: The context of the lifecycle helper execution.
    :param mender_endpoint: The endpoint of the Mender server to call.
    :param request_args: The args to provide to the API call.
    :param max_retries: Maximum number of retries for server errors (5xx). Default 0 (no retries).
    :param base_delay: Base delay in seconds between retries. Default 5.
    :raises HTTPError: If the API call fails.
    :return: The request response object or None.
    """
    if context.mender_pat is None:
        context.logger.error(
            "No MENDER_PAT env var specified, will not upload or deploy to the Mender server."
        )
        return None

    for attempt in range(max_retries + 1):
        r = requests.post(
            f"{context.mender_host}/api/management/v1/{mender_endpoint}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {context.mender_pat}",
            },
            **request_args,
        )
        if r.status_code == 201:
            return r
        context.logger.error(
            f"Request failed for endpoint {mender_endpoint}: status={r.status_code}, text={r.text}, url={r.request.url}, headers={r.request.headers}"
        )
        if r.status_code >= 500 and attempt < max_retries:
            delay = base_delay * (2**attempt)
            context.logger.warning(
                f"Request attempt {attempt + 1} failed with "
                f"status {r.status_code}, retrying in {delay}s"
            )
            time.sleep(delay)
        else:
            r.raise_for_status()


def upload_artifact(
    context: LifecycleHelperContext,
    artifact: LifecycleHelperArtifact,
    max_retries: int = 3,
    base_delay: int = 5,
) -> None:
    """
    Upload the specified artifact file to the Mender server with retry logic.

    :param context: The context of the lifecycle helper execution.
    :param artifact: The object of the artifact to upload to the Mender server.
    :param max_retries: The maximum number of times to retry uploading the artifact in the case of failure.
    :param base_delay: The number of seconds to wait between upload retries.
    :return: None
    """
    with open(artifact.filename, "rb") as file_contents:
        call_mender_host_api(
            context,
            "deployments/artifacts",
            {
                "data": {
                    "size": artifact.filename.stat().st_size,
                    "description": "string",
                },
                "files": {"artifact": file_contents},
            },
            max_retries=max_retries,
            base_delay=base_delay,
        )
    context.logger.info(f"Uploaded artifact {artifact.filename}")
