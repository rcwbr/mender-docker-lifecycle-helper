import time
import requests


def apply_client_to_group(mender_host, jwt, mender_client_id, device_group):
    response = requests.put(
        f"https://{mender_host}/api/management/v1/inventory/devices/{mender_client_id}/group",
        headers={"Authorization": f"Bearer {jwt}"},
        json={"group": device_group},
    )
    assert response.text == ""
    assert response.status_code == 204

    # Verify the client is in the group
    response = requests.get(
        f"https://{mender_host}/api/management/v1/inventory/devices",
        headers={
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/json",
        },
        params={
            "group": device_group,
        },
    )
    assert response.status_code == 200
    devices = response.json()
    device_ids = [d["id"] for d in devices]
    assert (
        mender_client_id in device_ids
    ), f"Client {mender_client_id} not found in group {device_group}. Devices in group: {device_ids}"


# def get_deployment_status(mender_host, jwt, deployment_id):
#     """Query the Mender API for deployment status.

#     Args:
#         mender_host: The Mender server host
#         jwt: JWT token for authentication
#         deployment_id: The deployment ID to check

#     Returns:
#         dict with deployment statistics or None on error
#     """
#     response = requests.get(
#         f"https://{mender_host}/api/management/v1/deployments/deployments/{deployment_id}/statistics",
#         headers={
#             "Accept": "application/json",
#             "Authorization": f"Bearer {jwt}"
#         },
#     )
#     if response.status_code != 200:
#         print(f"Failed to get deployment status: status={response.status_code}, text={response.text}")
#         return None
#     return response.json()


# def wait_for_deployment_success(mender_host, jwt, deployment_id, poll_interval=10, timeout=600):
#     """Wait for a deployment to succeed, or timeout.

#     Args:
#         mender_host: The Mender server host
#         jwt: JWT token for authentication
#         deployment_id: The deployment ID to watch
#         poll_interval: Seconds between status checks (default: 10)
#         timeout: Maximum seconds to wait (default: 600)

#     Returns:
#         True if deployment succeeded, False otherwise
#     """
#     start_time = time.time()

#     while time.time() - start_time < timeout:
#         stats = get_deployment_status(mender_host, jwt, deployment_id)
#         if stats is None:
#             print("Failed to get deployment status.")
#             return False

#         status = stats.get("status", {})
#         print(
#             f"Deployment {deployment_id} status: "
#             f"success={status.get('success', 0)}, "
#             f"failure={status.get('failure', 0)}, "
#             f"pending={status.get('pending', 0)}, "
#             f"installing={status.get('installing', 0)}"
#         )

#         # Check if deployment is complete (no more pending or installing)
#         total_active = status.get("pending", 0) + status.get("installing", 0)
#         if total_active == 0:
#             success_count = status.get("success", 0)
#             failure_count = status.get("failure", 0)
#             if failure_count > 0:
#                 print(f"Deployment {deployment_id} failed: {failure_count} device(s) reported failure.")
#                 return False
#             if success_count > 0:
#                 print(f"Deployment {deployment_id} succeeded: {success_count} device(s) reported success.")
#                 return True
#             # No active, no success, no failure - might be no devices in group
#             print(f"Deployment {deployment_id} has no active devices and no results.")
#             return False

#         time.sleep(poll_interval)

#     print(f"Deployment {deployment_id} timed out after {timeout} seconds.")
#     return False
