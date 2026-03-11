"""Tests for job_hunter.notion.drive_uploader — DriveUploader."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from job_hunter.notion.drive_uploader import DriveUploader, FOLDER_NAME


@pytest.fixture
def mock_service():
    service = MagicMock()
    return service


@pytest.fixture
def uploader(mock_service):
    with patch("job_hunter.notion.drive_uploader.DriveUploader._get_service", return_value=mock_service):
        u = DriveUploader(credentials_path="/fake/creds.json")
        u._service = mock_service
        yield u


# --- Folder management ---

def test_ensure_folder_finds_existing(uploader, mock_service):
    mock_service.files().list().execute.return_value = {
        "files": [{"id": "folder-abc", "name": FOLDER_NAME}]
    }

    folder_id = uploader._ensure_folder()

    assert folder_id == "folder-abc"
    assert uploader._folder_id == "folder-abc"


def test_ensure_folder_creates_new(uploader, mock_service):
    mock_service.files().list().execute.return_value = {"files": []}
    mock_service.files().create().execute.return_value = {"id": "new-folder-id"}

    folder_id = uploader._ensure_folder()

    assert folder_id == "new-folder-id"


def test_ensure_folder_cached(uploader):
    uploader._folder_id = "cached-id"

    folder_id = uploader._ensure_folder()

    assert folder_id == "cached-id"


# --- File upload ---

def test_upload_file_success(uploader, mock_service, tmp_path):
    pdf_file = tmp_path / "resume.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 test content")

    uploader._folder_id = "folder-id"

    mock_service.files().create().execute.return_value = {
        "id": "file-id-123",
        "webViewLink": "https://drive.google.com/file/d/file-id-123/view",
    }
    mock_service.permissions().create().execute.return_value = {}

    with patch.dict("sys.modules", {"googleapiclient.http": MagicMock()}):
        url = uploader.upload_file(pdf_file)

    assert url == "https://drive.google.com/file/d/file-id-123/view"


def test_upload_file_not_found(uploader):
    result = uploader.upload_file(Path("/nonexistent/file.pdf"))

    assert result is None


def test_upload_file_exception(uploader, mock_service, tmp_path):
    pdf_file = tmp_path / "resume.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 test")

    uploader._folder_id = "folder-id"

    with patch.dict("sys.modules", {"googleapiclient.http": MagicMock()}):
        mock_service.files().create().execute.side_effect = Exception("API error")
        result = uploader.upload_file(pdf_file)

    assert result is None


# --- Convenience methods ---

def test_upload_resume(uploader, tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF")

    uploader._folder_id = "f"
    with patch.object(uploader, "upload_file", return_value="https://link") as mock_upload:
        result = uploader.upload_resume(pdf)

    mock_upload.assert_called_once_with(pdf, "application/pdf")
    assert result == "https://link"


def test_upload_cover_letter_pdf(uploader, tmp_path):
    pdf = tmp_path / "cover.pdf"
    pdf.write_bytes(b"%PDF")

    with patch.object(uploader, "upload_file", return_value="https://link") as mock_upload:
        result = uploader.upload_cover_letter(pdf)

    mock_upload.assert_called_once_with(pdf, "application/pdf")


def test_upload_cover_letter_txt(uploader, tmp_path):
    txt = tmp_path / "cover.txt"
    txt.write_text("Dear Hiring Manager...")

    with patch.object(uploader, "upload_file", return_value="https://link") as mock_upload:
        result = uploader.upload_cover_letter(txt)

    mock_upload.assert_called_once_with(txt, "text/plain")


# --- Service initialization ---

def test_get_service_import_error():
    u = DriveUploader(credentials_path="/fake.json")

    with patch.dict("sys.modules", {"google.oauth2.service_account": None}):
        with pytest.raises((ImportError, ModuleNotFoundError)):
            u._get_service()
