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
