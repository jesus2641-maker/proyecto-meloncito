import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "").lower() in ("1", "true")
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
