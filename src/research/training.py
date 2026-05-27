import pickle
import shutil
from datetime import datetime
from pathlib import Path

from qlib.utils import init_instance_by_config

from src.common.logging import get_logger
from src.common.paths import MODELS_DIR

logger = get_logger(__name__)


def train_model(
    market: str, model_config: dict, dataset_config: dict, tag: str = ""
) -> tuple[object, Path]:
    """Train a Qlib model."""
    logger.info("Training model", market=market)
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

    return model, model_path
