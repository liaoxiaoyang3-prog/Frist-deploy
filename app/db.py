# app/db.py
import os
import mysql.connector

import os
import mysql.connector

def get_db_connection():
    # mysql-connector-python automatically negotiates SSL with Aiven by default
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 11780)), 
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )