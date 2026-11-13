import io

import pytest


def upload(client, name, data=b"x"):
    r = client.post("/projects/acme-web/files", data={"file": (io.BytesIO(data), name)})
    assert r.status_code == 201
    return r.json["name"]


@pytest.mark.parametrize("name,ctype,attachment", [
    ("logo.svg", "image/svg+xml", True),
    ("page.html", "text/html", True),
    ("app.js", "text/javascript", True),
    ("photo.png", "image/png", False),
    ("notes.txt", "text/plain", False),
    ("blob.unknownext", "application/octet-stream", False),
])
def test_content_type(client, name, ctype, attachment):
    upload(client, name)
    r = client.get(f"/projects/acme-web/files/{name}")
    assert r.status_code == 200
    assert r.mimetype == ctype
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert ("attachment" in r.headers.get("Content-Disposition", "")) is attachment


def test_csp_sandbox(client):
    upload(client, "photo.png")
    r = client.get("/projects/acme-web/files/photo.png")
    assert "sandbox" in r.headers["Content-Security-Policy"]
