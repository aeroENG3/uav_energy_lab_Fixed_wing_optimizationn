"""Train a PPO agent that sets airspeed/altitude in MISSION mode to minimise energy.
Requires: pip install stable-baselines3   (not needed by the rest of the lab)

    python examples/train_rl_sb3.py --steps 20000
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env

from uavlab.gym_env import UAVEnergyEnv

ap = argparse.ArgumentParser()
ap.add_argument("--steps", type=int, default=20000)
ap.add_argument("--envs", type=int, default=2)
a = ap.parse_args()

rand = {"wind.mean.speed_mps": {"uniform": [0.0, 9.0]},
        "wind.mean.from_deg": {"uniform": [0.0, 360.0]},
        "wind.turbulence.model": {"choice": ["none", "dryden"]}}
env = make_vec_env(lambda: UAVEnergyEnv(("configs/missions/out_and_back.yaml",), decision_dt_s=4.0,
                                        randomize=rand), n_envs=a.envs)
model = PPO("MlpPolicy", env, verbose=1, n_steps=256, batch_size=128, gamma=0.995)
model.learn(total_timesteps=a.steps)
model.save("ppo_uav_energy")
print("saved ppo_uav_energy.zip")
