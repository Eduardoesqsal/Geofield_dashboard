"""Punto de entrada compatible con el backend original.

Ejecutar con: ``uvicorn app:app --reload --port 8005``.
"""

import socket

import uvicorn

from geofield.app_factory import create_app
from geofield.config import Settings

settings = Settings.from_env()
app = create_app(settings)


def get_local_ip() -> str:
    """Obtiene la IP LAN para abrir el dashboard desde otro dispositivo."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


if __name__ == "__main__":
    local_ip = get_local_ip()
    print(f"[LINK] http://127.0.0.1:{settings.port}/", flush=True)
    print(f"[LINK] Red local: http://{local_ip}:{settings.port}/", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=settings.port, reload=False)
