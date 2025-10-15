# Configuración de Gunicorn
import os

bind = f"0.0.0.0:{os.getenv('PORT', '5000')}"
workers = 2
threads = 4
worker_class = 'gthread'
timeout = 120
accesslog = '-'
errorlog = '-'
loglevel = 'info'
capture_output = True
enable_stdio_inheritance = True

# IMPORTANTE: preload_app inicializa la BD antes de crear workers
preload_app = True

# Hook que se ejecuta ANTES de cargar los workers
def on_starting(server):
    """Se ejecuta UNA SOLA VEZ antes de crear workers."""
    print("🚀 Gunicorn iniciando en puerto", os.getenv('PORT', '5000'))

def when_ready(server):
    """Se ejecuta cuando el servidor está listo."""
    print("✓ Gunicorn listo para recibir peticiones")
    print(f"✓ Escuchando en {bind}")