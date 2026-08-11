import os
import requests
import time
from flask import Flask
import psycopg2
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
from datetime import datetime

app = Flask(__name__)

# Variables de entorno inyectadas por docker-compose
DB_HOST = os.environ.get("DB_HOST", "db")
DB_NAME = os.environ.get("DB_NAME", "uf_db")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASS = os.environ.get("DB_PASS", "postgres")


def get_db_connection():
    return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)


def init_db():
    retries = 5
    while retries > 0:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS uf_data (
                    fecha DATE PRIMARY KEY,
                    valor NUMERIC NOT NULL
                )
            ''')
            conn.commit()
            cur.close()
            conn.close()
            print("Base de datos lista y conectada.")
            break
        except Exception as e:
            print("Esperando a que el contenedor de PostgreSQL inicie...")
            retries -= 1
            time.sleep(3)


def fetch_and_save_uf():
    print("Consultando findic.cl para actualizar base de datos...")
    try:
        # La API por defecto entrega los últimos 31 registros
        response = requests.get('https://findic.cl/api/uf')
        if response.status_code == 200:
            data = response.json()
            if 'serie' in data:
                conn = get_db_connection()
                cur = conn.cursor()
                for item in data['serie']:
                    # Limpiamos la fecha por si viene con formato de tiempo
                    fecha_str = item['fecha'].split('T')[0]
                    valor = item['valor']

                    cur.execute('''
                        INSERT INTO uf_data (fecha, valor)
                        VALUES (%s, %s)
                        ON CONFLICT (fecha) DO UPDATE SET valor = EXCLUDED.valor
                    ''', (fecha_str, valor))
                conn.commit()
                cur.close()
                conn.close()
                print("Base de datos actualizada exitosamente con los valores de la UF.")
    except Exception as e:
        print(f"Error en la petición o escritura: {e}")


# Ejecutamos la inicialización y un primer escaneo apenas arranca el contenedor
init_db()
fetch_and_save_uf()

# Programamos la revisión diaria a las 08:00 AM hora de Chile
scheduler = BackgroundScheduler(timezone=pytz.timezone('America/Santiago'))
scheduler.add_job(fetch_and_save_uf, 'cron', hour=8, minute=0)
scheduler.start()


@app.route('/uf')
def get_uf_today():
    # Aseguramos que busque la fecha actual de Chile, sin importar la zona horaria del servidor
    tz_chile = pytz.timezone('America/Santiago')
    hoy = datetime.now(tz_chile).strftime('%Y-%m-%d')

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Intentamos obtener la UF del día exacto
        cur.execute('SELECT valor FROM uf_data WHERE fecha = %s', (hoy,))
        row = cur.fetchone()

        # Fallback: si aún no se publica la de hoy, traemos el registro anterior más cercano
        if not row:
            cur.execute('SELECT valor FROM uf_data WHERE fecha <= %s ORDER BY fecha DESC LIMIT 1', (hoy,))
            row = cur.fetchone()

        cur.close()
        conn.close()

        if row:
            # Excel procesa mejor el dato si devolvemos el número plano como texto (ej: 37500.50)
            return str(row[0])
        else:
            return "Dato no encontrado", 404

    except Exception as e:
        return f"Error interno: {str(e)}", 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5010)