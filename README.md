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
- `PI_SCAN_PANEL_VERSION` - optional release version without the `v` prefix, for example `0.5.0`. The footer displays `v0.5.0`; leave empty or unset to hide the version. Update it manually for each release and restart the application after changing it.
- `PI_SCAN_PANEL_FOOTER_TEXT` - optional plain text displayed beside the version, for example `Canada` or `Developed in Canada`. Leave empty or unset to hide the text. It can also be shown without a version. Restart the application after changing it.

## Scan File Actions

The scan form supports rotation during scanning: no rotation, 90, 180, or 270 degrees. PDF scans are rotated before PDF conversion.

The web panel can open, download, rotate 90 degrees, print, and delete saved scan files. Press rotate twice for 180 degrees. Rotation is supported for PNG and JPG files. PDF files can be opened, downloaded, printed, and deleted.

Printing is available from each saved scan row with the `Друк` button. Files are sent to CUPS with:

```bash
lp -d Canon_LBP2900 -o media=A4 -n 1 <scan-file>
```

## Health Check

```text
GET /health
```

Returns basic JSON status, including whether the shared scan/print command lock is currently busy.
