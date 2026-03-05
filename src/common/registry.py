import json
import uuid
import sqlite3
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from datetime import datetime

class ModelVersion(BaseModel):
    version_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    model_name: str
    architecture: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    metrics: Dict[str, float] = Field(default_factory=dict)
    hyperparameters: Dict[str, Any] = Field(default_factory=dict)
    stage: str = "Staging" # Staging | Production | Archived
    artifacts_path: Optional[str] = None
    
class MLRegistry:
    """
    Roadmap Item [90/22/23] Lightweight MLOps, MLflow-lite Registry
    A local, zero-dependency model tracking system mimicking MLflow's core database.
    Prevents overfitting by forcing all models to record immutable holdout metrics.
    """
    
    def __init__(self, db_path: str = "artifacts/registry.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS models (
                    version_id TEXT PRIMARY KEY,
                    model_name TEXT,
                    architecture TEXT,
                    created_at TEXT,
                    metrics TEXT,
                    hyperparameters TEXT,
                    stage TEXT,
                    artifacts_path TEXT
                )
            ''')
            
    def register_model(self, model: ModelVersion) -> str:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO models (version_id, model_name, architecture, created_at, metrics, hyperparameters, stage, artifacts_path) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (model.version_id, model.model_name, model.architecture, model.created_at, 
                 json.dumps(model.metrics), json.dumps(model.hyperparameters), model.stage, model.artifacts_path)
            )
        return model.version_id
        
    def transition_stage(self, version_id: str, new_stage: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE models SET stage=? WHERE version_id=?", (new_stage, version_id))
            
    def get_model(self, version_id: str) -> Optional[ModelVersion]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM models WHERE version_id=?", (version_id,)).fetchone()
            if row:
                d = dict(row)
                d['metrics'] = json.loads(d['metrics'])
                d['hyperparameters'] = json.loads(d['hyperparameters'])
                return ModelVersion(**d)
        return None
        
    def list_models(self, stage: str = None) -> List[ModelVersion]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if stage:
                rows = conn.execute("SELECT * FROM models WHERE stage=? ORDER BY created_at DESC", (stage,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM models ORDER BY created_at DESC").fetchall()
                
            out = []
            for row in rows:
                d = dict(row)
                d['metrics'] = json.loads(d['metrics'])
                d['hyperparameters'] = json.loads(d['hyperparameters'])
                out.append(ModelVersion(**d))
            return out
