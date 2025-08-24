import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()  # Carga las variables desde .envgit commit -m "Remueve .env del control de versiones"


def get_connection():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        database=os.environ.get("DB_NAME"),
        charset='utf8mb4',
        port=int(os.environ.get("DB_PORT", 3306))
    )

