
from setuptools import setup

setup(
    name = "musicmanager",
    packages = ["musicmanager"],
    version = "0.1.0",
    author = "Chris Thunes",
    author_email = "cthunes@brewtab.com",
    url = "http://github.com/c2nes/musicmanager",
    description = "Tools for managing/organizing your music library",
    classifiers = [
        "Programming Language :: Python",
        "Development Status :: 4 - Beta",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: MIT License",
        "Intended Audience :: End Users/Desktop",
        "Topic :: Multimedia :: Sound/Audio"
        ],
    install_requires=["mutagen", "argparse"],
    entry_points={
        'console_scripts': [
            'music-man = musicmanager.frontend:main'
            ]
        }
)
