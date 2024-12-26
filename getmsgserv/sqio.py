import os
import sqlite3
import subprocess

# Constants for database path and named pipe files
DB_PATH = "cache/OQQWall.db"  # Path to the SQLite database file
SQIOIN = "sqioin"            # Name of the input named pipe
SQIOOUT = "sqioout"          # Name of the output named pipe

print("SQIO服务已启动")  # Log message indicating the service has started

# Create named pipes if they do not exist
if not os.path.exists(SQIOIN):
    os.mkfifo(SQIOIN)  # Create input pipe for receiving SQL queries
if not os.path.exists(SQIOOUT):
    os.mkfifo(SQIOOUT)  # Create output pipe for sending query results
    print("sqio管道创建完毕")  # Log message indicating pipes are set up

try:
    while True:
        # Open sqioin pipe for reading SQL queries
        with open(SQIOIN, 'r') as input_pipe:
            sql_query = input_pipe.read().strip()  # Read and trim whitespace from the query
            if not sql_query:  # Skip if the query is empty
                continue

        # Execute the SQL query on the SQLite database
        try:
            conn = sqlite3.connect(DB_PATH)  # Connect to the SQLite database
            cursor = conn.cursor()  # Create a cursor object for executing queries
            cursor.execute(sql_query)  # Execute the received SQL query
            results = cursor.fetchall()  # Fetch all results from the query
            conn.commit()  # Commit any changes for write queries
        except sqlite3.Error as e:
            # Capture and log any SQLite errors encountered during execution
            results = [[f"Error: {str(e)}"]]  # Format the error message as a result
        finally:
            conn.close()  # Ensure the database connection is closed

        # Write the query results to the sqioout pipe
        with open(SQIOOUT, 'w') as output_pipe:
            for row in results:
                # Convert each row to a string with '|' as a delimiter and write to pipe
                output_pipe.write("|".join(map(str, row)) + "\n")

except KeyboardInterrupt:
    print("SQIOExiting...")  # Log message for manual interruption
finally:
    # Cleanup pipes when the program terminates
    if os.path.exists(SQIOIN):
        os.remove(SQIOIN)  # Remove input pipe
    if os.path.exists(SQIOOUT):
        os.remove(SQIOOUT)  # Remove output pipe