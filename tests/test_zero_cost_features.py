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

if __name__ == '__main__':
    unittest.main()
