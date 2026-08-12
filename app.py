import os
import time
from datetime import datetime, timedelta
from flask import Flask
import psycopg2
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
import requests

app = Flask(__name__)

# Variables BD
DB_HOST = os.environ.get("DB_HOST", "db")
DB_NAME = os.environ.get("DB_NAME", "uf_db")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASS = os.environ.get("DB_PASS", "postgres")

# Token Banco Central
BCC_TOKEN = os.environ.get("BCC_TOKEN", "tu_token")

# Códigos oficiales del BCCh actualizados
SERIES = {
    "uf": "F073.UFF.PRE.Z.D",
    "dolar": "F073.TCO.PRE.Z.D",
    "plata": "F019.PPB.PRE.45.D"  # Código exacto obtenido de la API
}


def get_db_connection():
    return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)


def init_db():
    retries = 5
    while retries > 0:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS indicadores (
                    fecha DATE,
                    tipo VARCHAR(50),
                    valor NUMERIC NOT NULL,
                    PRIMARY KEY (fecha, tipo)
                )
            ''')
            conn.commit()
            cur.close()
            conn.close()
            print("Base de datos de indicadores lista y conectada.")
            break
        except Exception as e:
            print("Esperando a PostgreSQL...")
            retries -= 1
            time.sleep(3)


def fetch_and_save_data():
    print("Consultando API REST del Banco Central directamente...")

    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

    conn = get_db_connection()
    cur = conn.cursor()

    for tipo, serie in SERIES.items():
        try:
            url = f"https://si3.bcentral.cl/SieteRestWS/SieteRestWS.ashx?function=GetSeries&timeseries={serie}&firstdate={start_date}&lastdate={end_date}&token={BCC_TOKEN}"

            response = requests.get(url, timeout=15)

            try:
                data = response.json()
            except requests.exceptions.JSONDecodeError:
                print(f"Error crítico con {tipo}: El banco devolvió HTML en vez de JSON.")
                continue

            if data.get("Codigo") != 0:
                print(f"API BCCh rechazó la consulta de {tipo}: {data.get('Descripcion')}")
                continue

            observaciones = data.get("Series", {}).get("Obs", [])

            for obs in observaciones:
                try:
                    fecha_str = datetime.strptime(obs["indexDateString"], "%d-%m-%Y").strftime("%Y-%m-%d")
                    valor = float(obs["value"])

                    cur.execute('''
                        INSERT INTO indicadores (fecha, tipo, valor)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (fecha, tipo) DO UPDATE SET valor = EXCLUDED.valor
                    ''', (fecha_str, tipo, valor))
                except (ValueError, KeyError):
                    continue

        except Exception as ex:
            print(f"Error de conexión consultando la serie {tipo}: {ex}")

    conn.commit()
    cur.close()
    conn.close()
    print(f"Base de datos actualizada correctamente desde {start_date} hasta {end_date}.")


init_db()
fetch_and_save_data()

scheduler = BackgroundScheduler(timezone=pytz.timezone('America/Santiago'))
scheduler.add_job(fetch_and_save_data, 'cron', hour=8, minute=0)
scheduler.start()


def get_indicador_today(tipo):
    tz_chile = pytz.timezone('America/Santiago')
    hoy = datetime.now(tz_chile).strftime('%Y-%m-%d')

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute('SELECT valor FROM indicadores WHERE fecha = %s AND tipo = %s', (hoy, tipo))
        row = cur.fetchone()

        if not row:
            cur.execute('SELECT valor FROM indicadores WHERE fecha <= %s AND tipo = %s ORDER BY fecha DESC LIMIT 1',
                        (hoy, tipo))
            row = cur.fetchone()

        cur.close()
        conn.close()

        if row:
            return str(row[0])
        else:
            return f"Dato no encontrado para {tipo}", 404

    except Exception as e:
        return f"Error interno: {str(e)}", 500


# ----- ENDPOINTS -----

@app.route('/')
@app.route('/uf')
def uf_endpoint():
    return get_indicador_today('uf')


@app.route('/dolar')
def dolar_endpoint():
    return get_indicador_today('dolar')


@app.route('/plata')
def plata_endpoint():
    return get_indicador_today('plata')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5010)