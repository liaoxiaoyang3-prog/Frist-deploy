import os
import mysql.connector
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

# Load your database credentials from the .env file
load_dotenv()

def migrate_passwords():
    print("Connecting to the database...")
    try:
        conn = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME")
        )
        cursor = conn.cursor(dictionary=True)
        
        # 1. Only fetch email and user_password (removing 'id')
        cursor.execute("SELECT email, user_password FROM users")
        users = cursor.fetchall()
        
        print(f"Found {len(users)} users. Checking for plain-text passwords...")
        updated_count = 0

        for user in users:
            current_password = user['user_password']
            user_email = user['email']
            
            # 2. Check if the password is ALREADY hashed
            if not current_password.startswith(('scrypt:', 'pbkdf2:')):
                print(f"-> Hashing plain-text password for: {user_email}")
                
                # 3. Generate the secure hash
                secure_hash = generate_password_hash(current_password, method='scrypt')
                
                # 4. Update this user's row using their unique email instead of an id
                update_cursor = conn.cursor()
                update_cursor.execute(
                    "UPDATE users SET user_password = %s WHERE email = %s",
                    (secure_hash, user_email)
                )
                update_cursor.close()
                updated_count += 1
        
        # Save all changes to the database
        conn.commit()
        
        cursor.close()
        conn.close()
        print(f"\nSuccess! Successfully hashed {updated_count} old plain-text passwords.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    migrate_passwords()