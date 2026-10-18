# Reference collection helpers

These scripts retain the public-download and indexing code used for this workspace. They write to `../Reference_Library` beside the repository. Original vendor documents, archives, extracted help and text indexes remain outside Git.

- `collect.py` follows the bounded vendor download indexes and explicit seeds. It records source URLs, failures and hashes. It downloads archives without executing installers.
- `build_index.py` indexes PDFs from the library's `manuals/` and `extracted/` directories. PDF extraction additionally requires PyMuPDF. It retains page text, metadata and outlines.
- `index_html_help.py` indexes the statically extracted ALC 4.1 help snapshot. The archive must already have been extracted into the documented sibling-library path; this script never runs the vendor installer.
- `search.py` searches PDF pages and HTML help with SQLite FTS5.
- `build_project_references.py` builds factual source metadata and the curated feature criteria used by the app. Existing JCI and GitHub inventories are optional inputs. Review the generated metadata before committing; do not commit raw manuals or site files.

The existing library's README describes the extraction paths and review scope. These helpers are research tools, not a claim of exhaustive internet coverage or automatic understanding of every vendor restriction.
