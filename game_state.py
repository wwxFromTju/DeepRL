# -*- coding: utf-8 -*-
import sys
import numpy as np
import gym

import cv2
import atari_py

from constants import GYM_ENV
from constants import ACTION_SIZE

class AtariEnvSkipping(gym.Wrapper):
    def __init__(self, env, frameskip=4):
        self.env = env
        self.env.ale.setFloat('frame_skip'.encode('utf-8'), frameskip)
        self.env.ale.setFloat('repeat_action_probability'.encode('utf-8'), 0.0)
        self.env._seed()

        print ("lives={}".format(self.env.ale.lives()))
        print ("frameskip={}".format(self.env.ale.getFloat(b'frame_skip')))
        print ("repeat_action_probability={}".format(self.env.ale.getFloat(b'repeat_action_probability')))
        print ("action space={}".format(self.env.action_space.n))

    def _step(self, a):
        reward = 0.0
        action = self.env._action_set[a]

        reward += self.env.ale.act(action)
        ob = self.env._get_obs()

        return ob, reward, self.env.ale.game_over(), {"ale.lives": self.env.ale.lives()}

class GameState(object):
  def __init__(self, display=False, crop_screen=True, frame_skip=4, no_op_max=30):
    self._display = display
    self._crop_screen = crop_screen
    self._frame_skip = frame_skip
    if self._frame_skip < 1:
      self._frame_skip = 1
    self._no_op_max = no_op_max
    self.env_id = GYM_ENV

    self.env = gym.make(GYM_ENV)
    self.env = AtariEnvSkipping(self.env, frameskip=self._frame_skip)

    self.reset()

  def _process_frame(self, action, reshape):
    reward = 0
    observation, r, terminal, _ = self.env.step(action)
    reward += r

    grayscale_observation = cv2.cvtColor(observation, cv2.COLOR_RGB2GRAY)

    if self._crop_screen:
      resized_observation = grayscale_observation.astype(np.float32)
      # crop to fit 84x84
      x_t = resized_observation[34:34+160, :160]
      x_t = cv2.resize(x_t, (84, 84))
    else:
      # resize to height=84, width=84
      resized_observation = cv2.resize(grayscale_observation, (84,84))
      x_t = resized_observation.astype(np.float32)

    if reshape:
      x_t = np.reshape(x_t, (84, 84, 1))

    # normalize
    x_t *= (1.0/255.0)
    return reward, terminal, x_t

  def reset(self):
    self.env.reset()

    # randomize initial state
    if self._no_op_max > 0:
      no_op = np.random.randint(0, self._no_op_max + 1)
      for _ in range(no_op):
        self.env.step(0)

    _, _, x_t = self._process_frame(0, False)

    self.reward = 0
    self.terminal = False
    self.s_t = np.stack((x_t, x_t, x_t, x_t), axis = 2)

  def process(self, action):
    if self._display:
      self.env.render()

    r, t, x_t1 = self._process_frame(action, True)

    self.reward = r
    self.terminal = t
    self.s_t1 = np.append(self.s_t[:,:,1:], x_t1, axis = 2)

  def update(self):
    self.s_t = self.s_t1
