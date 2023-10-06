""" Some helper methods for working with Google Drive """
import requests
from django.core.files.base import ContentFile
from cwcommon.models import FileUpload

WORD_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
GOOGLE_DOC_EXPORT_URL = (
    lambda file_id: f"https://www.googleapis.com/drive/v3/files/{file_id}/export?mimeType={WORD_MIME_TYPE}"
)


class GoogleDriveException(Exception):
    pass


class GoogleDriveManager:
    def export_google_doc(self, google_doc_id: str, access_token: str, filename: str):
        """ Export a Google Doc as a Word file
            Arguments:
                access_token: OAuth access token for user that Google Drive file belongs to
                google_doc_id: ID of Google Doc to download as Word file and
                filename: Name of Google Doc (will become title of FileUpload)
            Returns File Upload
            Throws GoogleDriveException for any 4xx or 5xx from Google
        """
        response = requests.get(
            GOOGLE_DOC_EXPORT_URL(google_doc_id), headers={"Authorization": f"Bearer {access_token}"}
        )
        if not response.status_code == 200:
            # TODO: Sentyr log
            breakpoint()
            raise GoogleDriveException()
        file_upload = FileUpload.objects.create(title=filename)
        file_upload.file_resource.save(filename, ContentFile(response.content))
        return file_upload
