import io


def test_upload_and_download(client):
    r = client.post("/projects/acme-web/files", data={"file": (io.BytesIO(b"hi"), "logo.svg")})
    assert r.status_code == 201
    assert client.get("/projects/acme-web/files/logo.svg").data == b"hi"
    assert client.get("/projects/acme-web/files").json == {"files": ["logo.svg"]}


def test_bad_slug(client):
    assert client.get("/projects/AB/files").status_code == 400


def test_filename_is_sanitised(client):
    r = client.post("/projects/acme-web/files", data={"file": (io.BytesIO(b"x"), "../../evil.sh")})
    assert r.json["name"] == "evil.sh"
