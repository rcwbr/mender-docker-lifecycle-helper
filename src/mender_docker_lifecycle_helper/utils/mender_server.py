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


def get_deployment_status(
    context: LifecycleHelperContext,
    deployment_id: str,
) -> dict:
    """
    Get the status of a deployment from the Mender server.

    :param context: The context of the lifecycle helper execution.
    :param deployment_id: The ID of the deployment to check.
    :return: The deployment statistics as a dict, or None if the request fails.
    """
    if context.mender_pat is None:
        context.logger.error(
            "No MENDER_PAT env var specified, cannot check deployment status."
        )
        return None

    r = requests.get(
        f"{context.mender_host}/api/management/v1/deployments/deployments/{deployment_id}/statistics",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {context.mender_pat}",
        },
    )
    if r.status_code != 200:
        context.logger.error(
            f"Failed to get deployment status: status={r.status_code}, text={r.text}"
        )
        r.raise_for_status()
    return r.json()


def wait_for_deployment(
    context: LifecycleHelperContext,
    deployment_id: str,
    poll_interval: int = 30,
    timeout: int = 3600,
) -> bool:
    """
    Watch a deployment until completion, success, or timeout.

    Returns True if the deployment succeeded (all devices reported success),
    False otherwise.

    :param context: The context of the lifecycle helper execution.
    :param deployment_id: The ID of the deployment to watch.
    :param poll_interval: Seconds between status checks (default: 30).
    :param timeout: Maximum seconds to wait (default: 3600).
    :return: True if deployment succeeded, False otherwise.
    """
    start_time = time.time()

    while time.time() - start_time < timeout:
        stats = get_deployment_status(context, deployment_id)
        if stats is None:
            context.logger.error("Failed to get deployment status.")
            return False

        # stats contains: success, failure, pending, installing counts
        # and status string ("finished", "inprogress", etc.)
        context.logger.info(
            f"Deployment {deployment_id} status: "
            f"success={stats.get('success', 0)}, "
            f"failure={stats.get('failure', 0)}, "
            f"pending={stats.get('pending', 0)}, "
            f"installing={stats.get('installing', 0)}"
        )

        # Check if deployment is complete (no more pending or installing)
        total_active = stats.get("pending", 0) + stats.get("installing", 0)
        if total_active == 0:
            success_count = stats.get("success", 0)
            failure_count = stats.get("failure", 0)
            if failure_count > 0:
                context.logger.error(
                    f"Deployment {deployment_id} failed: "
                    f"{failure_count} device(s) reported failure."
                )
                return False
            if success_count > 0:
                context.logger.info(
                    f"Deployment {deployment_id} succeeded: "
                    f"{success_count} device(s) reported success."
                )
                return True
            context.logger.debug(f"Deployment {deployment_id} has no results yet.")

        context.logger.debug(f"Waiting {poll_interval}s before next status check...")
        time.sleep(poll_interval)

    context.logger.error(
        f"Deployment {deployment_id} timed out after {timeout} seconds."
    )
    return False
