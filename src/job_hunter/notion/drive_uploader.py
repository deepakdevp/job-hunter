from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

FOLDER_NAME = "Job Hunter"


class DriveUploader:
    """Upload files to Google Drive and get shareable links."""

    def __init__(self, credentials_path: str | None = None):
        self._service = None
        self._folder_id: str | None = None
        self._credentials_path = credentials_path

    def _get_service(self):
        """Lazy-initialize the Drive service."""
        if self._service is not None:
            return self._service

        try:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build

            scopes = ["https://www.googleapis.com/auth/drive.file"]
            creds = Credentials.from_service_account_file(self._credentials_path, scopes=scopes)
            self._service = build("drive", "v3", credentials=creds)
            return self._service
        except ImportError:
            logger.error(
                "google-api-python-client not installed. "
                "Install with: pip install google-api-python-client google-auth"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to initialize Drive service: {e}")
            raise

    def _ensure_folder(self) -> str:
        """Find or create the Job Hunter folder in Drive."""
        if self._folder_id:
            return self._folder_id

        service = self._get_service()

        # Search for existing folder
        query = (
            f"name = '{FOLDER_NAME}' and mimeType = 'application/vnd.google-apps.folder' "
            f"and trashed = false"
        )
        results = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
        files = results.get("files", [])

        if files:
            self._folder_id = files[0]["id"]
            logger.info(f"Found existing Drive folder: {self._folder_id}")
            return self._folder_id

        # Create folder
        file_metadata = {
            "name": FOLDER_NAME,
            "mimeType": "application/vnd.google-apps.folder",
        }
        folder = service.files().create(body=file_metadata, fields="id").execute()
        self._folder_id = folder["id"]
        logger.info(f"Created Drive folder: {self._folder_id}")
        return self._folder_id

    def upload_file(self, file_path: Path, mime_type: str = "application/pdf") -> str | None:
        """Upload a file to the Job Hunter folder and return shareable link.

        Returns the shareable URL, or None on failure.
        """
        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            return None

        try:
            from googleapiclient.http import MediaFileUpload

            service = self._get_service()
            folder_id = self._ensure_folder()

            file_metadata = {
                "name": file_path.name,
                "parents": [folder_id],
            }
            media = MediaFileUpload(str(file_path), mimetype=mime_type)

            uploaded = (
                service.files()
                .create(body=file_metadata, media_body=media, fields="id, webViewLink")
                .execute()
            )

            file_id = uploaded["id"]

            # Set anyone-with-link permission
            service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
            ).execute()

            link = uploaded.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")
            logger.info(f"Uploaded {file_path.name} → {link}")
            return link

        except Exception as e:
            logger.warning(f"Drive upload failed for {file_path}: {e}")
            return None

    def upload_resume(self, file_path: Path) -> str | None:
        """Upload a resume PDF."""
        return self.upload_file(file_path, "application/pdf")

    def upload_cover_letter(self, file_path: Path) -> str | None:
        """Upload a cover letter (PDF or text)."""
        if file_path.suffix == ".txt":
            return self.upload_file(file_path, "text/plain")
        return self.upload_file(file_path, "application/pdf")
