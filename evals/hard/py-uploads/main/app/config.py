import os


class Config:
    STORAGE_ROOT = os.environ.get("STORAGE_ROOT", "/data/assets")
    MAX_CONTENT_LENGTH = 60 * 1024 * 1024
    MAX_FILE_BYTES = 20 * 1024 * 1024
    SIGNING_KEY = os.environ.get("SIGNING_KEY", "dev-only-key")
