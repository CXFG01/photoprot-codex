import importlib.util
import math
import socket
import ssl
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

spec = importlib.util.spec_from_file_location('client', Path(__file__).resolve().parents[1] / 'scripts/search_protein.py')
client = importlib.util.module_from_spec(spec); spec.loader.exec_module(client)


def payload():
    return {'results':[{'rank':i+1,'pdb_id':f'{i+1000}','score':.95-i*.01} for i in range(20)],
            'gallery_images':836399,'gallery_entries':38833,'aggregation':'top5','model':'DINOv2-L'}


class ClientTests(unittest.TestCase):
    def test_network_failures_are_distinguished_without_retry(self):
        cases = [
            (socket.gaierror(8, 'nodename nor servname provided, or not known'), 'DNS resolution failed'),
            (PermissionError(13, 'denied'), 'Network access was denied'),
            (ssl.SSLCertVerificationError(1, 'certificate verify failed'), 'TLS certificate verification failed'),
            (ssl.SSLError(1, 'handshake'), 'TLS negotiation failed'),
            (TimeoutError('timed out'), 'network request timed out'),
            (ConnectionRefusedError('refused'), 'refused the connection'),
            (ConnectionResetError('reset'), 'network connection failed'),
        ]
        for reason, expected in cases:
            for exc in (reason, urllib.error.URLError(reason)):
                with self.subTest(reason=type(reason).__name__, wrapped=isinstance(exc, urllib.error.URLError)):
                    with patch.object(client.urllib.request, 'build_opener') as opener:
                        opener.return_value.open.side_effect = exc
                        with self.assertRaises(client.SearchError) as error:
                            client.request_json('https://example.org', b'image', 'image/png')
                        self.assertIn(expected, str(error.exception))
                        self.assertIn('image request was not automatically retried', str(error.exception))
                        self.assertEqual(opener.return_value.open.call_count, 1)

    def test_health_error_does_not_claim_upload_or_expose_raw_reason(self):
        for reason in [socket.gaierror(8, 'private-host'), 'https://user:secret@proxy.invalid']:
            with patch.object(client.urllib.request, 'build_opener') as opener:
                opener.return_value.open.side_effect = urllib.error.URLError(reason)
                with self.assertRaises(client.SearchError) as error:
                    client.request_json('https://example.org/api/health')
                message = str(error.exception)
                self.assertNotIn('secret', message)
                self.assertNotIn('private-host', message)
                self.assertNotIn('image request was', message)
                self.assertEqual(opener.return_value.open.call_count, 1)

    def test_contents_and_size_not_extension(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'input.jpeg'
            file.write_bytes(b'\x89PNG\r\n\x1a\noriginal')
            self.assertEqual(client.read_image(file),(file.read_bytes(),'image/png'))
            file.write_bytes(b'not an image')
            with self.assertRaises(client.SearchError):client.read_image(file)
            file.write_bytes(b'x'*(client.MAX_IMAGE_BYTES+1))
            with self.assertRaises(client.SearchError):client.read_image(file)

    def test_url_validation(self):
        self.assertEqual(client.server_url('https://example.org/'),'https://example.org')
        self.assertEqual(client.server_url('http://127.0.0.1:8000'),'http://127.0.0.1:8000')
        for url in ['http://example.org','https://user:pass@example.org','https://example.org/api','https://example.org?a=1','https://example.org#x','file:///tmp/x']:
            with self.subTest(url=url),self.assertRaises(client.SearchError):client.server_url(url)

    def test_invalid_rankings_rejected(self):
        for change in ['duplicate','rank','nan','infinity','increasing','count','bool','aggregation']:
            p=payload()
            if change=='duplicate':p['results'][1]['pdb_id']=p['results'][0]['pdb_id']
            if change=='rank':p['results'][0]['rank']=0
            if change=='nan':p['results'][0]['score']=math.nan
            if change=='infinity':p['results'][0]['score']=math.inf
            if change=='increasing':p['results'][1]['score']=1.0
            if change=='count':p['results'].pop()
            if change=='bool':p['results'][0]['score']=True
            if change=='aggregation':p['aggregation']='max'
            with self.subTest(change=change),self.assertRaises(client.SearchError):client.validate_results(p)

    def test_metadata_failure_preserves_rankings_and_upload_bytes(self):
        raw=b'\x89PNG\r\n\x1a\noriginal pixels'
        with patch.object(client,'read_image',return_value=(raw,'image/png')), patch.object(client,'request_json',side_effect=[payload(),client.SearchError('unavailable')]) as request:
            result=client.search('chosen.png','https://example.org')
        self.assertEqual(len(result['results']),20)
        self.assertEqual(result['results'][0]['pdb_id'],'1000')
        self.assertEqual(request.call_args_list[0].args,('https://example.org/api/search',raw,'image/png'))
        self.assertEqual(len(result['warnings']),1)
        table=client.markdown(result)
        self.assertEqual(sum(line.startswith('| ') for line in table.splitlines()),21)

    def test_table_escapes_untrusted_metadata(self):
        result=payload();result['results']=client.validate_results(result);result['warnings']=[];result['score_note']='Not probability.'
        result['results'][0].update(title='<script>bad</script> | [link](javascript:x)\nnext',organisms=['*bold*'])
        table=client.markdown(result)
        self.assertNotIn('<script>',table);self.assertIn('&#124;',table);self.assertIn('\\[link\\]',table)
        self.assertIn('[1000](https://www.rcsb.org/structure/1000)',table)

    def test_redirects_never_forward_upload(self):
        request=urllib.request.Request('https://example.org/api/search',data=b'private')
        self.assertIsNone(client.NoRedirect().redirect_request(request,None,307,'redirect',{},'https://other.org'))
        with patch.object(client.urllib.request,'build_opener') as opener:
            opener.return_value.open.side_effect=urllib.error.HTTPError(request.full_url,307,'redirect',{},None)
            with self.assertRaisesRegex(client.SearchError,'No redirect was followed'):
                client.request_json(request.full_url,b'private','image/png')
            self.assertEqual(opener.return_value.open.call_count,1)

    def test_http_error_no_post_retry(self):
        with patch.object(client.urllib.request,'build_opener') as opener:
            opener.return_value.open.side_effect=urllib.error.HTTPError('https://example.org',429,'busy',{},None)
            with self.assertRaisesRegex(client.SearchError,'busy'):client.request_json('https://example.org',b'bytes','image/png')
            self.assertEqual(opener.return_value.open.call_count,1)


if __name__ == '__main__':unittest.main()
