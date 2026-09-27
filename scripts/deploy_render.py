from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import urllib.error
import urllib.request

API = "https://api.render.com/v1"


def api_request(method: str, path: str, key: str, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request) as response:
        body = response.read()
    return json.loads(body) if body else None


def build_payload(
    name: str,
    owner_id: str,
    image: str,
    plan: str,
    health_check_path: str,
    env_vars: dict[str, str],
) -> dict:
    return {
        "type": "web_service",
        "name": name,
        "ownerId": owner_id,
        "image": {"imagePath": image, "ownerId": owner_id},
        "serviceDetails": {
            "runtime": "image",
            "plan": plan,
            "healthCheckPath": health_check_path,
            "env": [
                {"key": key, "value": value} for key, value in sorted(env_vars.items())
            ],
        },
    }


def build_patch(payload: dict) -> dict:
    return {
        "image": payload["image"],
        "serviceDetails": payload["serviceDetails"],
    }


def resolve_owner_id(key: str, owner_id: str | None) -> str:
    if owner_id:
        return owner_id
    owners = api_request("GET", "/owners", key)
    if not owners:
        raise RuntimeError("this API key has no accessible owner")
    return owners[0]["owner"]["id"]


def find_service_id(key: str, name: str) -> str | None:
    for service in api_request("GET", "/services?limit=100", key):
        if service["service"]["name"] == name:
            return service["service"]["id"]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or update a Render web service from a prebuilt image."
    )
    parser.add_argument(
        "--image",
        required=True,
        help="image path, e.g. docker.io/username/order-search:latest",
    )
    parser.add_argument("--name", default="order-search")
    parser.add_argument("--plan", default="free")
    parser.add_argument("--health-check-path", default="/healthz")
    parser.add_argument("--owner-id", default=None)
    parser.add_argument("--data-key", default=os.environ.get("DATA_KEY", ""))
    parser.add_argument("--data-key-id", default=os.environ.get("DATA_KEY_ID", "v1"))
    parser.add_argument(
        "--admin-username", default=os.environ.get("ADMIN_USERNAME", "admin")
    )
    parser.add_argument(
        "--admin-password", default=os.environ.get("ADMIN_PASSWORD", "")
    )
    parser.add_argument("--secret-key", default=os.environ.get("SECRET_KEY", ""))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    missing = [
        label
        for label, value in (
            ("DATA_KEY", args.data_key),
            ("ADMIN_PASSWORD", args.admin_password),
        )
        if not value
    ]
    if missing:
        print(
            f"missing required value: {', '.join(missing)} "
            "(pass as a flag or set the env var)",
            file=sys.stderr,
        )
        return 2

    secret_key = args.secret_key or secrets.token_urlsafe(48)
    env_vars = {
        "DATA_KEY": args.data_key,
        "DATA_KEY_ID": args.data_key_id,
        "ADMIN_USERNAME": args.admin_username,
        "ADMIN_PASSWORD": args.admin_password,
        "SECRET_KEY": secret_key,
        "COOKIE_SECURE": "true",
    }

    key = os.environ.get("RENDER_API_KEY", "")
    if args.dry_run:
        payload = build_payload(
            args.name, "owner-placeholder", args.image, args.plan,
            args.health_check_path, env_vars,
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if not key:
        print("RENDER_API_KEY is required", file=sys.stderr)
        return 2

    try:
        owner_id = resolve_owner_id(key, args.owner_id)
        payload = build_payload(
            args.name,
            owner_id,
            args.image,
            args.plan,
            args.health_check_path,
            env_vars,
        )
        service_id = find_service_id(key, args.name)
        if service_id is None:
            created = api_request("POST", "/services", key, payload)["service"]
            print(f"created {created['name']} ({created['id']})")
        else:
            created = api_request(
                "PATCH", f"/services/{service_id}", key, build_patch(payload)
            )["service"]
            print(f"updated {created['name']} ({created['id']})")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        print(f"render api error {error.code}: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as error:
        print(f"cannot reach render api: {error.reason}", file=sys.stderr)
        return 1

    print(f"dashboard : https://dashboard.render.com/web/{created.get('slug', created['id'])}")
    print(f"env vars  : {', '.join(sorted(env_vars))}")
    if not args.secret_key:
        print(f"SECRET_KEY generated: {secret_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
