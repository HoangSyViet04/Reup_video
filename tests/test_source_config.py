"""Source configuration must drive every request and not depend on the shell cwd."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('configured_pipeline', PROJECT / 'scripts/download_nguonc.py')
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


class SourceConfigTests(unittest.TestCase):
    def test_reads_relative_to_project_and_accepts_bom_trailing_slash(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'config.json').write_text(json.dumps({'site_url': ' https://new-domain.example/ '}), encoding='utf-8-sig')
            with mock.patch.object(pipeline, 'ROOT', root):
                self.assertEqual(pipeline.load_site_origin(), 'https://new-domain.example')

    def test_missing_malformed_or_non_origin_config_reports_clear_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            with self.assertRaisesRegex(RuntimeError, 'Cannot read source config'):
                pipeline.load_site_origin(path)
            for data in ('{bad json', '[]', '{}', '{"site_url": 123}'):
                path.write_text(data)
                with self.subTest(data=data), self.assertRaises(RuntimeError):
                    pipeline.load_site_origin(path)
            for url in ('http://example.com', 'https://example.com/xem/film', 'https://example.com?token=abc',
                        'https://user:password@example.com', 'https://example.com/#video',
                        'https://example.com:invalid', 'https://exa mple.com', 'https://'):
                path.write_text(json.dumps({'site_url': url}))
                with self.subTest(url=url), self.assertRaisesRegex(RuntimeError, 'Invalid site_url'):
                    pipeline.load_site_origin(path)

    def test_changing_config_updates_api_and_all_referrers_without_code_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / 'config.json'
            embed = 'https://player.example/embed33'
            playlist = 'https://media.example/index.m3u8'
            manifest = '#EXTM3U\n#EXTINF:4.0,\n0.ts\n#EXTINF:4.0,\n1.ts\n#EXT-X-ENDLIST\n'
            for site in ('https://first-domain.example', 'https://next-domain.example'):
                with self.subTest(site=site):
                    config.write_text(json.dumps({'site_url': site}))
                    channels = {'nguoncEpisodes': [{'server_name': 'L\u1ed3ng Ti\u1ebfng #1',
                                'server_data': [{'name': '33', 'link_embed': embed}]}]}
                    session = mock.Mock()
                    session.get.side_effect = [
                        SimpleNamespace(text='<script id="stream-bootstrap">' + json.dumps({'api': embed}) + '</script>',
                                        raise_for_status=lambda: None),
                        SimpleNamespace(text=manifest, raise_for_status=lambda: None)]
                    session.post.return_value = SimpleNamespace(
                        json=lambda: {'preissued': {'playlist': playlist}}, raise_for_status=lambda: None)
                    curl = SimpleNamespace(requests=SimpleNamespace(Session=mock.Mock(return_value=session)))
                    with mock.patch.object(pipeline, 'ROOT', root), \
                         mock.patch.dict('sys.modules', {'curl_cffi': curl}), \
                         mock.patch.object(pipeline.subprocess, 'run', return_value=SimpleNamespace(
                             stdout=json.dumps(channels).encode())) as run:
                        metadata = pipeline.fetch_episode(33)
                    command = run.call_args.args[0]
                    self.assertTrue(command[-1].startswith(site + '/api/backup-servers?'))
                    self.assertEqual(command[command.index('-e') + 1], site + '/')
                    self.assertEqual(session.get.call_args_list[0].kwargs['headers']['Referer'], site + '/')
                    payload = session.post.call_args.kwargs['json']
                    self.assertEqual(payload['referrer'], site + '/')
                    self.assertEqual(payload['frame_origins'], [site])
                    self.assertEqual(metadata['expected_segments'], 2)


if __name__ == '__main__':
    unittest.main()
