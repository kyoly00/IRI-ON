import os
from urllib.parse import quote

import httpx


class AvatarStorageError(RuntimeError):
    pass


def _settings() -> tuple[str, str, str]:
    base_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    bucket = os.getenv("SUPABASE_AVATAR_BUCKET", "avatars")
    if not base_url or not service_key:
        raise AvatarStorageError("Avatar storage is not configured")
    return base_url, service_key, bucket


def _headers(service_key: str, content_type: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def upload_avatar(path: str, data: bytes) -> None:
    base_url, service_key, bucket = _settings()
    object_path = quote(path, safe="/")
    url = f"{base_url}/storage/v1/object/{quote(bucket)}/{object_path}"
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            url,
            headers={
                **_headers(service_key, "image/webp"),
                "x-upsert": "false",
            },
            content=data,
        )
    if response.status_code not in {200, 201}:
        raise AvatarStorageError(f"Avatar upload failed ({response.status_code})")


def delete_avatar(path: str) -> None:
    if not path:
        return
    base_url, service_key, bucket = _settings()
    object_path = quote(path, safe="/")
    url = f"{base_url}/storage/v1/object/{quote(bucket)}/{object_path}"
    with httpx.Client(timeout=15.0) as client:
        response = client.delete(url, headers=_headers(service_key))
    if response.status_code not in {200, 204, 404}:
        raise AvatarStorageError(f"Avatar deletion failed ({response.status_code})")


def signed_avatar_url(path: str, expires_in: int = 3600) -> str | None:
    if not path:
        return None
    try:
        base_url, service_key, bucket = _settings()
    except AvatarStorageError:
        return None
    object_path = quote(path, safe="/")
    url = f"{base_url}/storage/v1/object/sign/{quote(bucket)}/{object_path}"
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                url,
                headers=_headers(service_key, "application/json"),
                json={"expiresIn": expires_in},
            )
        response.raise_for_status()
        signed = response.json().get("signedURL") or response.json().get("signedUrl")
        return f"{base_url}/storage/v1{signed}" if signed and signed.startswith("/") else signed
    except (httpx.HTTPError, ValueError):
        return None
