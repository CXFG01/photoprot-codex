# PhotoProt for Codex

Attach or drag a PNG/JPEG/WebP protein image into a **local Codex task**, invoke PhotoProt and say:

> Search this protein image with PhotoProt.

The plugin uses the existing server to search its whole embedding index and returns a 20-row Markdown table:

| Rank | PDB | Protein | Organism | Similarity |
|---:|---|---|---|---:|
| … | Linked RCSB accession | RCSB title | Organism | Actual server score |

This is a skill-backed Codex plugin with a standard-library Python client. No model runs on the laptop and no new server deployment, MCP dependency, or custom upload UI is required. The native Codex attachment must expose a readable file path to the agent; if it supplies only visual context, the agent requests a file/path instead. This is not a web-only ChatGPT integration.

## Installation

Install from the GitHub marketplace using a Codex CLI with plugin support:

```text
codex plugin marketplace add CXFG01/photoprot-codex
codex plugin add photoprot@photoprot
```

Start a fresh local Codex task, attach an image, select PhotoProt's `protein-search` skill and ask it to search. See the [repository installation guide](../../README.md) for requirements and troubleshooting.

## Server configuration

`settings.json` uses the stable HTTPS origin `https://api.photoprot.uk`, connected to Brev through a named Cloudflare Tunnel. To use your own deployment, change this setting or set `PHOTOPROT_URL` in the environment used by Codex.

Priority: explicit `--server` → `PHOTOPROT_URL` → `settings.json`.

```text
python scripts/search_protein.py --health
python scripts/search_protein.py "/absolute/path/protein.png"
python scripts/search_protein.py "/absolute/path/protein.png" --top 5 --format json
python scripts/search_protein.py "/absolute/path/protein.png" --server https://your-photoprot-host
```

Python 3.10+ is required; no additional packages. On Codex desktop, use its bundled Python if Python is not on PATH. HTTPS origins are required except local loopback HTTP for development. Credentials in URLs, path/query/fragment origins and HTTP redirects are rejected. The current public API has no authentication support.

## What is sent and returned

- Exactly the selected image's original bytes: `POST /api/search`, raw body, content type determined from image contents. No automatic retry, conversion or local copy.
- Names and organisms: `GET /api/entries?ids=...` after search. Only the returned PDB IDs are requested.
- `GET /api/health` for an explicit connectivity check. It does not send an image.
- PNG/JPEG/WebP, up to 10 MB; server also limits decoded input to 20 megapixels.
- The server computes the mean of each PDB's five best reference-view cosine similarities and returns 20 distinct ranked PDBs. The client validates the response and preserves ranking. `--top` only limits displayed rows.
- Metadata failures retain the ranking and known RCSB links. Errors never produce fabricated candidates.

Similarity is not confidence, sequence identity, or TM-score. The server has no calibrated no-match detector. A correct accession does not establish assembly or protein-family identity. See [PRIVACY.md](PRIVACY.md) before handling sensitive images.

## Development and verification

Source of the tested client: `scripts/search_protein.py`; workflow: `skills/protein-search/SKILL.md`.

```text
python -m unittest discover -s tests -v
```

Unit tests cover upload types/limits, unchanged image bytes, malformed rankings, error handling, metadata failure and Markdown escaping. A live smoke test uses the public 3I3W training example and verifies the actual 20-result server response and metadata. Two user-supplied file attachments were also searched through the installed skill and returned real server tables. These are workflow checks, not an accuracy benchmark or a guarantee that every Codex attachment surface exposes a file path.
