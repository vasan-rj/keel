import argparse
import sys
import time
import webbrowser
from pathlib import Path

from keel_connect import client
from keel_connect.recipes import REGISTRY


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="keel_connect")
    ap.add_argument("harness", choices=sorted(REGISTRY))
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--label", default=None)
    ap.add_argument("--dest", default=".")
    ap.add_argument("--session", default="agent")
    ap.add_argument("--no-open", dest="open_browser", action="store_false", default=True,
                    help="do not open the verification URL in a browser")
    args = ap.parse_args(argv)

    start = client.start_device(args.url, args.harness, args.label)
    print(f"\n  To connect, open: {start['verification_uri']}")
    print(f"  and enter code:  {start['user_code']}\n")
    if args.open_browser:
        try:
            webbrowser.open(start["verification_uri"])
        except Exception:
            pass
    try:
        claim = client.poll_until_claimed(
            args.url, start["device_code"], interval=start.get("interval", 5),
            deadline=time.monotonic() + start.get("expires_in", 600))
    except client.ConnectError as e:
        print(f"  x {e}", file=sys.stderr)
        return 1
    files = REGISTRY[args.harness].write_config(
        Path(args.dest), args.url, claim["token"], args.session)
    print("  connected. wrote:")
    for f in files:
        print(f"    - {f}")
    print("\n  Next: `source .keel.env` (or export KEEL_TOKEN) and start your agent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
