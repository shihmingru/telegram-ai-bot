"""Optional reverse-image matching through Google Cloud Vision Web Detection.

Set GOOGLE_CLOUD_VISION_API_KEY in the deployment environment to enable it.
The module intentionally does not upload images unless the caller explicitly
requests image search.
"""
import base64
import os
import re

import requests


VISION_API_KEY_ENV = "GOOGLE_CLOUD_VISION_API_KEY"
VISION_ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"


def image_search_requested(text):
    """Return True only for explicit requests to match/search an uploaded image."""
    value = (text or "").lower()
    phrases = (
        "reverse image", "reverse search", "search this image",
        "search this photo", "find this image", "find this photo",
        "find this picture", "image source", "source of this image",
        "where is this image from", "where did this image come from",
        "find the original image", "find the original photo",
        "visually similar", "match this image", "match this photo",
        "look for this image online", "identify this image online",
        "find this online",
    )
    return any(phrase in value for phrase in phrases)


def _safe_http_url(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value if value.startswith(("https://", "http://")) else ""


def extract_web_detection(payload, limit=5):
    """Extract bounded, user-facing matches from a Vision API response."""
    responses = payload.get("responses") or []
    if not responses:
        return {"matches": [], "similar_images": [], "entities": [], "error": "No image-search response was returned."}

    response = responses[0]
    if response.get("error"):
        return {"matches": [], "similar_images": [], "entities": [], "error": response["error"].get("message", "Vision API error")}

    web = response.get("webDetection") or {}
    matches = []
    seen = set()
    for key, match_type in (
        ("fullMatchingImages", "Exact image match"),
        ("partialMatchingImages", "Partial image match"),
        ("pagesWithMatchingImages", "Page containing a matching image"),
    ):
        for item in web.get(key, []) or []:
            url = _safe_http_url(item.get("url"))
            if not url or url in seen:
                continue
            seen.add(url)
            matches.append({
                "type": match_type,
                "url": url,
                "title": str(item.get("pageTitle") or item.get("title") or "")[:240],
            })
            if len(matches) >= limit:
                break
        if len(matches) >= limit:
            break

    similar = []
    for item in web.get("visuallySimilarImages", []) or []:
        url = _safe_http_url(item.get("url"))
        if url and url not in {entry["url"] for entry in similar}:
            similar.append({"url": url, "title": str(item.get("title") or "")[:240]})
        if len(similar) >= limit:
            break

    entities = []
    for item in web.get("webEntities", []) or []:
        description = str(item.get("description") or "").strip()
        if description:
            entities.append({
                "description": description[:160],
                "score": item.get("score"),
            })
        if len(entities) >= limit:
            break

    return {"matches": matches, "similar_images": similar, "entities": entities, "error": ""}


def search_image_bytes(image_bytes, api_key=None, timeout=20):
    """Submit image bytes for web matching; no key means no network request."""
    key = api_key or os.environ.get(VISION_API_KEY_ENV)
    if not key:
        return {
            "configured": False,
            "matches": [],
            "similar_images": [],
            "entities": [],
            "error": "Reverse image search is not configured. Set GOOGLE_CLOUD_VISION_API_KEY to enable it.",
        }
    if not image_bytes:
        return {
            "configured": True,
            "matches": [],
            "similar_images": [],
            "entities": [],
            "error": "The image was empty.",
        }

    response = requests.post(
        VISION_ENDPOINT,
        params={"key": key},
        json={
            "requests": [{
                "image": {"content": base64.b64encode(image_bytes).decode("ascii")},
                "features": [{"type": "WEB_DETECTION", "maxResults": 10}],
            }]
        },
        timeout=timeout,
    )
    response.raise_for_status()
    result = extract_web_detection(response.json())
    result["configured"] = True
    return result


def format_image_search_results(result):
    """Format search evidence for the assistant without presenting guesses as facts."""
    if not result.get("configured"):
        return result.get("error", "Reverse image search is not configured.")
    if result.get("error"):
        return "Reverse image search could not complete: " + result["error"]

    lines = ["Live reverse-image search results (these are candidate matches, not proof of origin):"]
    matches = result.get("matches") or []
    if matches:
        lines.append("Matching images/pages:")
        for item in matches:
            title = (" | " + item["title"]) if item.get("title") else ""
            lines.append("- " + item["type"] + title + " | " + item["url"])
    else:
        lines.append("No exact or partial image matches were returned.")

    similar = result.get("similar_images") or []
    if similar:
        lines.append("Visually similar images:")
        for item in similar:
            title = (" | " + item["title"]) if item.get("title") else ""
            lines.append("- " + item["url"] + title)

    entities = result.get("entities") or []
    if entities:
        lines.append("Associated web entities:")
        lines.extend("- " + item["description"] for item in entities)

    lines.append("Do not claim a match is the original source unless the linked page verifies that.")
    return "\n".join(lines)
