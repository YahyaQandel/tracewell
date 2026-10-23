import re


def slugify_project_name(name):
    slug = name.strip().lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    return slug
