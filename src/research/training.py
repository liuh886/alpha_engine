import json
import pickle
import shutil
from datetime import datetime
from pathlib import Path

from qlib.utils import init_instance_by_config

from src.common.logging import get_logger
from src.common.paths import MODELS_DIR

logger = get_logger(__name__)


def train_model(
    market: str,
    model_config: dict,
    dataset_config: dict,
    tag: str = "",
    snapshot_id: str = "",
) -> tuple[object, Path]:
    """Train a Qlib model.

    Parameters
    ----------
    snapshot_id : str, optional
        Content-addressed snapshot ID of the data used for this training
        run.  When provided, it is persisted alongside the model artifact
        so that the training run can be reproduced with the exact same data.
    """
    logger.info("Training model", market=market, snapshot_id=snapshot_id or None)
    dataset = init_instance_by_config(dataset_config)

    model = init_instance_by_config(model_config)
    model.fit(dataset)

    # Save Model
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    from src.common.text_utils import sanitize_tag

    safe_tag = sanitize_tag(tag)

    model_filename = (
        f"{market}_model_{safe_tag}_{timestamp}.pkl"
        if safe_tag
        else f"{market}_model_{timestamp}.pkl"
    )
    model_path = MODELS_DIR / model_filename
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    shutil.copy(model_path, MODELS_DIR / f"{market}_model.pkl")

    # Persist training metadata alongside the model so the run is
    # reproducible with the exact same data snapshot.
    if snapshot_id:
        meta = {
            "snapshot_id": snapshot_id,
            "market": market,
            "tag": safe_tag,
            "created_at": timestamp,
        }
        meta_path = model_path.with_suffix(".meta.json")
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        logger.info("Persisted model metadata", meta_path=str(meta_path))

    return model, model_path
