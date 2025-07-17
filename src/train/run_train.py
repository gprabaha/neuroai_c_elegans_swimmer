# src/train/run_train.py

import os
import sys
from tonic.utils import config_loader
from src.train.common import train

def main():
    config_path = os.path.join(os.path.dirname(__file__), "../../configs/swimmer_ppo.yaml")
    config = config_loader.load_config(config_path)
    train(**config)

if __name__ == "__main__":
    main()
