import os
import time
from datetime import datetime, timedelta
from flask import Flask
import psycopg2
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
import bcchapi
import pandas as pd

app = Flask(__name__)

# Variables BD
DB_HOST = os.environ.get("DB_HOST", "db")
DB_NAME = os.environ.get("DB_NAME", "uf_db")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASS = os.environ.get("DB_PASS", "postgres")

# Token Banco Central (Inyectado por Coolify)
BCC_TOKEN = os.environ.get("BCC_TOKEN", "tu_token")


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
            print("Esperando a PostgreSQL...")
            retries -= 1
            time.sleep(3)


def fetch_and_save_uf():
    print("Consultando API oficial del Banco Central de Chile...")
    try:
        # Instanciamos usando únicamente el token
        siete = bcchapi.Siete(token=BCC_TOKEN)

        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

        df = siete.cuadro({"UF": "F073.UFF.PRE.Z.D"}, start=start_date, end=end_date)

        conn = get_db_connection()
        cur = conn.cursor()

        for date_index, row in df.iterrows():
            fecha_str = date_index.strftime('%Y-%m-%d')
            valor = float(row['UF'])

            if pd.notna(valor):
                cur.execute('''
                    INSERT INTO uf_data (fecha, valor)
                    VALUES (%s, %s)
                    ON CONFLICT (fecha) DO UPDATE SET valor = EXCLUDED.valor
                ''', (fecha_str, valor))

        conn.commit()
        cur.close()
        conn.close()
        print("Base de datos actualizada con datos del Banco Central.")
    except Exception as e:
        print(f"Error consultando al BCCh: {e}")


init_db()
fetch_and_save_uf()

scheduler = BackgroundScheduler(timezone=pytz.timezone('America/Santiago'))
scheduler.add_job(fetch_and_save_uf, 'cron', hour=8, minute=0)
scheduler.start()


@app.route('/')
@app.route('/uf')
def get_uf_today():
    tz_chile = pytz.timezone('America/Santiago')
    hoy = datetime.now(tz_chile).strftime('%Y-%m-%d')

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute('SELECT valor FROM uf_data WHERE fecha = %s', (hoy,))
        row = cur.fetchone()

        if not row:
            cur.execute('SELECT valor FROM uf_data WHERE fecha <= %s ORDER BY fecha DESC LIMIT 1', (hoy,))
            row = cur.fetchone()

        cur.close()
        conn.close()

        if row:
            return str(row[0])
        else:
            return "Dato no encontrado", 404

    except Exception as e:
        return f"Error interno: {str(e)}", 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5010)