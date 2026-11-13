import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({"STORAGE_ROOT": str(tmp_path / "assets"), "TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()
