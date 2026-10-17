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
        with mock.patch.object(sys, 'argv', ['pipeline', '--episode', '12', '--cover-only']), \
             mock.patch.object(pipeline, 'create_episode_cover') as cover, \
             mock.patch.object(pipeline, 'fetch_episode', side_effect=AssertionError('network')), \
             mock.patch.object(pipeline.shutil, 'which', side_effect=AssertionError('video dependency')):
            pipeline.main()
            self.assertEqual(cover.call_args.args[0], 12)

    def test_existing_video_still_creates_cover_without_merge(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video = pipeline.output_path(root / 'output/videos', 2, 105, None, 1.15)
            video.parent.mkdir(parents=True)
            video.write_bytes(b'untouched existing video')
            video.with_suffix('.report.json').write_text(json.dumps({
                'processing': pipeline.processing_profile(105, None, 1.15)}))
            with mock.patch.object(pipeline, 'ROOT', root), \
                 mock.patch.object(sys, 'argv', ['pipeline', '--episode', '2', '--no-logo']), \
                 mock.patch.object(pipeline.shutil, 'which', return_value='available'), \
                 mock.patch.object(pipeline, 'create_episode_cover') as cover, \
                 mock.patch.object(pipeline, 'fetch_episode', side_effect=AssertionError('network')), \
                 mock.patch.object(pipeline, 'merge_episode', side_effect=AssertionError('merge')):
                pipeline.main()
                self.assertEqual(cover.call_args.args[0], 2)
                self.assertEqual(video.read_bytes(), b'untouched existing video')


if __name__ == '__main__':
    unittest.main()
