import pickle
import shutil
from datetime import datetime
from pathlib import Path
from qlib.utils import init_instance_by_config
from qlib.data.dataset.handler import DataHandler
from src.common.paths import MODELS_DIR
from src.data.dim_reduction import DimensionalityReducer

def train_model(
    market: str, 
    model_config: dict, 
    dataset_config: dict, 
    tag: str = ""
) -> tuple[object, object, Path]:
    """
    Train a Qlib model with PCA dimensionality reduction.
    """
    print("Training Model...")
    dataset = init_instance_by_config(dataset_config)

    # Extract training features and reduce dimensionality via PCA
    try:
        train_features = dataset.prepare(segments="train", col_set="feature", data_key="feature")
    except KeyError:
        train_features = dataset.prepare(segments="train", col_set="feature", data_key=DataHandler.DK_I)

    reducer = DimensionalityReducer(variance_retained=0.95)
    reduced_train_features = reducer.fit_transform(train_features)

    print(f"PCA Reduced dimensions from {train_features.shape[1]} to {reduced_train_features.shape[1]}")

    model = init_instance_by_config(model_config)
    model.fit(dataset)

    # Save Model & Reducer
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    from src.common.text_utils import sanitize_tag
    safe_tag = sanitize_tag(tag)
    
    model_filename = f"{market}_model_{safe_tag}_{timestamp}.pkl" if safe_tag else f"{market}_model_{timestamp}.pkl"
    model_path = MODELS_DIR / model_filename
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    with open(MODELS_DIR / f"{market}_reducer.pkl", "wb") as f:
        pickle.dump(reducer, f)
    shutil.copy(model_path, MODELS_DIR / f"{market}_model.pkl")
    
    return model, reducer, model_path
