# PhotoProt plugin data handling

This document describes implementation boundaries, not a confidentiality or zero-retention guarantee.

The plugin reads only the image explicitly selected by the user and uploads its bytes to the configured PhotoProt server. The bundled address uses a public Cloudflare tunnel to the Brev-hosted service. There is no upload-body logging, temporary image copy, local embedding store or automatic POST retry in the client. If the user saves the returned output, that save is separate from the client's default behavior.

The server processes the upload and query embedding in CPU/GPU memory. It keeps at most 128 ranked result lists in RAM for CSV export. Links expire after one hour, but expired entries remain until eviction or restart. Server access logs contain request metadata and may contain candidate PDB identifiers and export paths. Provider logs, backups, swap and crash dumps have not been comprehensively audited. Memory is not securely zeroized.

The attachment, instructions, tool calls and returned table are also handled by **Codex** and can remain in the Codex task/history under the user's Codex settings and applicable policies. "No local client upload copy" does not mean Codex discards the attachment.

RCSB-derived names and organisms are requested through PhotoProt using candidate identifiers. Clicking a PDB link contacts RCSB. A different configured server has its own operators and retention practices; inspect them before use. HTTPS protects transport to the configured service but does not prevent access by its operators or involved hosting providers.

The public preview has no audited confidential-data commitment. Do not use it for confidential/unpublished material requiring such guarantees. Private/local deployment and an appropriate operational/retention policy are needed for that use case.
