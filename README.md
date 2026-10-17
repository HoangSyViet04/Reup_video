# Reup_video

Pipeline One Piece bản lồng tiếng **NguồnC / Lồng Tiếng #1 (NC)**.

```text
scripts/          Code tải và xử lý
assets/fanpage/    Avatar, ảnh bìa, watermark PNG
output/videos/    Thư mục tap-001, tap-002... chứa MP4, bìa JPG và báo cáo
cache/nguonc/     Segment, playlist metadata, dữ liệu ghép
tests/            Kiểm tra offline bằng video giả lập
.vendor/          Thư viện Python cục bộ
archive/          Code, tài liệu và cấu trúc cũ
```

## Dùng trên máy Windows khác

Không cần giữ đường dẫn `D:\Project\Reup_video`. Code và launcher tìm thư mục theo
vị trí của chúng. Nên dùng Python 3.11 64-bit như máy đang kiểm tra.

1. Cài Git và Python, bật tùy chọn thêm Python vào PATH.
2. Cài FFmpeg có cả `ffmpeg.exe` và `ffprobe.exe`, thêm thư mục `bin` vào PATH.
   Nguồn tải: https://ffmpeg.org/download.html . Windows cần có `curl.exe` trên PATH.
3. Clone repo, mở PowerShell trong thư mục clone, chạy:

```powershell
.\setup.cmd
.\run_download.cmd --episode 3
# Hoặc chỉ tạo bìa:
.\run_download.cmd --episode 3 --cover-only
```

`setup.cmd` tạo môi trường Python riêng và cài requirements; không cần activate.
Chạy lại `setup.cmd` sau khi pull nếu có thay đổi thư viện. Kiểm tra thủ công:
`.\.venv\Scripts\python.exe -B scripts/check_environment.py`.

Không cần GPU NVIDIA: mặc định `--encoder auto` thử NVENC rồi chọn CPU nếu không dùng được.
Máy CPU sẽ xuất chậm hơn. Kết nối mạng/IP và máy chủ nguồn có thể ảnh hưởng việc tải;
kiểm tra môi trường cục bộ không đảm bảo máy chủ luôn cho tải.

Git chỉ lưu code, cấu hình, tài liệu và ảnh nguồn trong assets. `.venv`, `.vendor`,
`cache`, `output`, `.test-work`, `archive` không được đưa lên Git. Vì vậy máy mới
không có các đoạn/video đã tải và không thể `--merge-only` cho tới khi có cache.
Video/bìa tạo trên máy nào ở máy đó; muốn dùng chung phải chép hoặc đồng bộ riêng.

## Một lệnh để tải và xuất video

```powershell
cd D:\Project\Reup_video
python scripts/download_nguonc.py --episode 3
```

Mặc định:

1. Tìm đúng NguồnC / Lồng Tiếng #1.
2. Đọc thời lượng từng segment và không yêu cầu các segment nằm hoàn toàn trong
   110 giây đầu. Segment 0 sẽ không bị yêu cầu khi nó thuộc phần intro.
3. Giữ segment giao với mốc 1:50, cắt chính xác phần dư khi xuất video. Mốc cắt
   được tính trên timeline tập gốc, không trừ tiếp 110 giây từ bản đã mất intro.
4. Ghép các đoạn còn lại, bỏ qua đoạn lỗi và ghi rõ trong báo cáo.
5. Chèn watermark vào góc trên bên phải, độ rộng canvas logo 18% chiều rộng
   video, độ đậm 85%, chừa mép theo kích thước video.
6. Xuất H.264/AAC MP4 khung dọc 1080×1920, giữ đủ cảnh phim ở giữa nền mờ, đặt metadata faststart.
   Tự dùng NVENC nếu probe GPU thành công, nếu không dùng libx264.

File dùng để xem/đăng:

```text
output/videos/tap-003/one-piece-ep-003-vi-nguonc-ready-cut110s-1.15x-9x16.mp4
```

Bản chưa xử lý trước đây vẫn được giữ nguyên; pipeline mới dùng hậu tố `-ready`.
Việc chèn logo yêu cầu encode lại video. NVENC dùng CQ 22 / preset p5;
libx264 dùng CRF 20 / veryfast. Bitrate video được giới hạn theo bitrate nguồn
để tránh tăng dung lượng quá mức. Âm thanh AAC 160 kb/s, 48 kHz.
Trong lúc xuất sẽ hiển thị tiến độ theo phần trăm.

## Dùng cache, không tải segment lại

```powershell
python scripts/download_nguonc.py --episode 3 --merge-only
```

Cần `cache/nguonc/nc-ep-003-parts/metadata.json` để cắt đúng 110 giây. Nếu cache
cũ chưa có file này, chạy lệnh thường một lần: pipeline lấy playlist mới rồi
tận dụng các segment đã có, không tải lại các segment hợp lệ.

## Tùy chỉnh

```powershell
# Cắt 90 giây thay vì 105
python scripts/download_nguonc.py --episode 3 --skip-intro 90

# Chọn logo khác
python scripts/download_nguonc.py --episode 3 --logo assets/fanpage/logo.png

# Không chèn logo
python scripts/download_nguonc.py --episode 3 --no-logo

# Bắt buộc đủ tất cả segment thuộc phần nội dung sau intro
python scripts/download_nguonc.py --episode 3 --strict

# Ép encode bằng CPU
python scripts/download_nguonc.py --episode 3 --encoder libx264
```

File đã tồn tại không bị ghi đè. Nếu đổi thời gian cắt/logo, chuyển file `-ready`
và báo cáo cũ sang chỗ khác trước khi chạy lại. Chạy cùng cấu hình sẽ thông báo
file đã có. Báo cáo ghi rõ đoạn intro bỏ theo yêu cầu và đoạn nội dung tải lỗi
riêng biệt. `complete: true` nghĩa là đủ phần nội dung sau mốc cắt.

## Cài đặt và kiểm tra

Cần Python 3.10+, FFmpeg, FFprobe, curl.exe trên PATH. Máy mới dùng `setup.cmd` để tạo `.venv`; `.vendor` chỉ dành cho môi trường cũ và không đưa lên Git.

```powershell
python -m pip install -r requirements.txt --target .vendor
python -B -m unittest discover -s tests -v
```

Kiểm tra offline bao gồm cắt giữa segment, bỏ intro ngay từ danh sách tải,
watermark xuất hiện đúng góc, thiếu segment, chế độ strict và cache cũ.
Các fixture nhỏ trong `.test-work/` được giữ lại để đối chiếu.
Pipeline không tự đổi server hoặc xử lý CAPTCHA/DRM.


## Default speed: 1.15x

The CLI now exports at 1.15x by default, after cutting the original 110-second intro.
Video and audio are sped up together; audio pitch is preserved with FFmpeg atempo.
The watermark is applied in the same encode pass. Existing 1x videos remain untouched.

```powershell
python scripts/download_nguonc.py --episode 3
# Re-export cached episode 2 without downloading:
python scripts/download_nguonc.py --episode 2 --merge-only
# Override speed (range 0.5 to 2):
python scripts/download_nguonc.py --episode 3 --speed 1
```

Default output: `output/videos/tap-003/one-piece-ep-003-vi-nguonc-ready-cut110s-1.15x-9x16.mp4`.
To change trim/logo settings for the same speed, move that output and its report aside first.


## Ảnh bìa đánh số tự động

Mỗi lần chạy thành công, pipeline tạo thêm ảnh bìa dọc 1080×1920:
`output/videos/tap-003/one-piece-ep-003-cover.jpg` với chữ **TẬP 03**.
Ảnh gốc `assets/fanpage/bia_new.jpg` được giữ nguyên; toàn bộ ảnh được đặt ở giữa
nền mờ, số tập trắng trên ô đen. Không chèn ảnh bìa vào video.
Khi video đã có đúng cấu hình, chạy lại vẫn tạo/cập nhật bìa mà không encode video.

```powershell
# Video và bìa trong cùng pipeline
python scripts/download_nguonc.py --episode 3
# Chỉ tạo bìa, không tải hoặc xuất video
python scripts/download_nguonc.py --episode 2 --cover-only
# Đổi ảnh nguồn hoặc bỏ qua bìa
python scripts/download_nguonc.py --episode 3 --cover-image assets/fanpage/bia_new.jpg
python scripts/download_nguonc.py --episode 3 --no-cover
```

Khi đăng Reel, chọn JPG này nếu giao diện có tùy chọn tải ảnh bìa riêng.
Nếu tạo bìa lỗi sau khi xuất video, MP4 đã hoàn thành vẫn được giữ lại;
sửa ảnh/font/thư viện rồi chạy `--cover-only` để tạo lại.


## Gom output theo tập và tự mở thư mục

Mặc định sau khi hoàn tất, pipeline mở File Explorer tại thư mục của tập:

```text
output/videos/tap-003/
  one-piece-ep-003-vi-nguonc-ready-cut110s-1.15x-9x16.mp4
  one-piece-ep-003-cover.jpg
  one-piece-ep-003-vi-nguonc-ready-1.15x.report.json
```

Video và bìa ở cùng một nơi để kéo thả đăng. `--cover-only` cũng lưu tại đây.
Khi chạy lại tập đã xuất, các file hoàn thiện trong cấu trúc cũ được chuyển sang
thư mục tập nếu không trùng file; không tải/encode lại chỉ vì đổi đường dẫn.
File đang xuất `.working.mp4` không được chuyển. Nếu trùng tên, file cũ được giữ và có cảnh báo.

```powershell
.\run_download.cmd --episode 3
# Không mở cửa sổ (chạy batch/tự động):
.\run_download.cmd --episode 3 --no-open
```

Lỗi xuất video/bìa không mở thư mục. Nếu File Explorer không mở được,
pipeline chỉ cảnh báo; các file đã xuất vẫn được giữ nguyên.


## Bìa mới và video dọc 9:16

Mặc định dùng `assets/fanpage/bia_new.jpg`, giữ bố cục ảnh dọc và giảm chữ số tập
từ 100 xuống 72 px. Bìa tạo lại cùng tên trong thư mục tập.

Video mặc định 1080×1920 (9:16): giữ trọn khung cảnh phim gốc nằm giữa nền mờ,
không kéo giãn hoặc cắt mất hai bên. Logo vẫn nằm góc phải của cảnh phim.
Cắt intro 110 giây và tốc độ 1.15x vẫn giữ nguyên.
File mới có hậu tố `-9x16.mp4`, không ghi đè bản ngang cũ.

```powershell
# Dùng cache để xuất lại tập đã tải thành bản dọc:
.\run_download.cmd --episode 2 --merge-only
# Chỉ làm lại bìa mới:
.\run_download.cmd --episode 2 --cover-only
# Xuất bản giữ nguyên khung hình gốc nếu cần:
.\run_download.cmd --episode 2 --layout original
```

Khung dọc không đảm bảo bỏ được giới hạn 90 giây trong giao diện đăng Reel.
Kiểm tra thời lượng trên màn hình đăng trước khi chia sẻ.


Mặc định bỏ **110 giây đầu (1:50)** trên timeline video gốc, tăng thêm 5 giây so với bản trước.
Các segment hoàn toàn trước mốc này không được tải. File mới có `-cut110s` trong tên,
giữ nguyên bản cắt 105 giây cũ. Dùng cache để xuất lại mà không tải segment mới:

```powershell
.\run_download.cmd --episode 2 --merge-only
```
