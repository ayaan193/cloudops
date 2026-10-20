
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    """Connect to the CloudOps PostgreSQL database."""
    return psycopg.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        connect_timeout=5,
    )


def init_db():
    """Create the incidents table if it does not exist."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                id BIGSERIAL PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                description TEXT NOT NULL,
                namespace VARCHAR(100) NOT NULL DEFAULT 'cloudops-lab',
                resource_name VARCHAR(200),
                severity VARCHAR(20) NOT NULL DEFAULT 'medium'
                    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
                status VARCHAR(20) NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'investigating', 'resolved')),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
