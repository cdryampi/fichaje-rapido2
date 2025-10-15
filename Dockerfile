# Usa una imagen base de Python 3.11
FROM python:3.11-slim

# Establece el directorio de trabajo
WORKDIR /app

# Instala dependencias del sistema necesarias para SQLite y build tools
RUN apt-get update && apt-get install -y \
    gcc \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copia los archivos de requirements primero (mejor cache de Docker)
COPY requirements.txt .

# Crea el entorno virtual e instala las dependencias
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia el resto de la aplicación
COPY . .

# Crea el directorio para la base de datos si no existe
RUN mkdir -p /app/data

# Variables de entorno
ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1
ENV PORT=5000

# Expone el puerto
EXPOSE 5000

# Script de inicio que inicializa la BD y arranca gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
