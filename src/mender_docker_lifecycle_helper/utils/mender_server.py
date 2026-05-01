import time

import requests

from mender_docker_lifecycle_helper.context import LifecycleHelperContext


def call_mender_host_api(
    context: LifecycleHelperContext,
    mender_endpoint: str,
    request_args: dict,
) -> requests.Response:
    """
    Calls the Mender server API at the specified endpoint with provided args.

    :param context: The context of the lifecycle helper execution.
    :param mender_endpoint: The endpoint of the Mender server to call.
    :param request_args: The args to provide to the API call.
    :raises HTTPError: If the API call fails.
    :return: The request response object or None.
    """
    if context.mender_pat is None:
        context.logger.error(
            "No MENDER_PAT env var specified, will not upload or deploy to the Mender server."
        )
        return None

    r = requests.post(
        f"{context.mender_host}/api/management/v1/{mender_endpoint}",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {context.mender_pat}",
        },
        **request_args,
    )
    if r.status_code != 201:
        context.logger.error(
            f"Request failed for endpoint {mender_endpoint}: status={r.status_code}, text={r.text}, url={r.request.url}, headers={r.request.headers}"
        )
        r.raise_for_status()
    else:
        return r


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
        try:
            stats = get_deployment_status(context, deployment_id)
            if stats is None:
                context.logger.error("Failed to get deployment status.")
                return False

            status = stats.get("status", {})
            context.logger.info(
                f"Deployment {deployment_id} status: "
                f"success={status.get('success', 0)}, "
                f"failure={status.get('failure', 0)}, "
                f"pending={status.get('pending', 0)}, "
                f"installing={status.get('installing', 0)}"
            )

            # Check if deployment is complete (no more pending or installing)
            total_active = status.get("pending", 0) + status.get("installing", 0)
            if total_active == 0:
                success_count = status.get("success", 0)
                failure_count = status.get("failure", 0)
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
                # No active, no success, no failure - might be no devices in group
                context.logger.warning(
                    f"Deployment {deployment_id} has no active devices and no results."
                )
                return False

            context.logger.debug(
                f"Waiting {poll_interval}s before next status check..."
            )
            time.sleep(poll_interval)

        except requests.HTTPError as e:
            context.logger.error(f"HTTP error while checking deployment: {e}")
            return False
        except Exception as e:
            context.logger.error(f"Error while waiting for deployment: {e}")
            return False

    context.logger.error(
        f"Deployment {deployment_id} timed out after {timeout} seconds."
    )
    return False
