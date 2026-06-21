from __future__ import annotations

import time
import uuid

from src.assistant.base_index import BaseIndex


class DataProvenanceIndex(BaseIndex):
    """
    Persistence for data fetch provenance (source, fallback, errors).
    """

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS data_provenance (
                    id TEXT PRIMARY KEY,
                    symbol TEXT,
                    market TEXT,
                    source_used TEXT,
                    fallback_used INTEGER,
                    code TEXT,
                    created_at REAL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_data_prov_symbol ON data_provenance(symbol)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_data_prov_market ON data_provenance(market)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_data_prov_created ON data_provenance(created_at)"
            )

    def record(
        self,
        *,
        symbol: str,
        market: str,
        source_used: str | None = None,
        fallback_used: bool = False,
        code: str | None = None,
    ) -> str:
        row_id = uuid.uuid4().hex
        created_at = time.time()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO data_provenance (id, symbol, market, source_used, fallback_used, code, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row_id,
                    str(symbol or ""),
                    str(market or ""),
                    str(source_used or ""),
                    1 if fallback_used else 0,
                    str(code or ""),
                    created_at,
                ),
            )
        return row_id

    def list_recent(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM data_provenance ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
