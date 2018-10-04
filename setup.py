#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The setup script."""

from setuptools import setup

with open('README.rst') as readme_file:
    readme = readme_file.read()

with open('HISTORY.rst') as history_file:
    history = history_file.read()

requirements = [
    'wiki',
    'channels>=2.0',
    'pyparsing',
    'aiostream',
    'file-magic',
]

setup_requirements = [
    'pytest-runner',
]

test_requirements = [
    'pytest',
]

setup(
    name='django_wiki_inputs',
    version='0.1.0',
    description="Python django_wiki_inputs contains plugin to create inputs in the wiki pages.",
    long_description=readme + '\n\n' + history,
    author="Jan Lána",
    author_email='lana.jan@gmail.com',
    url='https://github.com/jenda1/django-wiki-inputs',
    packages=[
        'django_wiki_inputs',
        'django_wiki_inputs.mdx',
        'django_wiki_inputs.migrations',
        'django_wiki_inputs.fn',
        'django_wiki_inputs.templatetags',
        ],
    include_package_data=True,
    install_requires=requirements,
    license="GNU General Public License v3",
    zip_safe=False,
    keywords='django_wiki_inputs',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Natural Language :: English',
        'Programming Language :: Python :: 3.7',
    ],
    test_suite='tests',
    tests_require=test_requirements,
    setup_requires=setup_requirements,
)
