import json
import time
import urllib.error
import urllib.request


class ConnectError(Exception):
    pass


def _post(url, body, headers=None):
    req = urllib.request.Request(url, method="POST", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def start_device(base_url, harness, label=None):
    status, body = _post(base_url + "/connect/device", {"harness": harness, "label": label})
    if status != 200:
        raise ConnectError(f"device start failed: {status} {body}")
    return body


def poll_until_claimed(base_url, device_code, interval, *, sleep=time.sleep, deadline=None):
    while True:
        status, body = _post(base_url + "/connect/token", {"device_code": device_code})
        if status == 200:
            return body
        err = body.get("error")
        if status in (428, 429) or err in ("authorization_pending", "slow_down"):
            if deadline is not None and time.monotonic() > deadline:
                raise ConnectError("timed out waiting for approval")
            sleep(max(interval, 0))
            continue
        raise ConnectError(f"device authorization failed: {err or status}")
