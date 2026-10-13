import unittest

from agent_workspace import validate_filename, validate_content, MAX_FILE_CHARS


class WorkspaceValidationTests(unittest.TestCase):
    def test_accepts_plain_filename(self):
        self.assertEqual(validate_filename("research notes.md"), "research notes.md")

    def test_rejects_path_traversal(self):
        for filename in ("../secret.txt", "folder/file.txt", "folder\\file.txt", ".."):
            with self.subTest(filename=filename):
                with self.assertRaises(ValueError):
                    validate_filename(filename)

    def test_rejects_empty_content(self):
        with self.assertRaises(ValueError):
            validate_content("   ")

    def test_rejects_oversized_content(self):
        with self.assertRaises(ValueError):
            validate_content("x" * (MAX_FILE_CHARS + 1))


if __name__ == "__main__":
    unittest.main()
