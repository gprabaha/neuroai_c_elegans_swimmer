# src/train/run_train.py

import os
from tonic.utils import config_loader
from src.train.common import train

# Load YAML config
config_path = os.path.join(os.path.dirname(__file__), "../config/swimmer_ppo.yaml")
config = config_loader.load_config(config_path)

# Launch training
train(**config)
