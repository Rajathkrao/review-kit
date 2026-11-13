import hashlib
import hmac

from jobs.handlers.webhook import sign


def test_signature():
    body = b'{"a":1}'
    assert sign("s3cret", body) == hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
