FROM python:3.11-slim

# Evitar que Python genere archivos bytecode y asegurar que los logs de consola salgan en tiempo real
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 5010

CMD ["python", "app.py"]