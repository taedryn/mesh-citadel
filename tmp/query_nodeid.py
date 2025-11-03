import sqlite3
import sys


def main():
    dbfile = "../citadel.db"
    node_id = sys.argv[1]
    query_id = node_id + '%'

    conn = sqlite3.connect(dbfile)
    query = "SELECT node_id, name FROM mc_chat_contacts WHERE node_id LIKE ?"

    cur = conn.execute(query, [query_id])
    rows = cur.fetchall()
    cur.close()

    print(f'Nodes matching {node_id}:')
    for row in rows:
        print(f'{row[0]}: {row[1]}')

if __name__ == '__main__':
    main()
