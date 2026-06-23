import os
# 1. CHANGE THIS LINE: Import the pooling tool instead of the raw connector
from mysql.connector import pooling 

# 2. ADD THIS BLOCK: This creates a permanent cluster of 5 open connections 
# that stay "warmed up" in the background the moment your app boots.
db_pool = pooling.MySQLConnectionPool(
    pool_name="embu_pool",
    pool_size=5,  
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT", 11780)), 
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME")
)

# 3. MODIFY YOUR FUNCTION: Instead of creating a brand new connection from scratch,
# it instantly grabs one of the already-open connections from the pool.
def get_db_connection():
    return db_pool.get_connection()