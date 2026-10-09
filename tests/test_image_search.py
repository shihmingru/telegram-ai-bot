import unittest
from unittest.mock import patch

import image_search


class ImageSearchTests(unittest.TestCase):
    def test_requires_explicit_reverse_search_intent(self):
        self.assertTrue(image_search.image_search_requested("Please reverse image search this photo"))
        self.assertTrue(image_search.image_search_requested("Can you find the original image?"))
        self.assertFalse(image_search.image_search_requested("What is in this picture?"))

    def test_missing_key_fails_without_network_request(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(image_search.requests, "post") as post:
            result = image_search.search_image_bytes(b"image-bytes")
        self.assertFalse(result["configured"])
        self.assertIn("GOOGLE_CLOUD_VISION_API_KEY", result["error"])
        post.assert_not_called()

    def test_extracts_exact_and_similar_urls(self):
        payload = {"responses": [{"webDetection": {
            "fullMatchingImages": [{"url": "https://example.com/exact.jpg"}],
            "visuallySimilarImages": [{"url": "https://example.com/similar.jpg"}],
            "webEntities": [{"description": "A painting", "score": 0.91}],
        }}]}
        result = image_search.extract_web_detection(payload)
        self.assertEqual(result["matches"][0]["type"], "Exact image match")
        self.assertEqual(result["similar_images"][0]["url"], "https://example.com/similar.jpg")
        self.assertEqual(result["entities"][0]["description"], "A painting")

    def test_rejects_non_http_urls(self):
        result = image_search.extract_web_detection({"responses": [{"webDetection": {
            "fullMatchingImages": [{"url": "javascript:alert(1)"}],
        }}]})
        self.assertEqual(result["matches"], [])


if __name__ == "__main__":
    unittest.main()
