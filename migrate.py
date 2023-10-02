import sqlite3
from sqlite3 import Error
from datetime import datetime

# Database connection and management
def create_connection():
    conn = None;
    try:
        conn = sqlite3.connect('mydb.db') # create a persistent database
        return conn
    except Error as e:
        print(e)

conn = create_connection()
cursor = conn.cursor()


# Step 1: Create a new table for borrowed_assets with the same structure plus the timestamp column
cursor.execute('''CREATE TABLE IF NOT EXISTS borrowed_assets_new
                  (user_id text, asset text, amount integer, timestamp datetime default current_timestamp,
                   FOREIGN KEY(user_id) REFERENCES users(_id))''')

# Step 2: Copy all data from borrowed_assets to the new table
cursor.execute("INSERT INTO borrowed_assets_new (user_id, asset, amount) SELECT user_id, asset, amount FROM borrowed_assets")

# Step 3: Drop the old borrowed_assets table
cursor.execute("DROP TABLE borrowed_assets")

# Step 4: Rename the new table to borrowed_assets
cursor.execute("ALTER TABLE borrowed_assets_new RENAME TO borrowed_assets")

# Get the current datetime
current_time = datetime.now()

# Update all rows in the borrowed_assets table with the current timestamp
cursor.execute("UPDATE borrowed_assets SET timestamp = ?", (current_time,))

conn.commit()
conn.close()

