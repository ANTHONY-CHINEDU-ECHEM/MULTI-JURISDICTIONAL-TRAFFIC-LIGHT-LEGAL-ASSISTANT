"""Installable package definition. Install with: pip install ."""

from pathlib import Path

from setuptools import find_packages, setup

HERE = Path(__file__).parent
REQUIREMENTS = [line.strip() for line in (HERE / "requirements.txt").read_text(encoding="utf8").splitlines()
                if line.strip() and not line.startswith("#")]

setup(
    name="trafficlegal",
    version="1.0.0",
    description="Hybrid structured and unstructured RAG for traffic signal incident and clearance interval analysis",
    long_description=(HERE / "README.md").read_text(encoding="utf8"),
    long_description_content_type="text/markdown",
    packages=find_packages(exclude=("tests",)),
    python_requires=">=3.10",
    install_requires=REQUIREMENTS,
    entry_points={"console_scripts": ["trafficlegal=trafficlegal.cli:main"]},
    license="MIT",
)
