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
