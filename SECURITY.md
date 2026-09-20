# Security and credential hygiene

PhotoProt is a hackathon prototype, not a security-hardened production product.

Do not commit API keys, private keys, tunnel credentials, `.env` files, local logs or account exports. Public service URLs, PDB identifiers and artifact checksums are not credentials. Deployment examples refer to a token file; the token itself must remain outside the repository with restricted permissions.

A pinned, checksum-verified Gitleaks workflow scans reachable Git history on pushes and pull requests. Reports and console output redact potential secrets. One narrow allowlist covers the service-file SHA-256 in `SHA256SUMS.json`, verified against the file it describes.

## Audit on 20 September 2026

Fetched remote branches and tags and scanned all locally reachable history: four existing commits in each repository (including the newly published API-hardening commit). No credentials were found. The sole raw-scanner finding was the verified service-file checksum described above.

The reproducibility audit also checked five model/index artifacts against published release hashes and scanned 121.91 MB of extracted non-executable metadata, including checkpoint pickle strings without deserializing objects and Parquet text fields. The sixth asset, the public open-image archive, matched its published hash and contained 708 PNGs and one JSON file; its scannable content had no findings.

This is a point-in-time automated scan and targeted review, not proof that no secret can exist. It does not inspect private account settings, inaccessible/deleted remote objects, image pixels for visually embedded text, or arbitrary data encoded inside numeric tensors.

If a credential is exposed, revoke/rotate it with its issuer first. Removing it from the latest commit alone does not remove it from history, caches or clones. Do not post the credential in a public issue.
