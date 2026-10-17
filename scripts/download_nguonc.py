"""Download Vietnamese-dub One Piece from NguonC, retaining usable segments.

python scripts/download_nguonc.py --episode 2
python scripts/download_nguonc.py --episode 2 --merge-only
Missing segments are skipped and documented by default; --strict requires all.
"""
import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.vendor'
if RUNTIME.is_dir() and sys.prefix == sys.base_prefix:
    sys.path.insert(0, str(RUNTIME))


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def fetch_episode(number):
    try:
        from curl_cffi import requests
    except ImportError as error:
        raise RuntimeError('Install dependencies: run setup.cmd (Windows) or install requirements.txt in your virtual environment') from error
    params = {'origin_name': 'One Piece', 'slug': 'dao-hai-tac', 'year': '1999',
              'nguonc_slug': 'one-piece', 'kkphim_slug': 'dao-hai-tac',
              'vsmov_slug': 'dao-hai-tac', 'tmdb_id': '37854',
              'tmdb_type': 'tv', 'tmdb_season': '1'}
    result = subprocess.run(['curl.exe', '-f', '-sS', '-L', '--max-time', '45',
                             '-A', 'Mozilla/5.0', '-e', 'https://tramphim.tech/',
                             'https://tramphim.tech/api/backup-servers?' + urlencode(params)],
                            check=True, capture_output=True)
    channels = json.loads(result.stdout).get('nguoncEpisodes', [])
    dub = 'l\u1ed3ng ti\u1ebfng'
    channel = next((c for c in channels if dub in c.get('server_name', '').casefold()), None)
    episode = next((e for e in (channel or {}).get('server_data', [])
                    if re.fullmatch(r'0*' + str(number), e.get('name', ''))), None)
    if not episode:
        raise RuntimeError('Episode not found on NguonC. No server fallback.')
    embed = episode['link_embed']
    origin = '{u.scheme}://{u.netloc}'.format(u=urlsplit(embed))
    session = requests.Session(impersonate='chrome131')
    page = session.get(embed, headers={'Referer': 'https://tramphim.tech/'}, timeout=25)
    page.raise_for_status()
    found = re.search(r'<script id="stream-bootstrap"[^>]*>(.*?)</script>', page.text, re.S)
    if not found or json.loads(found.group(1)).get('api') != embed:
        raise RuntimeError('Public player bootstrap unavailable or unexpected.')
    response = session.post(embed, headers={'Referer': embed, 'Origin': origin}, timeout=25,
                            json={'action': 'bootstrap', 'referrer': 'https://tramphim.tech/',
                                  'frame_origins': ['https://tramphim.tech'], 'request_grant': True,
                                  'playlist_format': 'hls', 'pretty_url': True, 'path_chunks': True,
                                  'bootstrap_format': 'json'})
    response.raise_for_status()
    grant = response.json().get('preissued') or {}
    playlist_url = grant.get('playlist')
    if not playlist_url:
        raise RuntimeError('No public HLS grant issued; verification may be required.')
    manifest = session.get(playlist_url, headers={'Referer': embed}, timeout=25)
    manifest.raise_for_status()
    text = manifest.text
    if not text.startswith('#EXTM3U') or '#EXT-X-ENDLIST' not in text:
        raise RuntimeError('Expected a complete HLS media playlist.')
    if any('METHOD=NONE' not in line for line in text.splitlines() if line.startswith('#EXT-X-KEY')):
        raise RuntimeError('Encrypted media is not supported.')
    if any(tag in text for tag in ['#EXT-X-MAP', '#EXT-X-BYTERANGE', '#EXT-X-STREAM-INF']):
        raise RuntimeError('Only plain MPEG-TS media playlists are supported.')
    urls = [urljoin(playlist_url, line.strip()) for line in text.splitlines()
            if line.strip() and not line.startswith('#')]
    durations = [float(n) for n in re.findall(r'#EXTINF:([0-9.]+)', text)]
    if not urls or len(urls) != len(durations):
        raise RuntimeError('Playlist duration/segment mismatch.')
    return {'source': 'NguonC', 'server': channel['server_name'], 'episode': number,
            'source_embed': embed, 'urls': urls, 'durations': durations,
            'expected_segments': len(urls), 'playlist_sha256': hashlib.sha256(text.encode()).hexdigest()}


def segment_plan(metadata, skip_intro=0):
    durations = metadata.get('durations', [])
    count = metadata.get('expected_segments', len(durations))
    if skip_intro and (len(durations) != count or not durations):
        raise RuntimeError('Exact intro trimming requires cached playlist metadata. Run without --merge-only once.')
    if durations and any(not math.isfinite(d) or d <= 0 for d in durations):
        raise RuntimeError('Invalid segment durations in playlist.')
    starts, position = [], 0.0
    for duration in durations:
        starts.append(position)
        position += duration
    if skip_intro and skip_intro >= position:
        raise RuntimeError('Intro cut is longer than the episode.')
    selected = [i for i in range(count) if not durations or starts[i] + durations[i] > skip_intro + 1e-8]
    excluded = sorted(set(range(count)) - set(selected))
    return selected, excluded, starts


def choose_encoder(requested):
    if requested != 'auto':
        return requested
    check = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                            '-i', 'color=size=320x240:rate=1', '-frames:v', '1',
                            '-c:v', 'h264_nvenc', '-f', 'null', '-'], capture_output=True)
    return 'h264_nvenc' if check.returncode == 0 else 'libx264'


def output_path(outdir, episode, skip_intro, logo, speed=1.0, layout='original'):
    suffix = '-ready' if skip_intro or logo or speed != 1 else ''
    if speed != 1:
        suffix += f'-{speed:g}x'
    if layout == 'portrait':
        suffix += '-9x16'
    return outdir / f'one-piece-ep-{episode:03d}-vi-nguonc{suffix}.mp4'


def processing_profile(skip_intro, logo, speed=1.0, layout='original'):
    return {**({'layout': 'portrait', 'canvas': [1080, 1920], 'background': 'blur'} if layout == 'portrait' else {}),
            'version': 5 if layout == 'portrait' else 4, 'skip_intro_seconds': skip_intro, 'speed': speed,
            'logo_sha256': hashlib.sha256(Path(logo).read_bytes()).hexdigest() if logo else None,
            'logo_position': 'top-right' if logo else None,
            'logo_width_ratio': 0.18 if logo else None,
            'logo_opacity': 0.85 if logo else None}


def run_encoder(command, expected_duration):
    command = command[:1] + ['-progress', 'pipe:1', '-nostats', '-stats_period', '2'] + command[1:]
    last_percent = -5
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True, encoding='utf-8', errors='replace') as process:
        for line in process.stdout:
            if line.startswith('out_time_us=') and expected_duration:
                try:
                    seconds = max(0, int(line.strip().split('=', 1)[1]) / 1_000_000)
                except ValueError:
                    continue
                percent = min(100, int(seconds * 100 / expected_duration))
                if percent >= last_percent + 5:
                    print(f'Export {percent}% ({seconds:.0f}/{expected_duration:.0f}s)', flush=True)
                    last_percent = percent
        code = process.wait()
        if code:
            raise subprocess.CalledProcessError(code, command)


def download_segments(parts, metadata, workers, indices=None):
    from curl_cffi import requests
    local = threading.local()
    rate_limited = threading.Event()

    def download(index, url):
        path = parts / f'{index:05d}.ts'
        if path.exists() and path.stat().st_size > 188:
            return
        if rate_limited.is_set():
            raise RuntimeError('Download paused after server rate limit; rerun later.')
        if not hasattr(local, 'session'):
            local.session = requests.Session(impersonate='chrome131')
        for attempt in range(3):
            try:
                r = local.session.get(url, headers={'Referer': metadata['source_embed']}, timeout=30)
                if r.status_code in (401, 403, 429, 503):
                    if r.status_code in (429, 503):
                        rate_limited.set()
                    raise PermissionError(f'HTTP {r.status_code}; segment unavailable')
                r.raise_for_status()
                if len(r.content) <= 188 or r.content.lstrip().startswith((b'<!DOCTYPE', b'<html')):
                    raise ValueError('Non-media response')
                temporary = path.with_suffix('.part')
                temporary.write_bytes(r.content)
                temporary.replace(path)
                return
            except PermissionError:
                raise
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)

    failures = []
    completed = 0
    indices = list(range(len(metadata['urls']))) if indices is None else list(indices)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download, index, metadata['urls'][index]): index for index in indices}
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            try:
                future.result()
                completed += 1
            except Exception as error:
                failures.append({'index': index, 'error': str(error)})
                print(f'WARNING: segment {index} unavailable: {error}', flush=True)
            if completed and completed % 25 == 0:
                print(f'Available {completed}/{len(futures)} segments', flush=True)
    write_json(parts / 'failures.json', {'source': 'NguonC', 'episode': metadata['episode'],
               'expected_segments': len(metadata['urls']), 'requested_segments': indices,
               'downloaded_segments': completed,
               'failures': sorted(failures, key=lambda f: f['index'])})


def merge_episode(parts, outdir, episode, metadata=None, strict=False,
                  skip_intro=0, logo=None, encoder='libx264', speed=1.0, layout='original'):
    if layout not in ('original', 'portrait'):
        raise RuntimeError('Layout must be original or portrait.')
    if not math.isfinite(speed) or not 0.5 <= speed <= 2:
        raise RuntimeError('Speed must be finite and between 0.5 and 2.')
    metadata = metadata or read_json(parts / 'metadata.json')
    previous = read_json(parts / 'failures.json')
    actual = {int(p.stem): p for p in parts.glob('*.ts')
              if re.fullmatch(r'\d{5}', p.stem) and p.stat().st_size > 188}
    if not actual:
        raise RuntimeError('No usable cached video segments found.')
    expected_count = metadata.get('expected_segments') or previous.get('expected_segments') or (max(actual) + 1)
    metadata = dict(metadata, expected_segments=expected_count)
    selected, excluded, starts = segment_plan(metadata, skip_intro)
    available = sorted(set(selected) & set(actual))
    missing = sorted(set(selected) - set(available))
    if not available:
        raise RuntimeError('No usable segments within the expected range.')
    if strict and missing:
        raise RuntimeError(f'Strict mode: {len(missing)} missing segments; no MP4 created.')
    durations = metadata.get('durations', [])
    known_durations = len(durations) == expected_count
    if logo is not None:
        logo = Path(logo).resolve()
        if not logo.is_file():
            raise RuntimeError(f'Logo not found: {logo}')
    output = output_path(outdir, episode, skip_intro, logo, speed, layout)
    if output.exists():
        raise RuntimeError(f'Output already exists; not overwriting: {output}')
    outdir.mkdir(parents=True, exist_ok=True)
    work = parts / 'merge-work' / uuid.uuid4().hex
    work.mkdir(parents=True)
    runs = []
    for index in available:
        if not runs or index != runs[-1][-1] + 1:
            runs.append([])
        runs[-1].append(index)
    concat_lines = []
    for number, indices in enumerate(runs):
        run = work / f'run-{number:03d}.ts'
        with run.open('wb') as dest:
            for index in indices:
                with actual[index].open('rb') as src:
                    shutil.copyfileobj(src, dest, 1024 * 1024)
        quoted = run.resolve().as_posix().replace("'", "'\\''")
        concat_lines.append(f"file '{quoted}'")
    concat_file = work / 'inputs.txt'
    concat_file.write_text('\n'.join(concat_lines) + '\n', encoding='utf-8')
    staged = outdir / f'{output.stem}.{uuid.uuid4().hex}.working.mp4'
    residual_trim = max(0.0, skip_intro - starts[available[0]]) if known_durations else 0.0
    print(f'Merging {len(available)}/{len(selected)} requested segments; intro excluded: {len(excluded)}; missing: {missing}', flush=True)
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-n', '-f', 'concat', '-safe', '0', '-i', str(concat_file)]
    needs_encode = bool(residual_trim or logo or speed != 1 or layout == 'portrait')
    used_encoder = 'copy'
    video_rate = None
    expected_output_duration = (sum(durations[i] for i in available) - residual_trim) / speed if known_durations else None
    if needs_encode:
        used_encoder = choose_encoder(encoder)
        source_probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                                       '-show_entries', 'stream=width,height:format=bit_rate,duration',
                                       '-of', 'json', str(work / 'run-000.ts')],
                                      check=True, capture_output=True)
        source_info = json.loads(source_probe.stdout)
        source_duration = float(source_info['format']['duration'])
        source_bps = int(source_info['format'].get('bit_rate') or (work / 'run-000.ts').stat().st_size * 8 / source_duration)
        cap = max(650_000, min(12_000_000, int(source_bps * 0.90)))
        target_bps = min(cap, max(500_000, int(source_bps * 0.70)))
        video_rate = {'source_container_bps': source_bps, 'target_bps': target_bps, 'max_bps': cap}
        print(f'Processing: intro={skip_intro}s, intra-segment trim={residual_trim:.6f}s, encoder={used_encoder}, speed={speed:g}x, layout={layout}, logo={logo}', flush=True)
        print(f'Video bitrate: target {target_bps/1e6:.2f} Mb/s, cap {cap/1e6:.2f} Mb/s', flush=True)
        filters = [f'[0:v]trim=start={residual_trim:.9f},setpts=(PTS-STARTPTS)/{speed:.12g}[base]',
                   f'[0:a]atrim=start={residual_trim:.9f},asetpts=PTS-STARTPTS,atempo={speed:.12g}[a]']
        if logo:
            dimensions = source_info['streams'][0]
            logo_width = max(32, round(dimensions['width'] * 0.18 / 2) * 2)
            margin = max(8, round(min(dimensions['width'], dimensions['height']) * 0.025))
            command += ['-loop', '1', '-framerate', '1', '-i', str(logo)]
            filters += [f'[1:v]scale={logo_width}:-2,format=rgba,colorchannelmixer=aa=0.85[wm]',
                        f'[base][wm]overlay=x=main_w-overlay_w-{margin}:y={margin}:shortest=1,format=yuv420p[v]']
        else:
            filters += ['[base]format=yuv420p[v]']
        if layout == 'portrait':
            # Overlay the logo onto the scene before fitting the full scene to a portrait canvas.
            filters = [f.replace('[v]', '[scene]') for f in filters]
            filters += [
                '[scene]split=2[bgsrc][fgsrc]',
                '[bgsrc]scale=270:480:force_original_aspect_ratio=increase:force_divisible_by=2,'
                'crop=270:480,setsar=1,gblur=sigma=10,eq=brightness=-0.12,scale=1080:1920[bg]',
                '[fgsrc]scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1[fg]',
                '[bg][fg]overlay=x=(main_w-overlay_w)/2:y=(main_h-overlay_h)/2:shortest=1,format=yuv420p[v]']
        command += ['-filter_complex', ';'.join(filters), '-map', '[v]', '-map', '[a]', '-c:v', used_encoder]
        if used_encoder == 'h264_nvenc':
            command += ['-preset', 'p5', '-tune', 'hq', '-rc', 'vbr', '-cq', '22',
                        '-b:v', str(target_bps), '-spatial-aq', '1', '-aq-strength', '8']
        else:
            command += ['-preset', 'veryfast', '-crf', '20']
        command += ['-maxrate', str(cap), '-bufsize', str(cap * 2),
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-ar', '48000', '-shortest']
    else:
        command += ['-map', '0:v:0', '-map', '0:a:0', '-c', 'copy']
    command += ['-movflags', '+faststart', str(staged)]
    run_encoder(command, expected_output_duration)
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                            'format=duration,size:stream=codec_type,codec_name,width,height,sample_rate,channels',
                            '-of', 'json', str(staged)], capture_output=True, check=True)
    technical = json.loads(probe.stdout)
    types = {s.get('codec_type') for s in technical.get('streams', [])}
    if not {'video', 'audio'}.issubset(types):
        raise RuntimeError('Output must contain both video and audio.')
    duration = float(technical['format']['duration'])
    retained = sum(durations[i] for i in available) - residual_trim if known_durations else None
    if duration <= 0 or (retained is not None and abs(duration - retained / speed) > max(2, len(runs) * 0.5)):
        raise RuntimeError('Unexpected output duration; unverified file remains marked working.')
    report = {'source': 'NguonC', 'server': metadata.get('server', 'Long Tieng #1 (NC)'),
              'episode': episode, 'complete': not missing, 'expected_segments': expected_count,
              'requested_segments': len(selected), 'merged_segments': len(available), 'missing_segments': missing,
              'intro_skipped_segments': excluded,
              'source_missing_segments': sorted(set(range(expected_count)) - set(actual)),
              'missing_duration_seconds': round(sum(max(0, starts[i] + durations[i] - max(starts[i], skip_intro)) for i in missing), 3) if known_durations else None,
              'processing': processing_profile(skip_intro, logo, speed, layout), 'encoder': used_encoder, 'video_bitrate': video_rate,
              'expected_output_duration_seconds': round(expected_output_duration, 3) if expected_output_duration is not None else None,
              'retained_expected_duration_seconds': round(retained, 3) if retained is not None else None,
              'probe': technical, 'saved': str(output.resolve())}
    if output.exists():
        raise RuntimeError('Output appeared during merge; refusing to overwrite.')
    staged.rename(output)
    write_json(output.with_suffix('.report.json'), report)
    write_json(parts / 'merge-report.json', report)
    print(json.dumps(report, ensure_ascii=True), flush=True)
    return output, report


def create_episode_cover(episode, source, outdir, font_path=None):
    """Compose a numbered portrait cover locally; keep the source image intact."""
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
    except ImportError as error:
        raise RuntimeError('Cover generation requires Pillow: run setup.cmd (Windows) or install requirements.txt in your virtual environment') from error
    if episode < 1:
        raise RuntimeError('Cover episode must be positive.')
    source, outdir = Path(source), Path(outdir)
    if not source.is_file():
        raise RuntimeError(f'Cover source not found: {source}')
    candidates = ([Path(font_path)] if font_path else [
        ROOT / 'assets/fonts/DejaVuSans-Bold.ttf',
        Path('C:/Windows/Fonts/arialbd.ttf'),
        Path('C:/Windows/Fonts/segoeuib.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')])
    chosen_font = next((p for p in candidates if p.is_file()), None)
    if chosen_font is None:
        raise RuntimeError('No suitable cover font found; provide --cover-font PATH.')
    try:
        with Image.open(source) as original:
            art = ImageOps.exif_transpose(original).convert('RGB')
        canvas = ImageOps.fit(art, (1080, 1920), method=Image.Resampling.LANCZOS)
        canvas = canvas.filter(ImageFilter.GaussianBlur(38))
        canvas = Image.blend(canvas, Image.new('RGB', canvas.size, '#102033'), 0.55)
        # Portrait sources occupy the full cover; landscape sources retain the centered panel.
        portrait_art = art.height > art.width
        panel = ImageOps.contain(art, (1080, 1920 if portrait_art else 900), method=Image.Resampling.LANCZOS)
        panel_y = (1920 - panel.height) // 2 if portrait_art else 850 - panel.height // 2
        canvas.paste(panel, ((1080 - panel.width) // 2, panel_y))
        draw = ImageDraw.Draw(canvas)
        label = f'TẬP {episode:02d}'
        size = 72
        font = ImageFont.truetype(str(chosen_font), size)
        while draw.textbbox((0, 0), label, font=font)[2] > 780:
            size -= 2
            font = ImageFont.truetype(str(chosen_font), size)
        box = draw.textbbox((0, 0), label, font=font)
        width, height = box[2] - box[0], box[3] - box[1]
        center_y = 1498 if portrait_art else max(1260, panel_y + panel.height + 75)
        left, top = (1080 - width) // 2 - 30, center_y - height // 2 - 18
        draw.rounded_rectangle((left, top, left + width + 60, top + height + 36),
                               radius=20, fill='#080B10', outline='#6A7684', width=2)
        draw.text(((1080 - width) / 2 - box[0], center_y - height / 2 - box[1]),
                  label, font=font, fill='white')
        outdir.mkdir(parents=True, exist_ok=True)
        output = outdir / f'one-piece-ep-{episode:03d}-cover.jpg'
        if output.resolve() == source.resolve():
            raise RuntimeError('Cover output must differ from the original artwork.')
        staged = outdir / f'.{output.stem}.{uuid.uuid4().hex}.tmp'
        try:
            canvas.save(staged, format='JPEG', quality=95, subsampling=0)
            staged.replace(output)
        finally:
            staged.unlink(missing_ok=True)
    except OSError as error:
        raise RuntimeError(f'Cannot create cover: {error}') from error
    print(f'Cover saved: {output.resolve()}', flush=True)
    return output


def episode_output_dir(episode):
    return ROOT / 'output/videos' / f'tap-{episode:03d}'


def collect_legacy_outputs(episode, destination):
    """Move completed files from the former flat layout without overwriting."""
    candidates = list((ROOT / 'output/videos').glob(f'one-piece-ep-{episode:03d}-vi-nguonc*.mp4'))
    candidates = [p for p in candidates if not p.name.endswith('.working.mp4')]
    cover = ROOT / 'output/covers' / f'one-piece-ep-{episode:03d}-cover.jpg'
    if cover.is_file():
        candidates.append(cover)
    for old in candidates:
        target = destination / old.name
        old_report = old.with_suffix('.report.json') if old.suffix == '.mp4' else None
        if target.exists() or (old_report and old_report.exists() and target.with_suffix('.report.json').exists()):
            print(f'WARNING: legacy output kept because destination already exists: {old}', flush=True)
            continue
        destination.mkdir(parents=True, exist_ok=True)
        old.rename(target)
        if old_report and old_report.exists():
            report = read_json(old_report)
            report['saved'] = str(target.resolve())
            write_json(old_report, report)
            old_report.rename(target.with_suffix('.report.json'))
        print(f'Collected existing output: {target}', flush=True)


def open_output_folder(folder):
    """Explorer failure must not turn a successful export into a failed job."""
    if os.name != 'nt':
        print(f'Output folder: {folder.resolve()}', flush=True)
        return
    try:
        os.startfile(str(folder.resolve()))
    except OSError as error:
        print(f'WARNING: cannot open output folder: {error}. Folder: {folder.resolve()}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--episode', type=int, default=1)
    parser.add_argument('--no-open', action='store_true', help='Do not open the episode output folder on completion')
    parser.add_argument('--cover-only', action='store_true', help='Create the numbered cover only; no network or video processing')
    parser.add_argument('--cover-image', type=Path, default=ROOT / 'assets/fanpage/bia_new.jpg')
    parser.add_argument('--cover-font', type=Path, help='Optional bold font supporting Vietnamese')
    parser.add_argument('--no-cover', action='store_true', help='Skip automatic episode cover')
    parser.add_argument('--merge-only', action='store_true', help='Merge cached segments without any network requests')
    parser.add_argument('--strict', action='store_true', help='Require every segment; default skips unavailable segments')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--skip-intro', type=float, default=105, help='Cut this many seconds from original episode; default 105')
    parser.add_argument('--speed', type=float, default=1.15, help='Playback speed, 0.5 to 2; default 1.15; preserves audio pitch')
    parser.add_argument('--logo', type=Path, default=ROOT / 'assets/fanpage/tiem-phim-gio-com-watermark.png')
    parser.add_argument('--no-logo', action='store_true', help='Disable watermark')
    parser.add_argument('--layout', choices=['portrait', 'original'], default='portrait',
                        help='Default: portrait 1080x1920 with full scene centered over blurred background')
    parser.add_argument('--encoder', choices=['auto', 'libx264', 'h264_nvenc'], default='auto')
    args = parser.parse_args()
    if args.episode < 1 or not 1 <= args.workers <= 8:
        parser.error('Episode must be positive and workers must be between 1 and 8.')
    if not math.isfinite(args.skip_intro) or args.skip_intro < 0:
        parser.error('--skip-intro must be finite and nonnegative.')
    if not math.isfinite(args.speed) or not 0.5 <= args.speed <= 2:
        parser.error('--speed must be finite and between 0.5 and 2.')
    outdir = episode_output_dir(args.episode)
    collect_legacy_outputs(args.episode, outdir)

    def finish():
        if not args.no_open:
            open_output_folder(outdir)

    def export_cover():
        return create_episode_cover(args.episode, args.cover_image, outdir, args.cover_font)

    if args.cover_only:
        if args.no_cover:
            parser.error('--cover-only cannot be combined with --no-cover.')
        export_cover()
        finish()
        return
    logo = None if args.no_logo else args.logo.resolve()
    if logo and not logo.is_file():
        raise RuntimeError(f'Logo not found: {logo}')
    for tool in ['ffmpeg', 'ffprobe'] + ([] if args.merge_only else ['curl.exe']):
        if not shutil.which(tool):
            raise RuntimeError(f'Missing dependency on PATH: {tool}')
    parts = ROOT / 'cache' / 'nguonc' / f'nc-ep-{args.episode:03d}-parts'
    existing = output_path(outdir, args.episode, args.skip_intro, logo, args.speed, args.layout)
    if existing.exists():
        report = read_json(existing.with_suffix('.report.json'))
        if report.get('processing') != processing_profile(args.skip_intro, logo, args.speed, args.layout):
            raise RuntimeError('Existing output has different processing settings; move it aside before rerunning.')
        print(f'Already exists: {existing}', flush=True)
        if report.get('missing_segments'):
            print(f"WARNING: existing video omits segments {report['missing_segments']}", flush=True)
            if args.strict:
                raise RuntimeError('Existing video is incomplete; strict mode requires every segment.')
        if not args.no_cover:
            export_cover()
        finish()
        return
    metadata = read_json(parts / 'metadata.json')
    if not args.merge_only:
        fresh = fetch_episode(args.episode)
        if metadata and (metadata.get('source_embed') != fresh.get('source_embed') or metadata.get('durations') != fresh.get('durations')):
            raise RuntimeError('Source layout changed; refusing to mix cached segments with a different video.')
        metadata = fresh
        selected, excluded, _ = segment_plan(metadata, args.skip_intro)
        parts.mkdir(parents=True, exist_ok=True)
        write_json(parts / 'metadata.json', metadata)
        print(json.dumps({'source': 'NguonC', 'episode': args.episode,
                          'segments_to_download': len(selected), 'intro_segments_not_requested': len(excluded),
                          'skip_intro_seconds': args.skip_intro, 'skip_missing': not args.strict}), flush=True)
        download_segments(parts, metadata, args.workers, selected)
    merge_episode(parts, outdir, args.episode, metadata, args.strict, args.skip_intro, logo, args.encoder, args.speed, args.layout)
    if not args.no_cover:
        export_cover()
    finish()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'ERROR: {error}') from error
