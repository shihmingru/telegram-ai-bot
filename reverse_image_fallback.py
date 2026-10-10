"""Free manual handoff for reverse-image searches.

This deliberately does not upload images to a third-party API or claim to
perform automated image matching. The user opens a visual-search site and
uploads the image themselves.
"""

import re

GOOGLE_LENS_URL = "https://lens.google.com/"
BING_VISUAL_SEARCH_URL = "https://www.bing.com/visualsearch"


def is_reverse_image_search_request(text):
    """Return True when a message explicitly asks for reverse-image search."""
    value = (text or "").strip().lower()
    if not value:
        return False
    if re.match(r"^/reverseimage(?:@\w+)?(?:\s|$)", value):
        return True
    phrases = (
        "reverse image search",
        "reverse-image search",
        "reverse search this image",
        "search this image",
        "search by image",
        "find this image online",
        "find the original image",
        "find similar images",
        "where is this image from",
        "where did this image come from",
        "identify the source of this image",
    )
    return any(phrase in value for phrase in phrases)


def has_image_attachment(message):
    """Detect Telegram photo or image-document attachments without downloading."""
    if message.get("photo"):
        return True
    document = message.get("document") or {}
    mime_type = (document.get("mime_type") or "").lower()
    file_name = (document.get("file_name") or "").lower()
    return mime_type.startswith("image/") or file_name.endswith(
        (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff")
    )


def reverse_image_search_response(image_attached):
    """Explain the free manual workflow honestly; no external request is made."""
    links = (
        "Google Lens: " + GOOGLE_LENS_URL + "\n"
        "Bing Visual Search: " + BING_VISUAL_SEARCH_URL
    )
    if image_attached:
        return (
            "I can’t run an automatic reverse-image match in this bot without a "
            "verified free provider. To keep this bot free-only, I have not enabled "
            "any paid or potentially billable image-search API.\n\n"
            "For a free manual search, open one of these sites and upload the image "
            "yourself (the image you sent here is not forwarded):\n"
            + links
        )
    return (
        "To search an image, send it with the caption /reverseimage, or ask for a "
        "reverse image search in the same message. I’ll give you free visual-search "
        "links; you will need to upload the image yourself.\n\n"
        + links
    )
