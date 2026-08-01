# Pi Scan Panel

Minimal Flask web panel for a USB scanner connected to Raspberry Pi. It lets users on the local network open a browser, log in, run an A4 scan, and download the generated PNG or PDF file.

## Prerequisites

- Raspberry Pi with Ubuntu Server 24.04 or similar Linux system.
- Canon CanoScan LiDE 90 or another scanner supported by SANE.
- `scanimage` installed and working.
- One scanner connected to the Raspberry Pi over USB.
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

## Setup

Install system packages:

```bash
sudo apt update
sudo apt install sane-utils python3 python3-venv python3-pip
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

## Configuration

- `SCANNER_USERNAME` - login for the web panel.
- `SCANNER_PASSWORD` - password for the web panel.
- `SCANNER_SCAN_DIR` - directory for generated scan files, defaults to `/home/pi/scans`.
- `SCANNER_SECRET_KEY` - Flask session secret.
- `SCANNER_DEVICE` - optional SANE device id. Leave unset when only one scanner is connected.

## Health Check

```text
GET /health
```

Returns basic JSON status, including whether the scanner lock is currently busy.
