# src/main.py

from src.train.common import train

if __name__ == "__main__":
    train("configs/swimmer_ppo.yaml")
