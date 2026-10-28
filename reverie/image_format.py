"""Identify capture image formats when a PNG fallback is returned."""


def image_mime(data):
    """Return the MIME type of a base64 image or raw image bytes."""
    if isinstance(data, str):
        return "image/png" if data.startswith("iVBORw0KGgo") else "image/jpeg"
    return "image/png" if data.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"


def image_data_uri(data):
    return f"data:{image_mime(data)};base64,{data}"
