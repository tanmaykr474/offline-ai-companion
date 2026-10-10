import os, sys
from offline_ai_companion.memory.database import Database
with Database(sys.argv[1]).connect() as connection:
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("UPDATE facts SET value = 'Java'")
    connection.execute("INSERT INTO tasks(title) VALUES ('Uncommitted task')")
    os._exit(23)
