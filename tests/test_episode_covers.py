"""Offline checks for cover-only mode and already-exported episodes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cover_pipeline', PROJECT / 'scripts/download_nguonc.py')
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


class CoverTests(unittest.TestCase):
    def test_cover_preserves_source_and_renders_jpeg(self):
        from PIL import Image
        source = PROJECT / 'assets/fanpage/bia_logo.jpg'
        before = hashlib.sha256(source.read_bytes()).digest()
        with tempfile.TemporaryDirectory() as folder:
            cover = pipeline.create_episode_cover(123, source, Path(folder))
            self.assertEqual(cover.name, 'one-piece-ep-123-cover.jpg')
            with Image.open(cover) as image:
                self.assertEqual(image.size, (1080, 1920))
                self.assertEqual(image.format, 'JPEG')
                image.load()
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), before)

    def test_cover_only_skips_video_dependencies_and_network(self):
        with mock.patch.object(sys, 'argv', ['pipeline', '--episode', '12', '--cover-only', '--no-open']), \
             mock.patch.object(pipeline, 'create_episode_cover') as cover, \
             mock.patch.object(pipeline, 'fetch_episode', side_effect=AssertionError('network')), \
             mock.patch.object(pipeline.shutil, 'which', side_effect=AssertionError('video dependency')):
            pipeline.main()
            self.assertEqual(cover.call_args.args[0], 12)

    def test_existing_video_still_creates_cover_without_merge(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video = pipeline.output_path(root / 'output/videos/tap-002', 2, 105, None, 1.15)
            video.parent.mkdir(parents=True)
            video.write_bytes(b'untouched existing video')
            video.with_suffix('.report.json').write_text(json.dumps({
                'processing': pipeline.processing_profile(105, None, 1.15)}))
            with mock.patch.object(pipeline, 'ROOT', root), \
                 mock.patch.object(sys, 'argv', ['pipeline', '--episode', '2', '--no-logo', '--no-open']), \
                 mock.patch.object(pipeline.shutil, 'which', return_value='available'), \
                 mock.patch.object(pipeline, 'create_episode_cover') as cover, \
                 mock.patch.object(pipeline, 'fetch_episode', side_effect=AssertionError('network')), \
                 mock.patch.object(pipeline, 'merge_episode', side_effect=AssertionError('merge')):
                pipeline.main()
                self.assertEqual(cover.call_args.args[0], 2)
                self.assertEqual(video.read_bytes(), b'untouched existing video')


    def test_legacy_video_report_and_cover_collected_without_reencoding(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old_video = root / 'output/videos/one-piece-ep-002-vi-nguonc-ready-1.15x.mp4'
            old_cover = root / 'output/covers/one-piece-ep-002-cover.jpg'
            old_video.parent.mkdir(parents=True)
            old_cover.parent.mkdir(parents=True)
            old_video.write_bytes(b'existing video bytes')
            old_cover.write_bytes(b'existing cover bytes')
            old_video.with_suffix('.report.json').write_text(json.dumps({'saved': str(old_video)}))
            with mock.patch.object(pipeline, 'ROOT', root):
                destination = pipeline.episode_output_dir(2)
                pipeline.collect_legacy_outputs(2, destination)
                self.assertEqual((destination / old_video.name).read_bytes(), b'existing video bytes')
                self.assertEqual((destination / old_cover.name).read_bytes(), b'existing cover bytes')
                report = json.loads((destination / old_video.with_suffix('.report.json').name).read_text())
                self.assertEqual(report['saved'], str((destination / old_video.name).resolve()))
                self.assertFalse(old_video.exists())
                self.assertFalse(old_cover.exists())

    def test_no_open_flag_suppresses_folder_launch(self):
        with mock.patch.object(sys, 'argv', ['pipeline', '--episode', '12', '--cover-only', '--no-open']), \
             mock.patch.object(pipeline, 'create_episode_cover'), \
             mock.patch.object(pipeline, 'collect_legacy_outputs'), \
             mock.patch.object(pipeline, 'open_output_folder') as launch:
            pipeline.main()
            launch.assert_not_called()

    def test_opens_folder_after_cover_success_only(self):
        with mock.patch.object(sys, 'argv', ['pipeline', '--episode', '12', '--cover-only']), \
             mock.patch.object(pipeline, 'create_episode_cover') as cover, \
             mock.patch.object(pipeline, 'collect_legacy_outputs'), \
             mock.patch.object(pipeline, 'open_output_folder') as launch:
            pipeline.main()
            launch.assert_called_once_with(PROJECT / 'output/videos/tap-012')
            launch.reset_mock()
            cover.side_effect = RuntimeError('cover failed')
            with self.assertRaisesRegex(RuntimeError, 'cover failed'):
                pipeline.main()
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
