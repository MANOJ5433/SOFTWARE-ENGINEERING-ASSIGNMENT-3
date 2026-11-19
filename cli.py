"""Command-line helpers.

Local SQLite example (no Docker):
    python -m app.cli init-db --url sqlite:///campus.db
PostgreSQL (Docker runs this automatically from db/init, so this is only needed for manual setups):
    python -m app.cli init-db --url postgresql://campus:campus@localhost:5432/campus
"""
import argparse
import os

from .config import Config
from .db import connect, sqlite_statements


def init_db(url, directory):
    tx = connect(url)
    for name in ("01_schema.sql", "02_seed.sql"):
        with open(os.path.join(directory, name), encoding="utf-8") as handle:
            sql = handle.read()
        if tx.sqlite:
            for statement in sqlite_statements(sql):
                tx.conn.execute(statement)
        else:
            cur = tx.conn.cursor()
            cur.execute(sql)
            tx.conn.commit()
        print(f"applied {name}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Smart Campus helper commands")
    parser.add_argument("command", choices=["init-db"])
    parser.add_argument("--url", default=Config.DATABASE_URL)
    parser.add_argument("--dir", default=os.path.join(os.path.dirname(__file__), "..", "..", "db", "init"))
    args = parser.parse_args(argv)
    if args.command == "init-db":
        init_db(args.url, args.dir)


if __name__ == "__main__":
    main()
