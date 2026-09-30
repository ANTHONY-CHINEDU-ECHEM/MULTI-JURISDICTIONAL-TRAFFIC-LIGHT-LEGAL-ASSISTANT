"""Shared fixtures. The first run builds data, index and database if they are missing."""

import pytest

from trafficlegal import config


@pytest.fixture(scope="session", autouse=True)
def prepared():
    if not (config.RAW_DIR / "crash_events.csv").exists():
        from trafficlegal.synth import generate

        generate()
    if not config.INDEX_PATH.exists():
        from trafficlegal.ingest import build_index

        build_index()
    if not config.DB_PATH.exists():
        from trafficlegal.store import build_database

        build_database()
    return True


@pytest.fixture(scope="session")
def assistant():
    from trafficlegal.assistant import LegalAssistant

    return LegalAssistant()
