import os
from pathlib import Path

import fire
import yaml
from tabulate import tabulate


class ModelManager:
    def __init__(self):
        self.list_path = Path("models/model_list.yaml")
        
    def _load(self):
        if self.list_path.exists():
            with open(self.list_path) as f:
                return yaml.safe_load(f) or {"models": []}
        return {"models": []}
        
    def _save(self, data):
        with open(self.list_path, 'w') as f:
            yaml.dump(data, f, sort_keys=False)

    def register(self, path, market, model_type="Unknown", metrics=None, description="Manual registration"):
        """
        Manually register a model file.
        Args:
            path: Path to the .pkl file
            market: 'cn', 'us', or other identifier
            model_type: 'LinearModel', 'LGBModel', etc.
            metrics: Dict or string of metrics (optional)
            description: Brief note
        """
        path = Path(path)
        if not path.exists():
            print(f"Error: File not found at {path}")
            return

        data = self._load()
        from datetime import datetime
        
        # Safe metric parsing
        if metrics and isinstance(metrics, str):
            try:
                import ast
                metrics = ast.literal_eval(metrics)
            except:
                metrics = {"raw": metrics}
        
        entry = {
            "id": f"{market}_{model_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "path": str(path).replace("\\", "/"),
            "type": model_type,
            "market": market,
            "created_at": str(datetime.now().date()),
            "description": description,
            "backtest": {
                "metrics": metrics or {}
            }
        }
        
        data["models"].append(entry)
        self._save(data)
        print(f"Successfully registered: {entry['id']}")

    def list(self):
        """List all registered models."""
        data = self._load()
        models = data.get("models", [])
        
        if not models:
            print("No models registered.")
            return
            
        table = []
        for m in models:
            metrics = m.get("backtest", {}).get("metrics", {})
            ret = metrics.get("annualized_return", "N/A")
            ir = metrics.get("information_ratio", "N/A")
            if isinstance(ret, float): ret = f"{ret:.2%}"
            if isinstance(ir, float): ir = f"{ir:.2f}"
            
            table.append([
                m['id'], 
                m['market'], 
                m['type'], 
                m['created_at'], 
                ret,
                ir
            ])
            
        print(tabulate(table, headers=["ID", "Market", "Type", "Created", "Ann. Ret", "IR"], tablefmt="simple"))

    def delete(self, model_id):
        """Delete a model by ID (files and registry entry)."""
        data = self._load()
        models = data.get("models", [])
        
        target = next((m for m in models if m['id'] == model_id), None)
        if not target:
            print(f"Model ID '{model_id}' not found.")
            return
            
        # Remove file
        path = Path(target['path'])
        if path.exists():
            try:
                os.remove(path)
                print(f"Deleted file: {path}")
            except Exception as e:
                print(f"Error deleting file: {e}")
        else:
            print(f"File not found: {path}")
            
        # Remove from registry
        data["models"] = [m for m in models if m['id'] != model_id]
        self._save(data)
        print(f"Removed '{model_id}' from registry.")

if __name__ == "__main__":
    fire.Fire(ModelManager)
