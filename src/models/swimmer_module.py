# Placeholder for SwimmerModule neural architecture.# src/models/swimmer.py

import torch
import torch.nn as nn
import numpy as np
from tonic.torch import models, normalizers



# ==================================================================================================
# Weight constraints.


def excitatory(w, upper=None):
    return w.clamp(min=0, max=upper)


def inhibitory(w, lower=None):
    return w.clamp(min=lower, max=0)


def unsigned(w, lower=None, upper=None):
    return w if lower is None and upper is None else w.clamp(min=lower, max=upper)


# ==================================================================================================
# Activation constraints.


def graded(x):
    return x.clamp(min=0, max=1)


# ==================================================================================================
# Weight initialization.


def excitatory_uniform(shape=(1,), lower=0., upper=1.):
    assert lower >= 0
    return nn.init.uniform_(nn.Parameter(torch.empty(shape)), a=lower, b=upper)


def inhibitory_uniform(shape=(1,), lower=-1., upper=0.):
    assert upper <= 0
    return nn.init.uniform_(nn.Parameter(torch.empty(shape)), a=lower, b=upper)


def unsigned_uniform(shape=(1,), lower=-1., upper=1.):
    return nn.init.uniform_(nn.Parameter(torch.empty(shape)), a=lower, b=upper)


def excitatory_constant(shape=(1,), value=1.):
    return nn.Parameter(torch.full(shape, value))


def inhibitory_constant(shape=(1,), value=-1.):
    return nn.Parameter(torch.full(shape, value))


def unsigned_constant(shape=(1,), lower=-1., upper=1., p=0.5):
    with torch.no_grad():
        weight = torch.empty(shape).uniform_(0, 1)
        mask = weight < p
        weight[mask] = upper
        weight[~mask] = lower
        return nn.Parameter(weight)


# ==================================================================================================
# Classes

class SwimmerModule(nn.Module):
    """C.-elegans-inspired neural circuit architectural prior."""

    def __init__(
            self,
            n_joints: int,
            n_turn_joints: int = 1,
            oscillator_period: int = 60,
            use_weight_sharing: bool = True,
            use_weight_constraints: bool = True,
            use_weight_constant_init: bool = True,
            include_proprioception: bool = True,
            include_head_oscillators: bool = True,
            include_speed_control: bool = False,
            include_turn_control: bool = False,
    ):
        super().__init__()
        self.n_joints = n_joints
        self.n_turn_joints = n_turn_joints
        self.oscillator_period = oscillator_period
        self.include_proprioception = include_proprioception
        self.include_head_oscillators = include_head_oscillators
        self.include_speed_control = include_speed_control
        self.include_turn_control = include_turn_control

        # Log activity
        self.connections_log = []

        # Timestep counter (for oscillations).
        self.timestep = 0

        # Weight sharing switch function.
        self.ws = lambda nonshared, shared: shared if use_weight_sharing else nonshared

        # Weight constraint and init functions.
        if use_weight_constraints:
            self.exc = excitatory
            self.inh = inhibitory
            if use_weight_constant_init:
                exc_param = excitatory_constant
                inh_param = inhibitory_constant
            else:
                exc_param = excitatory_uniform
                inh_param = inhibitory_uniform
        else:
            self.exc = unsigned
            self.inh = unsigned
            if use_weight_constant_init:
                exc_param = inh_param = unsigned_constant
            else:
                exc_param = inh_param = unsigned_uniform

        # Learnable parameters.
        self.params = nn.ParameterDict()
        if use_weight_sharing:
            if self.include_proprioception:
                self.params['bneuron_prop'] = exc_param()
            if self.include_speed_control:
                self.params['bneuron_speed'] = inh_param()
            if self.include_turn_control:
                self.params['bneuron_turn'] = exc_param()
            if self.include_head_oscillators:
                self.params['bneuron_osc'] = exc_param()
            self.params['muscle_ipsi'] = exc_param()
            self.params['muscle_contra'] = inh_param()
        else:
            for i in range(self.n_joints):
                if self.include_proprioception and i > 0:
                    self.params[f'bneuron_d_prop_{i}'] = exc_param()
                    self.params[f'bneuron_v_prop_{i}'] = exc_param()

                if self.include_speed_control:
                    self.params[f'bneuron_d_speed_{i}'] = inh_param()
                    self.params[f'bneuron_v_speed_{i}'] = inh_param()

                if self.include_turn_control and i < self.n_turn_joints:
                    self.params[f'bneuron_d_turn_{i}'] = exc_param()
                    self.params[f'bneuron_v_turn_{i}'] = exc_param()

                if self.include_head_oscillators and i == 0:
                    self.params[f'bneuron_d_osc_{i}'] = exc_param()
                    self.params[f'bneuron_v_osc_{i}'] = exc_param()

                self.params[f'muscle_d_d_{i}'] = exc_param()
                self.params[f'muscle_d_v_{i}'] = inh_param()
                self.params[f'muscle_v_v_{i}'] = exc_param()
                self.params[f'muscle_v_d_{i}'] = inh_param()

    def reset(self):
        self.timestep = 0

    def log_activity(self, activity_type, neuron):
        """Logs an active connection between neurons."""
        self.connections_log.append((self.timestep, activity_type, neuron))

    def forward(
            self,
            joint_pos,
            right_control=None,
            left_control=None,
            speed_control=None,
            timesteps=None,
            log_activity=True,
            log_file='log.txt'
    ):
        """Forward pass.

    Args:
      joint_pos (torch.Tensor): Joint positions in [-1, 1], shape (..., n_joints).
      right_control (torch.Tensor): Right turn control in [0, 1], shape (..., 1).
      left_control (torch.Tensor): Left turn control in [0, 1], shape (..., 1).
      speed_control (torch.Tensor): Speed control in [0, 1], 0 stopped, 1 fastest, shape (..., 1).
      timesteps (torch.Tensor): Timesteps in [0, max_env_steps], shape (..., 1).

    Returns:
      (torch.Tensor): Joint torques in [-1, 1], shape (..., n_joints).
    """

        exc = self.exc
        inh = self.inh
        ws = self.ws

        # Separate into dorsal and ventral sensor values in [0, 1], shape (..., n_joints).
        joint_pos_d = joint_pos.clamp(min=0, max=1)
        joint_pos_v = joint_pos.clamp(min=-1, max=0).neg()

        # Convert speed signal from acceleration into brake.
        if self.include_speed_control:
            assert speed_control is not None
            speed_control = 1 - speed_control.clamp(min=0, max=1)

        joint_torques = []  # [shape (..., 1)]
        for i in range(self.n_joints):
            bneuron_d = bneuron_v = torch.zeros_like(joint_pos[..., 0, None])  # shape (..., 1)

            # B-neurons recieve proprioceptive input from previous joint to propagate waves down the body.
            if self.include_proprioception and i > 0:
                bneuron_d = bneuron_d + joint_pos_d[
                    ..., i - 1, None] * exc(self.params[ws(f'bneuron_d_prop_{i}', 'bneuron_prop')])
                bneuron_v = bneuron_v + joint_pos_v[
                    ..., i - 1, None] * exc(self.params[ws(f'bneuron_v_prop_{i}', 'bneuron_prop')])
                self.log_activity('exc', f'bneuron_d_prop_{i}')
                self.log_activity('exc', f'bneuron_v_prop_{i}')

            # Speed control unit modulates all B-neurons.
            if self.include_speed_control:
                bneuron_d = bneuron_d + speed_control * inh(
                    self.params[ws(f'bneuron_d_speed_{i}', 'bneuron_speed')]
                )
                bneuron_v = bneuron_v + speed_control * inh(
                    self.params[ws(f'bneuron_v_speed_{i}', 'bneuron_speed')]
                )
                self.log_activity('inh', f'bneuron_d_speed_{i}')
                self.log_activity('inh', f'bneuron_v_speed_{i}')

            # Turn control units modulate head B-neurons.
            if self.include_turn_control and i < self.n_turn_joints:
                assert right_control is not None
                assert left_control is not None
                turn_control_d = right_control.clamp(min=0, max=1)  # shape (..., 1)
                turn_control_v = left_control.clamp(min=0, max=1)
                bneuron_d = bneuron_d + turn_control_d * exc(
                    self.params[ws(f'bneuron_d_turn_{i}', 'bneuron_turn')]
                )
                bneuron_v = bneuron_v + turn_control_v * exc(
                    self.params[ws(f'bneuron_v_turn_{i}', 'bneuron_turn')]
                )
                self.log_activity('exc', f'bneuron_d_turn_{i}')
                self.log_activity('exc', f'bneuron_v_turn_{i}')

            # Oscillator units modulate first B-neurons.
            if self.include_head_oscillators and i == 0:
                if timesteps is not None:
                    phase = timesteps.round().remainder(self.oscillator_period)
                    mask = phase < self.oscillator_period // 2
                    oscillator_d = torch.zeros_like(timesteps)  # shape (..., 1)
                    oscillator_v = torch.zeros_like(timesteps)  # shape (..., 1)
                    oscillator_d[mask] = 1.
                    oscillator_v[~mask] = 1.
                else:
                    phase = self.timestep % self.oscillator_period  # in [0, oscillator_period)
                    if phase < self.oscillator_period // 2:
                        oscillator_d, oscillator_v = 1.0, 0.0
                    else:
                        oscillator_d, oscillator_v = 0.0, 1.0
                bneuron_d = bneuron_d + oscillator_d * exc(
                    self.params[ws(f'bneuron_d_osc_{i}', 'bneuron_osc')]
                )
                bneuron_v = bneuron_v + oscillator_v * exc(
                    self.params[ws(f'bneuron_v_osc_{i}', 'bneuron_osc')]
                )

                self.log_activity('exc', f'bneuron_d_osc_{i}')
                self.log_activity('exc', f'bneuron_v_osc_{i}')

            # B-neuron activation.
            bneuron_d = graded(bneuron_d)
            bneuron_v = graded(bneuron_v)

            # Muscles receive excitatory ipsilateral and inhibitory contralateral input.
            muscle_d = graded(
                bneuron_d * exc(self.params[ws(f'muscle_d_d_{i}', 'muscle_ipsi')]) +
                bneuron_v * inh(self.params[ws(f'muscle_d_v_{i}', 'muscle_contra')])
            )
            muscle_v = graded(
                bneuron_v * exc(self.params[ws(f'muscle_v_v_{i}', 'muscle_ipsi')]) +
                bneuron_d * inh(self.params[ws(f'muscle_v_d_{i}', 'muscle_contra')])
            )

            # Joint torque from antagonistic contraction of dorsal and ventral muscles.
            joint_torque = muscle_d - muscle_v
            joint_torques.append(joint_torque)

        self.timestep += 1

        out = torch.cat(joint_torques, -1)  # shape (..., n_joints)
        return out



class SwimmerActor(nn.Module):
    def __init__(
            self,
            swimmer,
            controller=None,
            distribution=None,
            timestep_transform=(-1, 1, 0, 1000),
    ):
        super().__init__()
        self.swimmer = swimmer
        self.controller = controller
        self.distribution = distribution
        self.timestep_transform = timestep_transform

    def initialize(
            self,
            observation_space,
            action_space,
            observation_normalizer=None,
    ):
        self.action_size = action_space.shape[0]

    def forward(self, observations):
        joint_pos = observations[..., :self.action_size]
        timesteps = observations[..., -1, None]

        # Normalize joint positions by max joint angle (in radians).
        joint_limit = 2 * np.pi / (self.action_size + 1)  # In dm_control, calculated with n_bodies.
        joint_pos = torch.clamp(joint_pos / joint_limit, min=-1, max=1)

        # Convert normalized time signal into timestep.
        if self.timestep_transform:
            low_in, high_in, low_out, high_out = self.timestep_transform
            timesteps = (timesteps - low_in) / (high_in - low_in) * (high_out - low_out) + low_out

        # Generate high-level control signals.
        if self.controller:
            right, left, speed = self.controller(observations)
        else:
            right, left, speed = None, None, None

        # Generate low-level action signals.
        actions = self.swimmer(
            joint_pos,
            timesteps=timesteps,
            right_control=right,
            left_control=left,
            speed_control=speed,
        )

        # Pass through distribution for stochastic policy.
        if self.distribution:
            actions = self.distribution(actions)

        return actions




def ppo_swimmer_model(
    n_joints=5,
    action_noise=0.1,
    critic_sizes=(64, 64),
    critic_activation=nn.Tanh,
    **swimmer_kwargs,
):
    return models.ActorCritic(
        actor=SwimmerActor(
            swimmer=SwimmerModule(n_joints=n_joints, **swimmer_kwargs),
            distribution=lambda x: torch.distributions.normal.Normal(x, action_noise),
        ),
        critic=models.Critic(
            encoder=models.ObservationEncoder(),
            torso=models.MLP(critic_sizes, critic_activation),
            head=models.ValueHead(),
        ),
        observation_normalizer=normalizers.MeanStd(),
    )

def d4pg_swimmer_model(
    n_joints=5,
    critic_sizes=(256, 256),
    critic_activation=nn.ReLU,
    **swimmer_kwargs,
):
    return models.ActorCriticWithTargets(
        actor=SwimmerActor(
            swimmer=SwimmerModule(n_joints=n_joints, **swimmer_kwargs),
        ),
        critic=models.Critic(
            encoder=models.ObservationActionEncoder(),
            torso=models.MLP(critic_sizes, critic_activation),
            head=models.DistributionalValueHead(-150., 150., 51),
        ),
        observation_normalizer=normalizers.MeanStd(),
    )
