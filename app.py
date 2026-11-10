# app.py

# Custom Modules
from pi_scan_panel.web import app


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
