import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host="miappdb.c7u6giqeygpc.us-east-2.rds.amazonaws.com",  # punto de enlace RDS
        user="admin",
        password="Lunita1808",
        database='futbol',
        charset='utf8mb4',
        port=3306  # puerto de MySQL, aunque mysql.connector lo pone por defecto
    )
