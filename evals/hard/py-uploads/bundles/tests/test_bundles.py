import io
import tarfile

import pytest


def make_bundle(files: dict[str, bytes]) -> io.BytesIO:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf


def post_bundle(client, project, bundle):
    return client.post("/bundles", data={"project": project, "bundle": (bundle, "b.tar.gz")})


def test_bundle_upload_and_nested_download(client):
    r = post_bundle(client, "acme-web", make_bundle({"icons/24/close.svg": b"<svg/>", "readme.txt": b"hi"}))
    assert r.status_code == 201
    assert r.json["files"] == ["icons/24/close.svg", "readme.txt"]
    assert client.get("/projects/acme-web/files/icons/24/close.svg").data == b"<svg/>"


@pytest.mark.parametrize("name", ["../escape.txt", "/etc/cron.d/x", "a/../../b"])
def test_rejects_unsafe_paths(client, name):
    r = post_bundle(client, "acme-web", make_bundle({name: b"x"}))
    assert r.status_code == 400


def test_rejects_garbage(client):
    r = post_bundle(client, "acme-web", io.BytesIO(b"not a tarball"))
    assert r.status_code == 400


def test_rejects_bad_slug(client):
    r = post_bundle(client, "AB", make_bundle({"a.txt": b"x"}))
    assert r.status_code == 400


def test_too_many_files(app, client):
    app.config["MAX_BUNDLE_FILES"] = 2
    r = post_bundle(client, "acme-web", make_bundle({f"{i}.txt": b"x" for i in range(3)}))
    assert r.status_code == 413
