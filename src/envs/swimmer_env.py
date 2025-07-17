# src/envs/swimmer_env.py
from tonic.environments import ControlSuite

def SwimmerEnv():
    return ControlSuite('swimmer-swim', time_feature=True)
