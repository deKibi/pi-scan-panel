# app.py

# Standard Libraries
import hmac
import os
import re
import secrets
import subprocess
import threading
from datetime import datetime
from functools import wraps
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from zoneinfo import ZoneInfo

# Third-party Libraries
from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template_string,
    request,
    send_from_directory,
    session,
    url_for,
)
from PIL import Image
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename


# Scan settings
SCAN_MODES: tuple[str, ...] = ("Color", "Gray", "Lineart")
SCAN_RESOLUTIONS: tuple[str, ...] = ("300", "600")
OUTPUT_FORMATS: tuple[str, ...] = ("png", "pdf")
ROTATIONS: tuple[str, ...] = ("none", "90", "180", "270")
DEFAULT_SCAN_DIR = "/home/pi/scans"
DEFAULT_PRINTER_NAME = "Canon_LBP2900"
DEFAULT_UPLOAD_DIR = "/home/pi/scans/uploads"
SCAN_TIMEOUT_SECONDS = 900
PRINT_TIMEOUT_SECONDS = 60
SCAN_FILES_PER_PAGE = 20
PREVIEW_MAX_SIZE = (640, 640)
PREVIEW_JPEG_QUALITY = 85
# Bump this when preview dimensions or encoding settings change.
PREVIEW_CACHE_VERSION = 2
KYIV_TIMEZONE = ZoneInfo("Europe/Kyiv")
SCAN_FILE_EXTENSIONS: frozenset[str] = frozenset({".png", ".pdf", ".jpg", ".jpeg"})
IMAGE_FILE_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg"})
PRINT_FILE_EXTENSIONS: frozenset[str] = frozenset({".png", ".pdf", ".jpg", ".jpeg"})
UPLOAD_MIME_TYPES: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"application/pdf"}),
    ".png": frozenset({"image/png"}),
    ".jpg": frozenset({"image/jpeg", "image/pjpeg"}),
    ".jpeg": frozenset({"image/jpeg", "image/pjpeg"}),
}

# Runtime state
command_lock = threading.Lock()
preview_lock = threading.Lock()
last_scan: dict[str, str] | None = None


load_dotenv()

APP_USERNAME = os.getenv("SCANNER_USERNAME")
APP_PASSWORD = os.getenv("SCANNER_PASSWORD")
SCAN_DIR = Path(os.getenv("SCANNER_SCAN_DIR", DEFAULT_SCAN_DIR)).expanduser()
SCANNER_DEVICE = os.getenv("SCANNER_DEVICE")
PRINTER_NAME = os.getenv("PI_SCAN_PANEL_PRINTER_NAME", DEFAULT_PRINTER_NAME)
UPLOAD_DIR = Path(os.getenv("PI_SCAN_PANEL_UPLOAD_DIR", DEFAULT_UPLOAD_DIR)).expanduser()
MAX_UPLOAD_MB = int(os.getenv("PI_SCAN_PANEL_MAX_UPLOAD_MB", "25"))

if not APP_USERNAME or not APP_PASSWORD:
    raise RuntimeError("SCANNER_USERNAME and SCANNER_PASSWORD must be set in .env")

app = Flask(__name__)
app.secret_key = os.getenv("SCANNER_SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


BASE_TEMPLATE = """
<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }}</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #161a1d;
      --muted: #63707c;
      --border: #d9dee5;
      --accent: #1f6feb;
      --accent-strong: #1458c8;
      --danger-bg: #fff0f0;
      --danger-text: #9f1d1d;
      --success-bg: #edf9f1;
      --success-text: #1b6b35;
      --busy-bg: #fff7e6;
      --busy-text: #795100;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }

    .page {
      width: min(100%, 720px);
      margin: 0 auto;
      padding: 24px 16px 36px;
    }

    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }

    h1 {
      margin: 0;
      font-size: clamp(1.55rem, 4vw, 2.2rem);
      line-height: 1.15;
      letter-spacing: 0;
    }

    .subtitle {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 0.98rem;
    }

    .logout {
      color: var(--accent);
      font-weight: 650;
      text-decoration: none;
      white-space: nowrap;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
    }

    form {
      display: grid;
      gap: 16px;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }

    label {
      display: grid;
      gap: 7px;
      color: var(--muted);
      font-size: 0.9rem;
      font-weight: 650;
    }

    select,
    input {
      width: 100%;
      min-height: 46px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #ffffff;
      color: var(--text);
      font: inherit;
      padding: 10px 12px;
    }

    button {
      min-height: 50px;
      border: 0;
      border-radius: 8px;
      background: var(--accent);
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-weight: 750;
      padding: 12px 16px;
    }

    button:active {
      background: var(--accent-strong);
    }

    button:disabled {
      cursor: not-allowed;
      opacity: 0.65;
    }

    .message {
      border-radius: 8px;
      margin: 0 0 16px;
      padding: 12px 14px;
      font-weight: 650;
    }

    .message.error {
      background: var(--danger-bg);
      color: var(--danger-text);
    }

    .message.success {
      background: var(--success-bg);
      color: var(--success-text);
    }

    .message.busy {
      background: var(--busy-bg);
      color: var(--busy-text);
    }

    .download {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 46px;
      border-radius: 8px;
      background: #161a1d;
      color: #ffffff;
      font-weight: 750;
      margin-top: 12px;
      padding: 10px 14px;
      text-decoration: none;
    }

    .hint {
      color: var(--muted);
      font-size: 0.9rem;
      margin: 14px 0 0;
    }

    .scan-status {
      color: var(--busy-text);
      font-weight: 650;
      margin: -4px 0 0;
      min-height: 22px;
    }

    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 12px;
    }

    .button-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 42px;
      border-radius: 8px;
      background: #161a1d;
      color: #ffffff;
      font-weight: 750;
      padding: 9px 13px;
      text-decoration: none;
    }

    .scan-list {
      display: grid;
      gap: 12px;
      margin-top: 22px;
    }

    h2 {
      font-size: 1.15rem;
      letter-spacing: 0;
      margin: 0;
    }

    .scan-item {
      display: grid;
      grid-template-columns: 96px minmax(0, 1fr);
      gap: 12px;
      align-items: center;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px;
    }

    .scan-preview {
      align-items: center;
      aspect-ratio: 1 / 1.25;
      background: #eef1f5;
      border: 1px solid var(--border);
      border-radius: 6px;
      color: var(--muted);
      display: flex;
      font-weight: 800;
      justify-content: center;
      overflow: hidden;
      position: relative;
      text-decoration: none;
      width: 100%;
    }

    .scan-preview img {
      display: block;
      height: 100%;
      object-fit: cover;
      opacity: 0;
      position: absolute;
      inset: 0;
      width: 100%;
    }

    .preview-error {
      display: none;
    }

    .scan-preview.is-loaded img {
      opacity: 1;
    }

    .scan-preview.is-error .preview-error {
      display: block;
    }

    .pagination {
      align-items: center;
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      justify-content: center;
      margin-top: 18px;
    }

    .scan-meta {
      display: grid;
      gap: 5px;
      min-width: 0;
    }

    .scan-meta strong,
    .scan-meta span {
      overflow-wrap: anywhere;
    }

    .scan-meta span {
      color: var(--muted);
      font-size: 0.9rem;
    }

    .scan-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 4px;
    }

    .scan-actions a {
      color: var(--accent);
      font-weight: 750;
      text-decoration: none;
    }

    .scan-actions form {
      display: inline;
    }

    .scan-actions button {
      background: transparent;
      color: var(--accent);
      min-height: auto;
      padding: 0;
      text-align: left;
    }

    .scan-actions .danger {
      color: var(--danger-text);
    }

    .section-title {
      font-size: 1.15rem;
      letter-spacing: 0;
      margin: 22px 0 12px;
    }

    .upload-form {
      border: 1px solid var(--border);
      border-radius: 8px;
      margin-top: 16px;
      padding: 14px;
    }

    .print-status {
      color: var(--busy-text);
      font-weight: 650;
      margin: -4px 0 0;
      min-height: 22px;
    }

    .printer-status {
      background: #f9fafb;
      border: 1px solid var(--border);
      border-radius: 8px;
      color: var(--muted);
      font-size: 0.9rem;
      margin-top: 14px;
      padding: 12px;
      white-space: pre-wrap;
    }

    @media (max-width: 560px) {
      .page {
        padding: 18px 12px 28px;
      }

      .topbar {
        align-items: flex-start;
      }

      .panel {
        padding: 16px;
      }

      .grid {
        grid-template-columns: 1fr;
      }

      .actions {
        display: grid;
        grid-template-columns: 1fr;
      }

      .scan-item {
        grid-template-columns: 74px minmax(0, 1fr);
      }
    }
  </style>
</head>
<body>
  <main class="page">
    <div class="topbar">
      <div>
        <h1>{{ heading }}</h1>
        {% if subtitle %}<p class="subtitle">{{ subtitle }}</p>{% endif %}
      </div>
      {% if logged_in %}
        <a class="logout" href="{{ url_for('logout') }}">Вийти</a>
      {% endif %}
    </div>
    <section class="panel">
      {% if message %}
        <p class="message {{ message_type }}">{{ message }}</p>
      {% endif %}
      {{ body|safe }}
    </section>
  </main>
</body>
</html>
"""

LOGIN_BODY = """
<form method="post" action="{{ url_for('login') }}">
  <label>
    Логін
    <input name="username" autocomplete="username" required autofocus>
  </label>
  <label>
    Пароль
    <input name="password" type="password" autocomplete="current-password" required>
  </label>
  <button type="submit">Увійти</button>
</form>
"""

HOME_BODY = """
<form class="scan-form" method="post" action="{{ url_for('index') }}">
  <div class="grid">
    <label>
      Режим
      <select name="mode">
        {% for item in modes %}
          <option value="{{ item }}" {% if values.mode == item %}selected{% endif %}>
            {{ item }}
          </option>
        {% endfor %}
      </select>
    </label>
    <label>
      Роздільність
      <select name="resolution">
        {% for item in resolutions %}
          <option value="{{ item }}" {% if values.resolution == item %}selected{% endif %}>
            {{ item }} dpi
          </option>
        {% endfor %}
      </select>
    </label>
    <label>
      Формат
      <select name="output_format">
        {% for item in formats %}
          <option value="{{ item }}" {% if values.output_format == item %}selected{% endif %}>
            {{ item|upper }}
          </option>
        {% endfor %}
      </select>
    </label>
    <label>
      Поворот
      <select name="rotation">
        {% for item in rotations %}
          <option value="{{ item }}" {% if values.rotation == item %}selected{% endif %}>
            {% if item == "none" %}Без повороту{% else %}{{ item }}°{% endif %}
          </option>
        {% endfor %}
      </select>
    </label>
  </div>
  <button type="submit" {% if busy %}disabled{% endif %}>
    {% if busy %}Сканер або принтер зайнятий{% else %}Сканувати{% endif %}
  </button>
  <p class="scan-status" id="scan-status" aria-live="polite"></p>
</form>
{% if filename %}
  <div class="actions">
    <a class="button-link" href="{{ url_for('open_scan', filename=filename) }}" target="_blank" rel="noopener">Відкрити останній скан</a>
    <a class="button-link" href="{{ url_for('download_scan', filename=filename) }}">Завантажити останній скан</a>
  </div>
{% endif %}
<p class="hint">A4, область сканування 210 × 297 мм. Файли зберігаються локально на Raspberry Pi.</p>
<div class="printer-status" id="printer-status" data-status-url="{{ url_for('printer_status') }}" aria-live="polite">Завантажуємо статус принтера...</div>
{% if scan_files %}
  <div class="scan-list">
    <h2>Скани</h2>
    {% for file in scan_files %}
      <article class="scan-item">
        {% if file.is_image %}
          <a class="scan-preview" href="{{ file.open_url }}" target="_blank" rel="noopener">
            <svg class="preview-error" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
              <rect x="3" y="3" width="18" height="18" rx="2"></rect>
              <circle cx="8" cy="8" r="1.5"></circle>
              <path d="m21 15-5-5L5 21M3 3l18 18"></path>
            </svg>
            <img data-preview-src="{{ file.preview_url }}" alt="{{ file.name }}" width="96" height="120" decoding="async">
          </a>
        {% else %}
          <a class="scan-preview pdf-preview" href="{{ file.open_url }}" target="_blank" rel="noopener">PDF</a>
        {% endif %}
        <div class="scan-meta">
          <strong>{{ file.name }}</strong>
          <span>{{ file.completed_at }} · {{ file.size }}</span>
          <div class="scan-actions">
            <a href="{{ file.open_url }}" target="_blank" rel="noopener">Відкрити</a>
            <a href="{{ file.download_url }}">Завантажити</a>
            {% if file.can_rotate %}
              <form class="action-form" method="post" action="{{ file.rotate_url }}">
                <button type="submit">Повернути 90°</button>
              </form>
            {% endif %}
            <form class="action-form print-form" method="post" action="{{ file.print_url }}">
              <button type="submit">Друк</button>
            </form>
            <form class="action-form delete-form" method="post" action="{{ file.delete_url }}">
              <button class="danger" type="submit">Видалити</button>
            </form>
          </div>
        </div>
      </article>
    {% endfor %}
  </div>
  {% if page_count > 1 %}
    <nav class="pagination" aria-label="Сторінки сканів">
      {% if page > 1 %}
        <a class="button-link" href="{{ url_for('index', page=page - 1) }}">Попередня</a>
      {% endif %}
      <span aria-current="page">Сторінка {{ page }} з {{ page_count }}</span>
      {% if page < page_count %}
        <a class="button-link" href="{{ url_for('index', page=page + 1) }}">Наступна</a>
      {% endif %}
    </nav>
  {% endif %}
{% else %}
  <p class="hint">Поки немає збережених сканів.</p>
{% endif %}
<script>
  // Start image requests after the document loads so previews do not hold up the page.
  window.addEventListener("load", () => {
    const previewQueue = new Set();
    const previewMargin = 200;
    const maxActivePreviews = 2;
    let activePreviews = 0;

    function loadNextPreviews() {
      const candidates = [...previewQueue].map((image) => {
        const bounds = image.getBoundingClientRect();
        return {
          image,
          top: bounds.top,
          bottom: bounds.bottom,
          visible: bounds.bottom > 0 && bounds.top < window.innerHeight,
        };
      }).filter((item) => (
        item.bottom >= -previewMargin && item.top <= window.innerHeight + previewMargin
      )).sort((first, second) => (
        Number(second.visible) - Number(first.visible) || first.top - second.top
      ));

      for (const { image, visible } of candidates) {
        if (activePreviews >= maxActivePreviews) {
          break;
        }

        previewQueue.delete(image);
        previewObserver.unobserve(image);
        activePreviews += 1;
        image.fetchPriority = visible ? "high" : "low";

        function finishPreview(loaded) {
          const preview = image.closest(".scan-preview");
          if (loaded) {
            preview.classList.add("is-loaded");
          } else {
            preview.classList.add("is-error");
            preview.title = "Прев’ю недоступне. Відкрити оригінал.";
            preview.setAttribute("aria-label", `${image.alt}: ${preview.title}`);
          }
          activePreviews -= 1;
          loadNextPreviews();
        }

        image.addEventListener("load", () => finishPreview(true), { once: true });
        image.addEventListener("error", () => finishPreview(false), { once: true });
        image.src = image.dataset.previewSrc;
      }
    }

    const previewObserver = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          previewQueue.add(entry.target);
        } else {
          previewQueue.delete(entry.target);
        }
      }
      loadNextPreviews();
    }, { rootMargin: `${previewMargin}px 0px` });

    document.querySelectorAll("img[data-preview-src]").forEach((image) => {
      previewObserver.observe(image);
    });

    const printerStatus = document.querySelector("#printer-status");
    fetch(printerStatus.dataset.statusUrl, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) {
          throw new Error("Printer status request failed");
        }
        return response.json();
      })
      .then((data) => {
        printerStatus.textContent = data.status;
      })
      .catch(() => {
        printerStatus.textContent = "Статус принтера недоступний.";
      });
  }, { once: true });

  const scanForm = document.querySelector(".scan-form");
  const scanButton = scanForm.querySelector("button[type='submit']");
  const scanStatus = document.querySelector("#scan-status");

  scanForm.addEventListener("submit", () => {
    scanButton.disabled = true;
    scanButton.textContent = "Сканування триває...";
    scanStatus.textContent = "Сканер почав роботу. Не закривайте сторінку до завершення.";
  });

  document.querySelectorAll(".print-form").forEach((form) => {
    form.addEventListener("submit", () => {
      const button = form.querySelector("button[type='submit']");
      const status = form.querySelector(".print-status");

      if (button) {
        button.disabled = true;
        button.textContent = "Відправляємо на друк...";
      }
      if (status) {
        status.textContent = "Файл передається у чергу друку.";
      }
    });
  });

  document.querySelectorAll(".delete-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!confirm("Видалити цей файл?")) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll(".action-form:not(.print-form)").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (event.defaultPrevented) {
        return;
      }

      const button = form.querySelector("button[type='submit']");

      if (button) {
        button.disabled = true;
      }
    });
  });
</script>
"""


def render_page(
    title: str,
    heading: str,
    body_template: str,
    message: str | None = None,
    message_type: str = "success",
    subtitle: str | None = None,
    **context: Any,
) -> str:
    body = render_template_string(body_template, **context)
    return render_template_string(
        BASE_TEMPLATE,
        title=title,
        heading=heading,
        subtitle=subtitle,
        logged_in=session.get("logged_in"),
        message=message,
        message_type=message_type,
        body=body,
    )


def login_required(view: Any) -> Any:
    @wraps(view)
    def wrapped_view(*args: Any, **kwargs: Any) -> Any:
        if not session.get("logged_in"):
            return redirect(url_for("login"))

        return view(*args, **kwargs)

    return wrapped_view


def get_form_values() -> dict[str, str]:
    return {
        "mode": request.form.get("mode", "Color"),
        "resolution": request.form.get("resolution", "300"),
        "output_format": request.form.get("output_format", "png"),
        "rotation": request.form.get("rotation", "none"),
    }


def validate_form(values: dict[str, str]) -> str | None:
    if values["mode"] not in SCAN_MODES:
        return "Невідомий режим сканування."
    if values["resolution"] not in SCAN_RESOLUTIONS:
        return "Невідома роздільність."
    if values["output_format"] not in OUTPUT_FORMATS:
        return "Невідомий формат файлу."
    if values["rotation"] not in ROTATIONS:
        return "Невідоме значення повороту."

    return None


def build_scan_command(values: dict[str, str]) -> list[str]:
    command = ["scanimage"]

    if SCANNER_DEVICE:
        command.extend(["-d", SCANNER_DEVICE])

    command.extend(
        [
            "--format=png",
            "--mode",
            values["mode"],
            "--resolution",
            values["resolution"],
            "-x",
            "210",
            "-y",
            "297",
        ]
    )
    return command


def create_timestamped_filename(extension: str) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return f"scan-{timestamp}.{extension}"


def format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"

    return f"{size_bytes / 1024 / 1024:.1f} MB"


def get_safe_scan_path(filename: str) -> Path | None:
    requested_name = Path(filename).name
    requested_path = SCAN_DIR / requested_name

    if requested_name != filename:
        return None
    if requested_path.suffix.lower() not in SCAN_FILE_EXTENSIONS:
        return None
    if not requested_path.is_file():
        return None

    return requested_path


def get_preview_version(stat: os.stat_result) -> str:
    return (
        f"{PREVIEW_CACHE_VERSION}-{stat.st_mtime_ns}-"
        f"{stat.st_ctime_ns}-{stat.st_size}"
    )


def list_scan_files(page: int = 1) -> tuple[list[dict[str, Any]], int, int]:
    if not SCAN_DIR.is_dir():
        return [], 1, 1

    scan_paths: list[tuple[Path, os.stat_result]] = []
    with os.scandir(SCAN_DIR) as entries:
        for entry in entries:
            if Path(entry.name).suffix.lower() in SCAN_FILE_EXTENSIONS and entry.is_file():
                scan_paths.append((Path(entry.path), entry.stat()))

    scan_paths.sort(key=lambda item: item[1].st_mtime_ns, reverse=True)
    page_count = max(1, (len(scan_paths) + SCAN_FILES_PER_PAGE - 1) // SCAN_FILES_PER_PAGE)
    page = min(max(1, page), page_count)
    offset = (page - 1) * SCAN_FILES_PER_PAGE
    files: list[dict[str, Any]] = []
    for path, stat in scan_paths[offset:offset + SCAN_FILES_PER_PAGE]:
        suffix = path.suffix.lower()
        completed_at = datetime.fromtimestamp(stat.st_mtime, tz=KYIV_TIMEZONE)
        files.append(
            {
                "name": path.name,
                "completed_at": completed_at.strftime("%Y-%m-%d %H:%M:%S"),
                "mtime": stat.st_mtime,
                "size": format_file_size(stat.st_size),
                "is_image": suffix in IMAGE_FILE_EXTENSIONS,
                "can_rotate": suffix in IMAGE_FILE_EXTENSIONS,
                "open_url": url_for("open_scan", filename=path.name),
                "preview_url": (
                    url_for(
                        "preview_scan",
                        filename=path.name,
                        v=get_preview_version(stat),
                    ) if suffix in IMAGE_FILE_EXTENSIONS else None
                ),
                "download_url": url_for("download_scan", filename=path.name),
                "rotate_url": url_for("rotate_scan", filename=path.name, page=page),
                "print_url": url_for("print_scan", filename=path.name, page=page),
                "delete_url": url_for("delete_scan", filename=path.name, page=page),
            }
        )

    return files, page, page_count


def remove_scan_previews(path: Path) -> None:
    preview_dir = SCAN_DIR / "previews" / path.name
    if not preview_dir.is_dir():
        return

    for preview_path in preview_dir.glob("*.jpg"):
        preview_path.unlink(missing_ok=True)
    preview_dir.rmdir()


def get_scan_preview(path: Path) -> Path:
    # Serializing generation bounds memory use when decoding large scans on the Pi.
    with preview_lock:
        stat = path.stat()
        preview_dir = SCAN_DIR / "previews" / path.name
        preview_path = preview_dir / f"{get_preview_version(stat)}.jpg"
        if preview_path.is_file():
            return preview_path

        preview_dir.mkdir(parents=True, exist_ok=True)
        with Image.open(path) as image:
            image.thumbnail(PREVIEW_MAX_SIZE, Image.Resampling.LANCZOS)
            if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                image = image.convert("RGBA")
                thumbnail = Image.new("RGB", image.size, "white")
                thumbnail.paste(image, mask=image.getchannel("A"))
            else:
                thumbnail = image.convert("RGB")

            with NamedTemporaryFile(
                dir=preview_dir, suffix=".jpg", delete=False
            ) as preview_file:
                temporary_path = Path(preview_file.name)
                try:
                    thumbnail.save(
                        preview_file,
                        format="JPEG",
                        quality=PREVIEW_JPEG_QUALITY,
                        optimize=True,
                    )
                    preview_file.close()
                    temporary_path.replace(preview_path)
                finally:
                    temporary_path.unlink(missing_ok=True)

        for old_preview in preview_dir.glob("*.jpg"):
            if old_preview != preview_path:
                old_preview.unlink(missing_ok=True)
        return preview_path


def get_printer_status() -> str:
    status_parts: list[str] = []
    commands = (
        ["lpstat", "-p", PRINTER_NAME, "-l"],
        ["lpstat", "-o", PRINTER_NAME],
    )

    for command in commands:
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return f"Статус принтера недоступний: {error}"

        output = result.stdout.strip() or result.stderr.strip()
        if output:
            status_parts.append(output)

    return "\n".join(status_parts) if status_parts else f"Принтер {PRINTER_NAME}: черга порожня."


def run_print_command(file_path: Path) -> str:
    result = subprocess.run(
        ["lp", "-d", PRINTER_NAME, "-o", "media=A4", "-n", "1", str(file_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
        timeout=PRINT_TIMEOUT_SECONDS,
    )
    return result.stdout.strip()


def print_file_with_lock(file_path: Path) -> tuple[str, str]:
    if not command_lock.acquire(blocking=False):
        return "Сканер або принтер вже виконує іншу команду. Спробуйте ще раз за кілька секунд.", "busy"

    try:
        output = run_print_command(file_path)
    except subprocess.TimeoutExpired:
        return "Передача файлу на друк перевищила ліміт часу.", "error"
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip()
        suffix = f" Деталі: {detail}" if detail else ""
        return f"Не вдалося відправити файл на друк.{suffix}", "error"
    except OSError as error:
        return f"Не вдалося запустити команду друку: {error}", "error"
    finally:
        command_lock.release()

    detail = f" CUPS: {output}" if output else ""
    return f"Файл відправлено на друк.{detail}", "success"


def create_safe_upload_filename(original_filename: str) -> str | None:
    safe_name = secure_filename(original_filename)
    if not safe_name:
        return None

    path = Path(safe_name)
    suffix = path.suffix.lower()
    if suffix not in PRINT_FILE_EXTENSIONS:
        return None

    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", path.stem).strip("-") or "upload"
    stem = stem[:80]
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return f"upload-{timestamp}-{stem}{suffix}"


def is_allowed_upload(filename: str, mime_type: str) -> bool:
    suffix = Path(filename).suffix.lower()
    allowed_mime_types = UPLOAD_MIME_TYPES.get(suffix)

    return bool(allowed_mime_types and mime_type in allowed_mime_types)


def save_uploaded_print_file() -> tuple[Path | None, str | None]:
    uploaded_file = request.files.get("upload")
    if uploaded_file is None or not uploaded_file.filename:
        return None, "Оберіть файл для друку."

    upload_filename = create_safe_upload_filename(uploaded_file.filename)
    if upload_filename is None:
        return None, "Підтримуються тільки PDF, PNG, JPG або JPEG."
    if not is_allowed_upload(upload_filename, uploaded_file.mimetype):
        return None, "Тип файлу не відповідає дозволеним форматам PDF, PNG або JPG."

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    upload_path = UPLOAD_DIR / upload_filename
    uploaded_file.save(upload_path)
    return upload_path, None


def rotate_image_file(path: Path, degrees: int = 90) -> None:
    with preview_lock:
        remove_scan_previews(path)
        with Image.open(path) as image:
            rotated_image = image.rotate(-degrees, expand=True)
            if path.suffix.lower() in {".jpg", ".jpeg"} and rotated_image.mode in {"RGBA", "P"}:
                rotated_image = rotated_image.convert("RGB")

            rotated_image.save(path)


def apply_scan_rotation(path: Path, rotation: str) -> None:
    if rotation == "none":
        return

    rotate_image_file(path, int(rotation))


def run_scan(values: dict[str, str]) -> str:
    global last_scan

    SCAN_DIR.mkdir(parents=True, exist_ok=True)
    png_filename = create_timestamped_filename("png")
    png_path = SCAN_DIR / png_filename

    try:
        with png_path.open("wb") as png_file:
            subprocess.run(
                build_scan_command(values),
                stdout=png_file,
                stderr=subprocess.PIPE,
                check=True,
                timeout=SCAN_TIMEOUT_SECONDS,
            )
        apply_scan_rotation(png_path, values["rotation"])
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        png_path.unlink(missing_ok=True)
        raise

    if values["output_format"] == "png":
        last_scan = {"filename": png_filename, "format": "png"}
        return png_filename

    pdf_filename = png_path.with_suffix(".pdf").name
    pdf_path = SCAN_DIR / pdf_filename
    try:
        subprocess.run(
            ["img2pdf", str(png_path), "-o", str(pdf_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=SCAN_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pdf_path.unlink(missing_ok=True)
        raise

    png_path.unlink(missing_ok=True)
    last_scan = {"filename": pdf_filename, "format": "pdf"}
    return pdf_filename


def render_home(
    values: dict[str, str] | None = None,
    message: str | None = None,
    message_type: str = "success",
    filename: str | None = None,
) -> str:
    scan_files, page, page_count = list_scan_files(request.args.get("page", 1, type=int))
    return render_page(
        title="Pi Scan Panel",
        heading="Pi Scan Panel",
        subtitle="Локальна веб-панель для USB-сканера",
        body_template=HOME_BODY,
        message=message,
        message_type=message_type,
        modes=SCAN_MODES,
        resolutions=SCAN_RESOLUTIONS,
        formats=OUTPUT_FORMATS,
        rotations=ROTATIONS,
        values=values
        or {
            "mode": "Color",
            "resolution": "300",
            "output_format": "png",
            "rotation": "none",
        },
        busy=command_lock.locked(),
        filename=filename,
        scan_files=scan_files,
        page=page,
        page_count=page_count,
    )


@app.route("/", methods=["GET", "POST"])
@login_required
def index() -> str:
    if request.method == "GET":
        filename = last_scan["filename"] if last_scan else None
        return render_home(filename=filename)

    values = get_form_values()
    validation_error = validate_form(values)
    if validation_error:
        return render_home(values, validation_error, "error")

    if not command_lock.acquire(blocking=False):
        return render_home(values, "Сканер або принтер вже виконує іншу команду.", "busy")

    filename = None
    message = "Сканування завершено."
    message_type = "success"

    try:
        filename = run_scan(values)
    except subprocess.TimeoutExpired:
        message = "Сканування перевищило ліміт часу."
        message_type = "error"
    except subprocess.CalledProcessError as error:
        stderr = error.stderr.decode("utf-8", errors="replace").strip()
        detail = f" Деталі: {stderr}" if stderr else ""
        message = f"Команда сканування завершилась з помилкою.{detail}"
        message_type = "error"
    except OSError as error:
        message = f"Не вдалося запустити команду: {error}"
        message_type = "error"
    finally:
        command_lock.release()

    return render_home(values, message, message_type, filename)


@app.route("/login", methods=["GET", "POST"])
def login() -> str | Response:
    if request.method == "GET":
        return render_page(
            title="Вхід",
            heading="Вхід",
            subtitle="Доступ тільки для локальних користувачів",
            body_template=LOGIN_BODY,
        )

    username = request.form.get("username", "")
    password = request.form.get("password", "")
    if hmac.compare_digest(username, APP_USERNAME) and hmac.compare_digest(password, APP_PASSWORD):
        session.clear()
        session["logged_in"] = True
        return redirect(url_for("index"))

    return render_page(
        title="Вхід",
        heading="Вхід",
        subtitle="Доступ тільки для локальних користувачів",
        body_template=LOGIN_BODY,
        message="Невірний логін або пароль.",
        message_type="error",
    )


@app.route("/logout")
def logout() -> Response:
    session.clear()
    return redirect(url_for("login"))


@app.route("/download/<path:filename>")
@login_required
def download_scan(filename: str) -> Response:
    requested_path = get_safe_scan_path(filename)

    if requested_path is None:
        return Response("Invalid filename", status=400)

    return send_from_directory(SCAN_DIR, requested_path.name, as_attachment=True)


@app.route("/files/<path:filename>")
@login_required
def open_scan(filename: str) -> Response:
    requested_path = get_safe_scan_path(filename)

    if requested_path is None:
        return Response("Invalid filename", status=400)

    return send_from_directory(SCAN_DIR, requested_path.name, as_attachment=False)


@app.route("/previews/<path:filename>")
@login_required
def preview_scan(filename: str) -> Response:
    requested_path = get_safe_scan_path(filename)
    if requested_path is None or requested_path.suffix.lower() not in IMAGE_FILE_EXTENSIONS:
        return Response("Invalid filename", status=400)

    try:
        preview_path = get_scan_preview(requested_path)
    except (OSError, ValueError, Image.DecompressionBombError):
        app.logger.exception("Could not generate scan preview")
        return Response("Preview unavailable", status=500)

    response = send_from_directory(preview_path.parent, preview_path.name, max_age=0)
    response.cache_control.private = True
    return response


@app.route("/printer-status")
@login_required
def printer_status() -> Response:
    response = jsonify({"status": get_printer_status()})
    response.cache_control.no_store = True
    return response


@app.route("/rotate/<path:filename>", methods=["POST"])
@login_required
def rotate_scan(filename: str) -> str:
    requested_path = get_safe_scan_path(filename)

    if requested_path is None:
        return render_home(message="Файл не знайдено або ім'я файлу некоректне.", message_type="error")
    if requested_path.suffix.lower() not in IMAGE_FILE_EXTENSIONS:
        return render_home(message="Поворот доступний тільки для PNG або JPG.", message_type="error")

    try:
        rotate_image_file(requested_path)
    except OSError as error:
        return render_home(message=f"Не вдалося повернути файл: {error}", message_type="error")

    return render_home(message="Файл повернуто на 90°.", message_type="success", filename=requested_path.name)


@app.route("/delete/<path:filename>", methods=["POST"])
@login_required
def delete_scan(filename: str) -> str:
    global last_scan

    requested_path = get_safe_scan_path(filename)

    if requested_path is None:
        return render_home(message="Файл не знайдено або ім'я файлу некоректне.", message_type="error")

    try:
        with preview_lock:
            remove_scan_previews(requested_path)
            requested_path.unlink()
    except OSError as error:
        return render_home(message=f"Не вдалося видалити файл: {error}", message_type="error")

    if last_scan and last_scan.get("filename") == requested_path.name:
        last_scan = None

    return render_home(message="Файл видалено.", message_type="success")


@app.route("/print/<path:filename>", methods=["POST"])
@login_required
def print_scan(filename: str) -> str:
    requested_path = get_safe_scan_path(filename)

    if requested_path is None:
        return render_home(message="Файл не знайдено або ім'я файлу некоректне.", message_type="error")
    if requested_path.suffix.lower() not in PRINT_FILE_EXTENSIONS:
        return render_home(message="Цей формат не підтримується для друку.", message_type="error")

    message, message_type = print_file_with_lock(requested_path)
    return render_home(message=message, message_type=message_type, filename=requested_path.name)


@app.route("/print-upload", methods=["POST"])
@login_required
def print_upload() -> str:
    upload_path, error = save_uploaded_print_file()
    if error or upload_path is None:
        return render_home(message=error or "Не вдалося завантажити файл.", message_type="error")

    message, message_type = print_file_with_lock(upload_path)
    return render_home(message=message, message_type=message_type)


@app.errorhandler(RequestEntityTooLarge)
def handle_large_upload(error: RequestEntityTooLarge) -> tuple[str, int]:
    return (
        render_home(
            message=f"Файл завеликий. Максимальний розмір: {MAX_UPLOAD_MB} MB.",
            message_type="error",
        ),
        413,
    )


@app.route("/health")
def health() -> Response:
    return jsonify(
        {
            "status": "ok",
            "busy": command_lock.locked(),
            "command_busy": command_lock.locked(),
            "scan_dir": str(SCAN_DIR),
            "upload_dir": str(UPLOAD_DIR),
            "printer_name": PRINTER_NAME,
            "auth_configured": bool(APP_USERNAME and APP_PASSWORD),
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
