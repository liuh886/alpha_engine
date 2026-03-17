import qlib
from pathlib import Path
import threading

_qlib_lock = threading.Lock()
_initialized_regions = set()

def ensure_qlib_init(provider_uri: str, region: str = "cn"):
    """
    Ensures Qlib is initialized only once per region within a single process.
    Thread-safe implementation for MCP/API server environments.
    """
    global _initialized_regions
    
    with _qlib_lock:
        cache_key = f"{provider_uri}_{region}"
        if cache_key in _initialized_regions:
            return True
            
        print(f"[*] Initializing Qlib for region: {region} (URI: {provider_uri})...")
        try:
            # If Qlib was already initialized by another call with same settings, 
            # qlib.init is usually fast but we skip it entirely to be sure.
            qlib.init(provider_uri=str(provider_uri), region=region)
            _initialized_regions.add(cache_key)
            print(f"[OK] Qlib initialized successfully.")
            return True
        except Exception as e:
            print(f"[!] Qlib initialization failed: {e}")
            return False

def get_qlib_status():
    """Returns a summary of initialized Qlib instances."""
    return list(_initialized_regions)
