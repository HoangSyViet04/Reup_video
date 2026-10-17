"""Offline integration checks using synthetic HLS video and audio."""
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('nguonc', PROJECT / 'scripts/download_nguonc.py')
nguonc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nguonc)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg is required')
class MergeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = PROJECT / '.test-work'
        base.mkdir(exist_ok=True)
        cls.root = Path(tempfile.mkdtemp(prefix='merge-', dir=base))
        cls.fixture = cls.root / 'fixture'
        cls.fixture.mkdir()
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error',
                        '-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=12',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100',
                        '-t', '8', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-g', '24',
                        '-sc_threshold', '0', '-c:a', 'aac', '-f', 'hls', '-hls_time', '2',
                        '-hls_playlist_type', 'vod', '-hls_segment_filename', str(cls.fixture / '%05d.ts'),
                        str(cls.fixture / 'playlist.m3u8')], check=True)
        durations = [float(n) for n in re.findall(r'#EXTINF:([0-9.]+)', (cls.fixture / 'playlist.m3u8').read_text())]
        cls.metadata = {'expected_segments': len(durations), 'durations': durations, 'server': 'Synthetic fixture'}
        assert len(durations) == 4

    def make_parts(self, name, missing):
        parts = self.root / name
        parts.mkdir()
        for i in range(4):
            if i not in missing:
                shutil.copy2(self.fixture / f'{i:05d}.ts', parts / f'{i:05d}.ts')
        return parts

    def test_complete(self):
        parts = self.make_parts('complete', [])
        output, report = nguonc.merge_episode(parts, self.root / 'complete-out', 1, self.metadata)
        self.assertTrue(output.is_file())
        self.assertTrue(report['complete'])
        self.assertAlmostEqual(float(report['probe']['format']['duration']), 8, delta=0.5)

    def test_skip_first(self):
        parts = self.make_parts('leading', [0])
        output, report = nguonc.merge_episode(parts, self.root / 'leading-out', 2, self.metadata)
        self.assertTrue(output.is_file())
        self.assertEqual(report['missing_segments'], [0])
        self.assertEqual(report['missing_duration_seconds'], 2)
        self.assertAlmostEqual(float(report['probe']['format']['duration']), 6, delta=0.5)

    def test_skip_middle_compacts_timeline(self):
        parts = self.make_parts('middle', [1])
        _, report = nguonc.merge_episode(parts, self.root / 'middle-out', 3, self.metadata)
        self.assertEqual(report['missing_segments'], [1])
        self.assertAlmostEqual(float(report['probe']['format']['duration']), 6, delta=0.5)

    def test_strict_rejects_missing(self):
        parts = self.make_parts('strict', [0])
        with self.assertRaisesRegex(RuntimeError, 'Strict mode'):
            nguonc.merge_episode(parts, self.root / 'strict-out', 4, self.metadata, strict=True)
        self.assertFalse((self.root / 'strict-out').exists())

    def test_old_cache_can_merge_without_network_metadata(self):
        parts = self.make_parts('legacy', [0])
        (parts / 'failures.json').write_text(json.dumps({'expected_segments': 4}))
        _, report = nguonc.merge_episode(parts, self.root / 'legacy-out', 5)
        self.assertEqual(report['missing_segments'], [0])
        self.assertIsNone(report['missing_duration_seconds'])

    def test_no_segments_fails(self):
        parts = self.make_parts('empty', [0, 1, 2, 3])
        with self.assertRaisesRegex(RuntimeError, 'No usable'):
            nguonc.merge_episode(parts, self.root / 'empty-out', 6, self.metadata)

    def test_intro_not_downloaded(self):
        parts = self.make_parts('download-optimized', [0, 1, 2, 3])
        metadata = dict(self.metadata, episode=7, source_embed='https://example.test/embed',
                        urls=[f'https://example.test/{i}' for i in range(4)])
        selected, excluded, _ = nguonc.segment_plan(metadata, 3.1)
        calls = []
        fixture = self.fixture

        class Session:
            def __init__(self, **kwargs):
                pass

            def get(self, url, **kwargs):
                index = int(url.rsplit('/', 1)[-1])
                if index == 0:
                    raise AssertionError('Intro segment must never be requested')
                calls.append(index)
                return SimpleNamespace(status_code=200, content=(fixture / f'{index:05d}.ts').read_bytes(),
                                       raise_for_status=lambda: None)

        with mock.patch.dict('sys.modules', {'curl_cffi': SimpleNamespace(requests=SimpleNamespace(Session=Session))}):
            nguonc.download_segments(parts, metadata, 1, selected)
        self.assertEqual(excluded, [0])
        self.assertEqual(sorted(calls), [1, 2, 3])
        self.assertFalse((parts / '00000.ts').exists())

    def test_exact_intro_and_visible_top_right_logo(self):
        parts = self.make_parts('processed', [0])
        logo = self.root / 'red-logo.png'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                        '-i', 'color=c=red:s=32x16:rate=1', '-frames:v', '1', str(logo)], check=True)
        output, report = nguonc.merge_episode(parts, self.root / 'processed-out', 8, self.metadata,
                                              strict=True, skip_intro=3.1, logo=logo, encoder='libx264')
        self.assertTrue(report['complete'])
        self.assertEqual(report['intro_skipped_segments'], [0])
        self.assertEqual(report['missing_segments'], [])
        self.assertEqual(report['source_missing_segments'], [0])
        self.assertAlmostEqual(float(report['probe']['format']['duration']), 4.9, delta=0.3)
        self.assertEqual(report['processing']['logo_position'], 'top-right')
        pixel = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-ss', '0.5',
                                '-i', str(output), '-vf', 'crop=2:2:270:16,format=rgb24',
                                '-frames:v', '1', '-f', 'rawvideo', '-'], capture_output=True, check=True).stdout
        self.assertGreater(pixel[0], 180)
        self.assertLess(pixel[1], 100)
        self.assertLess(pixel[2], 100)

    def test_speed_with_trim_and_logo(self):
        parts = self.make_parts('speed', [])
        logo = self.root / 'speed-logo.png'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                        '-i', 'color=c=red:s=32x16:rate=1', '-frames:v', '1', str(logo)], check=True)
        output, report = nguonc.merge_episode(parts, self.root / 'speed-out', 9, self.metadata,
                                              skip_intro=1.1, logo=logo, speed=1.15)
        self.assertIn('-1.15x.mp4', output.name)
        self.assertEqual(report['processing']['speed'], 1.15)
        self.assertAlmostEqual(float(report['probe']['format']['duration']), 6.9 / 1.15, delta=0.25)
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,duration',
                                '-of', 'json', str(output)], check=True, capture_output=True)
        durations = [float(s['duration']) for s in json.loads(probe.stdout)['streams']]
        self.assertLess(max(durations) - min(durations), 0.25)
        # The original 440 Hz tone must retain its pitch after tempo adjustment.
        audio = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(output), '-ss', '1', '-t', '2',
                                '-vn', '-ac', '1', '-ar', '8000', '-f', 's16le', '-'],
                               check=True, capture_output=True).stdout
        import array
        samples = array.array('h', audio)
        crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
        self.assertAlmostEqual(crossings / (len(samples) / 8000), 440, delta=5)

    def test_invalid_speed(self):
        for speed in (0, -1, float('nan'), float('inf'), 3):
            with self.assertRaisesRegex(RuntimeError, 'Speed'):
                nguonc.merge_episode(self.fixture, self.root / 'invalid-speed', 10, speed=speed)

    def test_intro_longer_than_episode_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'longer than'):
            nguonc.segment_plan(self.metadata, 105)

    def test_intro_requires_original_durations(self):
        with self.assertRaisesRegex(RuntimeError, 'metadata'):
            nguonc.segment_plan({'expected_segments': 4}, 3.1)


if __name__ == '__main__':
    unittest.main()
