from django.test import SimpleTestCase

from projects.slugs import slugify_project_name


class SlugifyProjectNameTests(SimpleTestCase):
    def test_lowercases_and_hyphenates(self):
        self.assertEqual(slugify_project_name('My Project!'), 'my-project')

    def test_collapses_multiple_separators(self):
        self.assertEqual(slugify_project_name('My   Cool___Project'), 'my-cool-project')

    def test_strips_leading_and_trailing_hyphens(self):
        self.assertEqual(slugify_project_name('  --Hello--  '), 'hello')

    def test_all_punctuation_slugifies_to_empty_string(self):
        self.assertEqual(slugify_project_name('!!!'), '')

    def test_empty_input_slugifies_to_empty_string(self):
        self.assertEqual(slugify_project_name(''), '')
