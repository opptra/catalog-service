"""Laptop-only object PUT/GET/DELETE. Registered by ``local.app``."""

from fastapi import HTTPException, Request, Response

from core.auth import SecureAPIRouter, no_auth
from core.exceptions import GcsError
from local.storage import LocalStorageClient

router = SecureAPIRouter(prefix="/local-storage", tags=["local-storage"])


def _client(request: Request) -> LocalStorageClient:
    client = request.app.state.gcs
    if not isinstance(client, LocalStorageClient):
        raise HTTPException(status_code=404, detail="Local storage is not enabled")
    return client


@router.get("/{object_name:path}")
@no_auth
def get_object(object_name: str, request: Request) -> Response:
    client = _client(request)
    try:
        data = client.download_bytes(object_name)
    except (GcsError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=data, media_type=client.content_type_for(object_name))


@router.put("/{object_name:path}", status_code=204)
@no_auth
async def put_object(object_name: str, request: Request) -> None:
    client = _client(request)
    body = await request.body()
    content_type = request.headers.get("content-type") or "application/octet-stream"
    try:
        client.upload_bytes(body, object_name, content_type=content_type)
    except (GcsError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{object_name:path}", status_code=204)
@no_auth
def delete_object(object_name: str, request: Request) -> None:
    client = _client(request)
    try:
        path = client.resolve_path(object_name)
    except (GcsError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if path.is_file():
        path.unlink()
    marker = path.with_suffix(path.suffix + ".content-type")
    if marker.is_file():
        marker.unlink()
