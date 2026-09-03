"""Object-storage abstraction (§44). Local for dev, Vercel Blob / S3 in prod."""

from __future__ import annotations

import abc
from pathlib import Path

import httpx

from app.core.config import settings
from app.core.errors import AuraError, NotFoundError


class StorageProvider(abc.ABC):
    name = "base"

    @abc.abstractmethod
    async def upload(
        self, key: str, payload: bytes, content_type: str = "application/octet-stream"
    ) -> str: ...

    @abc.abstractmethod
    async def download(self, key: str) -> bytes: ...

    @abc.abstractmethod
    async def delete(self, key: str) -> None: ...


class LocalStorageProvider(StorageProvider):
    """Development only — the filesystem is NOT durable on Vercel."""

    name = "local"

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or settings.storage_dir)

    def _path(self, key: str) -> Path:
        safe = key.replace("..", "_").lstrip("/")
        p = self.root / safe
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    async def upload(
        self, key: str, payload: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        self._path(key).write_bytes(payload)
        return f"local://{key}"

    async def download(self, key: str) -> bytes:
        p = self._path(key)
        if not p.exists():
            raise NotFoundError(f"object '{key}' not found")
        return p.read_bytes()

    async def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()


class MemoryStorageProvider(StorageProvider):
    """Used in tests and as a serverless fallback for small payloads."""

    name = "memory"
    _store: dict[str, bytes] = {}

    async def upload(
        self, key: str, payload: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        self._store[key] = payload
        return f"memory://{key}"

    async def download(self, key: str) -> bytes:
        if key not in self._store:
            raise NotFoundError(f"object '{key}' not found")
        return self._store[key]

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


class VercelBlobStorageProvider(StorageProvider):
    """Production provider backed by Vercel Blob."""

    name = "blob"
    endpoint = "https://blob.vercel-storage.com"

    def __init__(self, token: str | None = None) -> None:
        self.token = token or settings.blob_read_write_token
        self._urls: dict[str, str] = {}

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise AuraError("BLOB_READ_WRITE_TOKEN is not configured")
        return {"authorization": f"Bearer {self.token}", "x-api-version": "7"}

    async def upload(
        self, key: str, payload: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.put(
                f"{self.endpoint}/{key}",
                headers={
                    **self._headers(),
                    "content-type": content_type,
                    "x-add-random-suffix": "0",
                },
                content=payload,
            )
        if r.status_code >= 400:
            raise AuraError(f"blob upload failed with HTTP {r.status_code}")
        url = r.json().get("url", "")
        self._urls[key] = url
        return url

    async def download(self, key: str) -> bytes:
        url = self._urls.get(key) or key
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
            r = await c.get(url)
        if r.status_code >= 400:
            raise NotFoundError(f"object '{key}' not found in blob storage")
        return r.content

    async def delete(self, key: str) -> None:
        async with httpx.AsyncClient(timeout=30) as c:
            await c.post(
                f"{self.endpoint}/delete",
                headers=self._headers(),
                json={"urls": [self._urls.get(key, key)]},
            )


_PROVIDERS = {
    "local": LocalStorageProvider,
    "memory": MemoryStorageProvider,
    "blob": VercelBlobStorageProvider,
}

_instance: StorageProvider | None = None


def get_storage() -> StorageProvider:
    global _instance
    if _instance is None:
        name = settings.storage_provider
        if name == "blob" and not settings.blob_read_write_token:
            name = "memory"
        if name == "local" and settings.is_serverless:
            name = "memory"  # never rely on the serverless filesystem (§39)
        _instance = _PROVIDERS.get(name, LocalStorageProvider)()
    return _instance


def set_storage(provider: StorageProvider | None) -> None:
    global _instance
    _instance = provider
