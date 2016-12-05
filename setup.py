#!/usr/bin/env python
import os
from setuptools import setup, find_packages
from inkblock import __name__ as package_name

DESCRIPTION = "A simple, end-to-end publishing platform."
ROOT_DIR = os.path.dirname(__file__)
SOURCE_DIR = os.path.join(ROOT_DIR)
VERSION = "0.6.4"

reqs = []
with open("requirements.txt", "r+") as f:
    for line in f.readlines():
        reqs.append(line.strip())

try:
    import pypandoc
    long_description = pypandoc.convert('README.md', 'rst')
except (IOError, ImportError, OSError, RuntimeError):
    try:
        import os
        long_description = open(os.path.join(os.path.dirname(__file__), 'README.md')).read()
    except:
        long_description = DESCRIPTION + '\n'

setup(
    name="inkblock",
    description=DESCRIPTION,
    long_description=long_description,
    author="Steven Skoczen",
    author_email="skoczen@gmail.com",
    url="https://github.com/skoczen/inkblock",
    version=VERSION,
    download_url=['https://github.com/skoczen/inkblock/tarball/%s' % VERSION, ],
    install_requires=reqs,
    packages=find_packages(),
    include_package_data=True,
    keywords=["static", "generator", "social"],
    classifiers=[
        "Programming Language :: Python",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    entry_points={
        'console_scripts': ['ink = inkblock.main:cli', ],
    },
)
