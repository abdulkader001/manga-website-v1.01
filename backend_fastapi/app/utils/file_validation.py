from fastapi import UploadFile, HTTPException, status

ALLOWED_IMAGE_MIMETYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def validate_image_mimetype(upload: UploadFile) -> None:
    if upload.content_type not in ALLOWED_IMAGE_MIMETYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image MIME type."
        )
