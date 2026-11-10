# Pi Scan Panel

Minimal Flask web panel for a USB scanner connected to Raspberry Pi. It lets users on the local network open a browser, log in, run an A4 scan, and download the generated PNG or PDF file.

## Prerequisites

- Raspberry Pi with Ubuntu Server 24.04 or similar Linux system.
- Canon CanoScan LiDE 90 or another scanner supported by SANE.
- `scanimage` installed and working.
- CUPS installed and the local printer queue working.
- Printer queue name: `Canon_LBP2900`.
- One scanner connected to the Raspberry Pi over USB.
- One printer connected to the Raspberry Pi over USB.
- Python 3 and pip.
- The app must run as a regular user, for example `pi`, not as root.

Check that SANE sees the scanner:

```bash
scanimage -L
```

Expected scan command shape:

```bash
scanimage --format=png --mode Color --resolution 300 -x 210 -y 297 > ~/scans/a4-color-300.png
```

Check that CUPS can print:

```bash
lp -d Canon_LBP2900 /usr/share/cups/data/testprint
```

## Setup

Install system packages:

```bash
sudo apt update
sudo apt install sane-utils cups-client python3 python3-venv python3-pip screen
```

Create a virtual environment and install Python dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Create local configuration from the example:

```bash
cp .env.example .env
```

Edit `.env` and set `SCANNER_USERNAME`, `SCANNER_PASSWORD`, and `SCANNER_SECRET_KEY`.

By default scans are saved to `/home/pi/scans`. If the app runs as `pi`, create the directory:

```bash
mkdir -p /home/pi/scans
```

## Run

```bash
. .venv/bin/activate
python app.py
```

The panel listens on:

```text
http://0.0.0.0:8080
```

From another device on the same LAN, open:

```text
http://<raspberry-pi-ip>:8080
```

## Run in screen

Use `screen` when you want a quick long-running session without keeping the SSH terminal attached:

```bash
cd /home/pi/pi-scan-panel
. .venv/bin/activate
screen -S pi-scan-panel
python app.py
```

Detach from the screen session:

```text
Ctrl+A, then D
```

Reattach later:

```bash
screen -r pi-scan-panel
```

## Run as a systemd service

Create a service file:

```bash
sudo nano /etc/systemd/system/pi-scan-panel.service
```

Example service:

```ini
[Unit]
Description=Pi Scan Panel
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/pi-scan-panel
EnvironmentFile=/home/pi/pi-scan-panel/.env
ExecStart=/home/pi/pi-scan-panel/.venv/bin/python /home/pi/pi-scan-panel/app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable pi-scan-panel
sudo systemctl start pi-scan-panel
sudo systemctl status pi-scan-panel
```

## Update

After updating the application files on the production Raspberry Pi, restart the service and check its status:

```bash
sudo systemctl restart pi-scan-panel
sudo systemctl status pi-scan-panel --no-pager
```

If the systemd service file changed, run `sudo systemctl daemon-reload` before restarting.

## Configuration

- `SCANNER_USERNAME` - login for the web panel.
- `SCANNER_PASSWORD` - password for the web panel.
- `SCANNER_SCAN_DIR` - directory for generated scan files, defaults to `/home/pi/scans`.
- `SCANNER_SECRET_KEY` - Flask session secret.
- `SCANNER_DEVICE` - optional SANE device id. Leave unset when only one scanner is connected.
- `PI_SCAN_PANEL_PRINTER_NAME` - CUPS printer queue, defaults to `Canon_LBP2900`.
- `PI_SCAN_PANEL_UPLOAD_DIR` - temporary upload directory for print jobs, defaults to `/home/pi/scans/uploads`.
- `PI_SCAN_PANEL_MAX_UPLOAD_MB` - maximum upload size in MB, defaults to `25`.
- `PI_SCAN_PANEL_VERSION` - optional release version displayed as provided, with surrounding whitespace trimmed and no automatic prefix: `v0.5.0` displays as `v0.5.0`, and `0.5.5` as `0.5.5`. Leave empty or unset to hide the version. Update it manually for each release and restart the application after changing it.
- `PI_SCAN_PANEL_FOOTER_TEXT` - optional plain text displayed beside the version, for example `Canada` or `Developed in Canada`. Leave empty or unset to hide the text. It can also be shown without a version. Restart the application after changing it.

## Scan File Actions

The scan form supports rotation during scanning: no rotation, 90, 180, or 270 degrees. PDF scans are rotated before PDF conversion.

The web panel can open, download, rotate 90 degrees, print, and delete saved scan files. Press rotate twice for 180 degrees. Rotation is supported for PNG and JPG files. PDF files can be opened, downloaded, printed, and deleted.

Images and the first page of PDFs have cached JPEG previews in both the scan list and trash. Preview requests start after the page loads, only near the visible area, with at most two requests at a time. Generation is serialized; PDF rendering runs in a separate Python process with a 10-second timeout and a maximum output size of 640 × 640 pixels. Unreadable or password-protected PDFs show the preview error indicator.

PDF rendering uses the `pypdfium2` Python dependency. Check that a binary wheel is available for the Raspberry Pi's OS and architecture before deployment; building PDFium from source on the Pi is not part of setup. After updating dependencies and code on the Pi, restart the running application using your existing launch method.

Printing is available from each saved scan row with the `Друк` button. Files are sent to CUPS with:

```bash
lp -d Canon_LBP2900 -o media=A4 -n 1 <scan-file>
```

## Local Preview Checks

Run the focused backend tests after installing `requirements.txt`:

```bash
python -m unittest discover -s tests -p 'test_previews.py' -v
```

These tests use synthetic credentials, bypass `.env` loading, and isolate scan files in temporary directories. They do not scan or print. If Node.js is available, verify the shared browser loading queue without additional packages:

```bash
node --test tests/test_scan_previews.js
```

Small portrait, landscape, and two-page PDFs are included in `tests/fixtures/pdf/`. To create an isolated local scan directory with these examples and an additional scan-like PDF of approximately 16 MB:

```bash
preview_scan_dir="$(mktemp -d -t pi-scan-preview)"
python tests/generate_preview_pdfs.py --output "$preview_scan_dir" --large
```

For a local browser check, run with synthetic settings and dotenv loading disabled:

```bash
FLASK_SKIP_DOTENV=1 PYTHON_DOTENV_DISABLED=1 \
SCANNER_USERNAME=preview SCANNER_PASSWORD=preview-local-only \
SCANNER_SECRET_KEY=preview-local-session-key \
SCANNER_SCAN_DIR="$preview_scan_dir" \
PI_SCAN_PANEL_UPLOAD_DIR="$preview_scan_dir/uploads" \
SCANNER_DEVICE=preview-test-only PI_SCAN_PANEL_PRINTER_NAME=preview-test-only \
python -m flask --app app run --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080` and log in using the synthetic credentials above. Verify that the two-page sample shows the red first page, landscape pages fit without cropping, and previews also work after moving a sample to trash. In browser developer tools, disable browser caching and check that preview requests begin after the main page loads; scroll through a longer list to confirm lazy loading and the two-request limit. Reload to check server cache reuse. On the Pi, compare cold and warm preview times and CPU/memory use with the large sample; desktop timings do not establish Pi performance.

## Health Check

```text
GET /health
```

Returns basic JSON status, including whether the shared scan/print command lock is currently busy.
