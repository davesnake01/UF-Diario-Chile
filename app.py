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

# Token Banco Central
BCC_TOKEN = os.environ.get("BCC_TOKEN", "tu_token")

# Diccionario con los códigos de las series oficiales del BCCh
SERIES = {
    "uf": "F073.UFF.PRE.Z.D",
    "dolar": "F073.TCO.PRE.Z.D",
    "plata": "F073.CMB.PLA.Z.D"
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
    print("Consultando API oficial del Banco Central de Chile...")
    try:
        siete = bcchapi.Siete(BCC_TOKEN)

        # Calculamos las fechas en el formato 'YYYY-MM-DD' que pide la documentación
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

        conn = get_db_connection()
        cur = conn.cursor()

        for tipo, serie in SERIES.items():
            try:
                # Aplicamos la sintaxis exacta de la documentación
                df = siete.cuadro(
                    series=[serie],
                    desde=start_date,
                    hasta=end_date,
                    nombres=[tipo]
                )

                for date_index, row in df.iterrows():
                    fecha_str = date_index.strftime('%Y-%m-%d')
                    valor = float(row[tipo])

                    # pd.notna() evita que guardemos los 'NaN' de días sin publicación (ej. fines de semana)
                    if pd.notna(valor):
                        cur.execute('''
                            INSERT INTO indicadores (fecha, tipo, valor)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (fecha, tipo) DO UPDATE SET valor = EXCLUDED.valor
                        ''', (fecha_str, tipo, valor))
            except Exception as ex:
                print(f"Advertencia consultando serie {tipo} ({serie}): {ex}")

        conn.commit()
        cur.close()
        conn.close()
        print(f"Base de datos actualizada correctamente desde {start_date} hasta {end_date}.")
    except Exception as e:
        print(f"Error general consultando al BCCh: {e}")


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
    # Puerto ajustado a 5010
    app.run(host='0.0.0.0', port=5010)