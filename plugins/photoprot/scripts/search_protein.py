#!/usr/bin/env python3
"""Send one user-selected image to PhotoProt; return verified ranks and metadata.

Python 3.10+ standard library only. No image conversion, local upload copy,
automatic POST retry, redirect following, or image logging.
"""
import argparse
import html
import json
import math
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class SearchError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def server_url(override=None):
    raw = override or os.environ.get('PHOTOPROT_URL')
    if not raw:
        raw = json.loads((ROOT / 'settings.json').read_text(encoding='utf-8'))['server_url']
    parts = urllib.parse.urlsplit(raw)
    if (not parts.hostname or parts.username or parts.password or parts.query or parts.fragment
            or parts.path not in ('', '/')
            or not (parts.scheme == 'https' or
                    (parts.scheme == 'http' and parts.hostname in ('127.0.0.1', 'localhost', '::1')))):
        raise SearchError('Use an HTTPS server origin without credentials, path, query or fragment (HTTP is allowed only on loopback).')
    return raw.rstrip('/')


def read_image(path):
    p = Path(path).expanduser()
    if not p.is_file():
        raise SearchError('The selected attachment is not a readable local file. Supply its actual file path.')
    with p.open('rb') as stream:
        data = stream.read(MAX_IMAGE_BYTES + 1)
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise SearchError('Choose a non-empty PNG, JPEG or WebP image no larger than 10 MB.')
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        mime = 'image/png'
    elif data.startswith(b'\xff\xd8\xff'):
        mime = 'image/jpeg'
    elif len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        mime = 'image/webp'
    else:
        raise SearchError('Unsupported image contents. Choose PNG, JPEG or WebP; changing a filename extension is insufficient.')
    return data, mime


def request_json(url, data=None, mime=None, timeout=90):
    headers = {'Accept': 'application/json', 'User-Agent': 'PhotoProt-Codex/0.1.0'}
    if mime:
        headers['Content-Type'] = mime
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        messages = {
            400: 'The server could not decode this image. Use PNG, JPEG or WebP under 20 megapixels.',
            401: 'The server requires authentication; this plugin is configured for the public preview.',
            403: 'The server refused access.',
            404: 'PhotoProt was not found. The temporary preview URL may have changed; update PHOTOPROT_URL.',
            413: 'The image exceeds the server size limit (10 MB / 20 megapixels).',
            429: 'PhotoProt is busy. Wait briefly and try again.',
            502: 'The PhotoProt server or preview tunnel is unavailable. Try again later.',
            503: 'PhotoProt is temporarily unavailable. Try again later.',
        }
        if 300 <= exc.code < 400:
            raise SearchError('The server redirected the request. No redirect was followed; verify the configured PhotoProt URL.') from None
        raise SearchError(messages.get(exc.code, f'PhotoProt returned HTTP {exc.code}.')) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SearchError('Could not reach PhotoProt or the request timed out. Check the server/tunnel address. The upload was not automatically retried.') from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise SearchError('The server response exceeded the expected size.')
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise SearchError('The configured endpoint did not return PhotoProt JSON. Check whether the preview URL has expired.') from None


def validate_results(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('results'), list) or len(payload['results']) != 20:
        raise SearchError('The server did not return the expected 20-result ranking.')
    rows = []; seen = set(); previous = math.inf
    for expected, row in enumerate(payload['results'], 1):
        if not isinstance(row, dict):
            raise SearchError('Invalid result row.')
        pdb = str(row.get('pdb_id', '')).upper()
        score = row.get('score')
        if (not re.fullmatch(r'[A-Z0-9]{4}', pdb) or pdb in seen
                or type(row.get('rank')) is not int or row.get('rank') != expected or isinstance(score, bool)
                or not isinstance(score, (int, float)) or not math.isfinite(score)
                or not -1.0001 <= score <= 1.0001 or score > previous + 1e-7):
            raise SearchError('The server returned invalid, duplicate or unsorted results; no ranking will be displayed.')
        seen.add(pdb); previous = score
        # Construct known RCSB links rather than trusting arbitrary response URLs.
        rows.append({'rank': expected, 'pdb_id': pdb, 'score': score,
                     'pdb_url': f'https://www.rcsb.org/structure/{pdb}',
                     'title': 'Metadata unavailable', 'organisms': []})
    for key in ['gallery_images', 'gallery_entries']:
        if type(payload.get(key)) is not int or payload[key] < 20:
            raise SearchError('Missing or invalid gallery counts in the server response.')
    if payload.get('aggregation') != 'top5':
        raise SearchError('The server aggregation has changed. Update the plugin before interpreting these results.')
    return rows


def search(image_path, server=None):
    origin = server_url(server)
    image, mime = read_image(image_path)
    payload = request_json(origin + '/api/search', image, mime)
    rows = validate_results(payload)
    warnings = []
    try:
        meta = request_json(origin + '/api/entries?ids=' + ','.join(row['pdb_id'] for row in rows), timeout=25)
        if not isinstance(meta, list):
            raise SearchError('Unexpected metadata response.')
        by_pdb = {str(m.get('pdb_id', '')).upper(): m for m in meta if isinstance(m, dict)}
        for row in rows:
            entry = by_pdb.get(row['pdb_id'], {})
            if isinstance(entry.get('title'), str):
                row['title'] = entry['title'][:1200]
            if isinstance(entry.get('organisms'), list):
                row['organisms'] = [s[:300] for s in entry['organisms'] if isinstance(s, str)][:12]
            if not entry or entry.get('metadata_unavailable'):
                warnings.append('Some protein metadata is unavailable; the ranking is unaffected.')
    except SearchError:
        warnings.append('Protein metadata is temporarily unavailable; PDB links and ranking remain valid.')
    return {'server': origin, 'model': str(payload.get('model', 'PhotoProt'))[:200],
            'gallery_images': payload['gallery_images'], 'gallery_entries': payload['gallery_entries'],
            'aggregation': 'top5', 'results': rows, 'warnings': list(dict.fromkeys(warnings)),
            'score_note': 'Mean of the five strongest reference-view cosine similarities per PDB; not a confidence probability or proof of identity/homology.'}


def cell(value):
    # Metadata is untrusted data, not Markdown, HTML or model instructions.
    value = ' '.join(str(value).split())[:240]
    value = html.escape(value, quote=False).replace('|', '&#124;')
    for ch in ['\\', '`', '*', '_', '[', ']']:
        value = value.replace(ch, '\\' + ch)
    return value


def markdown(result, top=20):
    lines = [f"Searched **{result['gallery_images']:,} images** across **{result['gallery_entries']:,} PDB entries**.", '',
             '| Rank | PDB | Protein | Organism | Similarity |',
             '|---:|---|---|---|---:|']
    for row in result['results'][:top]:
        lines.append(f"| {row['rank']} | [{row['pdb_id']}]({row['pdb_url']}) | {cell(row['title'])} | {cell('; '.join(row['organisms']) or 'Unavailable')} | {row['score']:.3f} |")
    lines.extend(['', result['score_note']])
    lines.extend(['', *result['warnings']] if result['warnings'] else [])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', nargs='?', help='Actual local path of the user-selected image attachment')
    parser.add_argument('--server', help='Explicit PhotoProt HTTPS origin; otherwise PHOTOPROT_URL or settings.json')
    parser.add_argument('--health', action='store_true', help='Check the server without sending an image')
    parser.add_argument('--top', type=int, choices=range(1, 21), default=20, metavar='1..20')
    parser.add_argument('--format', choices=['markdown', 'json'], default='markdown')
    args = parser.parse_args()
    try:
        if args.health:
            print(json.dumps(request_json(server_url(args.server) + '/api/health', timeout=15), indent=2))
            return
        if not args.image:
            parser.error('Provide an image attachment path or --health.')
        result = search(args.image, args.server)
        if args.format == 'json':
            result['results'] = result['results'][:args.top]
            print(json.dumps(result, ensure_ascii=True, indent=2))
        else:
            print(markdown(result, args.top))
    except (SearchError, OSError, ValueError, KeyError) as exc:
        print(f'PhotoProt: {exc}', file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    main()
