# Asset bundles

Designers export whole folders from Figma as `.tar.gz`. Uploading a bundle replaces a lot of
one-by-one uploads.

## Requirements

1. `POST /bundles` with form fields `project` (the slug) and `bundle` (the file).
2. A bundle may be at most 50 MB as uploaded **and** at most 200 MB / 2,000 files once
   extracted. Larger bundles are rejected with 413 before anything is written.
3. Members are extracted under the project's directory, keeping their folder structure.
   Nothing may be written outside the project's directory: reject absolute paths, `..`
   components, and links (symlinks and hard links) and device files. One bad member rejects
   the whole bundle with 400; no partial extraction.
4. Nested files are downloadable at `GET /projects/<slug>/files/<path>` (e.g.
   `icons/24/close.svg`). Downloads must stay inside the project's directory.
5. The response lists the extracted files.
