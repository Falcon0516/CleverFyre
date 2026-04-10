from setuptools import setup, find_packages

setup(
    name="axiom-agpp",
    version="0.1.0",
    description="AXIOM Agentic Payment Protocol SDK",
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
)
