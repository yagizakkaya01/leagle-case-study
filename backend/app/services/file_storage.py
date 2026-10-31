"""Where uploaded PDF files live: a local folder, or Azure Blob Storage.

Both backends share one small interface, so DocumentStore does not care which
one is configured. Files are named by their sha256 document id.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings

log = logging.getLogger(__name__)


class FileStorage(ABC):
    @abstractmethod
    def save(self, document_id: str, data: bytes) -> None: ...

    @abstractmethod
    def load(self, document_id: str) -> bytes | None: ...

    @abstractmethod
    def delete(self, document_id: str) -> None: ...


class LocalFileStorage(FileStorage):
    def __init__(self, directory: Path):
        self._dir = directory

    def save(self, document_id: str, data: bytes) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path(document_id).write_bytes(data)

    def load(self, document_id: str) -> bytes | None:
        path = self._path(document_id)
        return path.read_bytes() if path.exists() else None

    def delete(self, document_id: str) -> None:
        self._path(document_id).unlink(missing_ok=True)

    def _path(self, document_id: str) -> Path:
        return self._dir / f"{document_id}.pdf"


class AzureBlobStorage(FileStorage):
    def __init__(self, connection_string: str, container: str):
        service = BlobServiceClient.from_connection_string(connection_string)
        self._container = service.get_container_client(container)
        try:
            self._container.create_container()
        except ResourceExistsError:
            pass

    def save(self, document_id: str, data: bytes) -> None:
        # Same content -> same name, so a re-upload simply overwrites with identical bytes.
        self._container.upload_blob(
            f"{document_id}.pdf", data, overwrite=True,
            content_settings=ContentSettings(content_type="application/pdf"),
        )

    def load(self, document_id: str) -> bytes | None:
        try:
            return self._container.download_blob(f"{document_id}.pdf").readall()
        except ResourceNotFoundError:
            return None

    def delete(self, document_id: str) -> None:
        try:
            self._container.delete_blob(f"{document_id}.pdf")
        except ResourceNotFoundError:
            pass


def build_file_storage(azure_connection_string: str, container: str,
                       local_dir: Path) -> FileStorage:
    if azure_connection_string:
        log.info("Storing PDFs in Azure Blob container '%s'", container)
        return AzureBlobStorage(azure_connection_string, container)
    return LocalFileStorage(local_dir)
