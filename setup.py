from setuptools import setup, find_packages

import os

# Read the contents of your README file
this_directory = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(this_directory, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="axiom-agpp",
    version="0.1.0",
    description="AXIOM Agentic Payment Protocol SDK",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="CleverFyre Hackathon Team",
    packages=find_packages(),
    install_requires=[
        "py-algorand-sdk>=2.0.0",
        "algokit-utils>=2.0.0",
        "pynacl",
        "requests",
        "pyyaml",
        "numpy",
        "scipy",
        "scikit-learn",
        "sentence-transformers",
        "fastapi",
        "uvicorn",
        "pydantic",
        "click",
    ],
    entry_points={
        "console_scripts": [
            "axiom=axiom_agpp.cli:cli",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.9",
)
