"""FileStorage backends. The Azure variant runs against Azurite (or a real account)
only when TEST_AZURE_CONNECTION_STRING is set."""
import os
from uuid import uuid4

import pytest

from app.services.file_storage import AzureBlobStorage, LocalFileStorage
from app.services.persistence import MemoryRepository
from tests.pdf_factory import make_pdf, make_store
from tests.test_chat import PAGES

AZURE = os.environ.get("TEST_AZURE_CONNECTION_STRING", "")


@pytest.fixture(params=["local", "azure"])
def files(request, tmp_path):
    if request.param == "local":
        return LocalFileStorage(tmp_path)
    if not AZURE:
        pytest.skip("TEST_AZURE_CONNECTION_STRING not set")
    return AzureBlobStorage(AZURE, f"test-{uuid4().hex[:12]}")


def test_save_and_load_round_trip(files):
    files.save("abc", b"%PDF-1.4 data")
    assert files.load("abc") == b"%PDF-1.4 data"
    assert files.load("missing") is None


def test_conversation_document_is_reloaded_from_file_storage(files):
    repo = MemoryRepository()
    doc = make_store(files, repo).add(make_pdf(PAGES), "agreement.pdf")
    # New process: nothing cached, PDF comes back from the storage backend.
    reloaded = make_store(files, repo).get(doc.document_id)
    assert reloaded is not None and reloaded.page_count == 2
