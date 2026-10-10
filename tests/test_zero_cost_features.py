import unittest
from unittest.mock import patch, Mock
import safe_web
from agent_features import skill_for

class SafeWebTests(unittest.TestCase):
    def test_rejects_local_and_private_urls(self):
        for url in ('http://localhost/admin', 'http://127.0.0.1/', 'http://192.168.1.2/', 'file:///etc/passwd'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                safe_web.validate_public_url(url)

    @patch('safe_web.socket.getaddrinfo')
    def test_rejects_hostname_resolving_to_private_address(self, resolver):
        resolver.return_value = [(None, None, None, None, ('10.0.0.5', 80))]
        with self.assertRaises(ValueError):
            safe_web.validate_public_url('https://example.test')

    @patch('safe_web.socket.getaddrinfo')
    @patch('safe_web.requests.get')
    def test_redirect_to_private_destination_is_rejected(self, get, resolver):
        resolver.return_value = [(None, None, None, None, ('93.184.216.34', 443))]
        redirect = Mock()
        redirect.is_redirect = True
        redirect.is_permanent_redirect = False
        redirect.headers = {'Location': 'http://127.0.0.1/admin'}
        redirect.close = Mock()
        get.return_value = redirect
        with self.assertRaises(ValueError):
            safe_web.safe_get('https://example.test')

class SkillTests(unittest.TestCase):
    def test_supported_skills_are_available(self):
        self.assertIn('French', skill_for('French lesson'))
        self.assertIn('vegetarian cooking', skill_for('vegetarian cooking'))
        self.assertIn('Buddhist Studies', skill_for('Buddhist Studies research'))
        self.assertEqual(skill_for('unknown skill'), '')


from reverse_image_fallback import (
    GOOGLE_LENS_URL,
    BING_VISUAL_SEARCH_URL,
    has_image_attachment,
    is_reverse_image_search_request,
    reverse_image_search_response,
)

class ReverseImageFallbackTests(unittest.TestCase):
    def test_detects_explicit_reverse_image_requests(self):
        self.assertTrue(is_reverse_image_search_request("Please do a reverse image search"))
        self.assertTrue(is_reverse_image_search_request("/reverseimage"))
        self.assertFalse(is_reverse_image_search_request("What breed is this cat?"))
        self.assertFalse(is_reverse_image_search_request(""))

    def test_detects_photo_and_image_documents(self):
        self.assertTrue(has_image_attachment({"photo": [{"file_id": "x"}]}))
        self.assertTrue(has_image_attachment({"document": {"mime_type": "image/png"}}))
        self.assertTrue(has_image_attachment({"document": {"file_name": "cat.webp"}}))
        self.assertFalse(has_image_attachment({"document": {"mime_type": "application/pdf", "file_name": "doc.pdf"}}))

    def test_response_is_honest_and_offers_manual_links(self):
        response = reverse_image_search_response(True)
        self.assertIn(GOOGLE_LENS_URL, response)
        self.assertIn(BING_VISUAL_SEARCH_URL, response)
        self.assertIn("upload the image yourself", response)
        self.assertIn("not forwarded", response)
        self.assertIn("can’t run an automatic", response)

    def test_missing_image_prompts_upload(self):
        response = reverse_image_search_response(False)
        self.assertIn("/reverseimage", response)
        self.assertIn(GOOGLE_LENS_URL, response)


if __name__ == '__main__':
    unittest.main()
