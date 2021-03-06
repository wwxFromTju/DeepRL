#!/usr/bin/env python3
import tensorflow as tf
import numpy as np
import logging

from abc import ABC, abstractmethod
from termcolor import colored

logger = logging.getLogger("network")

# Base Class
class Network(ABC):
    use_mnih_2015 = False
    l1_beta = 0. #NOT USED
    l2_beta = 0. #0.0001
    use_gpu = True

    def __init__(self,
                 action_size,
                 thread_index, # -1 for global
                 device="/cpu:0"):
        self.action_size = action_size
        self._thread_index = thread_index
        self._device = device

    @abstractmethod
    def prepare_loss(self):
        raise NotImplementedError()

    @abstractmethod
    def prepare_evaluate(self):
        raise NotImplementedError()

    @abstractmethod
    def load(self, sess, checkpoint):
        raise NotImplementedError()

    @abstractmethod
    def run_policy_and_value(self, sess, s_t):
        raise NotImplementedError()

    @abstractmethod
    def run_policy(self, sess, s_t):
        raise NotImplementedError()

    @abstractmethod
    def run_value(self, sess, s_t):
        raise NotImplementedError()

    @abstractmethod
    def get_vars(self):
        raise NotImplementedError()

    def sync_from(self, src_network, name=None):
        src_vars = src_network.get_vars()
        dst_vars = self.get_vars()

        sync_ops = []

        with tf.device(self._device):
            with tf.name_scope(name, "GameACNetwork", []) as name:
                for(src_var, dst_var) in zip(src_vars, dst_vars):
                    sync_op = tf.assign(dst_var, src_var)
                    sync_ops.append(sync_op)

                return tf.group(*sync_ops, name=name)

    def conv_variable(self, shape, layer_name='conv', gain=1.0):
        with tf.variable_scope(layer_name):
            weight = tf.get_variable('weights', shape, initializer=tf.orthogonal_initializer(gain=gain))
            bias = tf.get_variable('biases', [shape[3]], initializer=tf.zeros_initializer())
        return weight, bias

    def fc_variable(self, shape, layer_name='fc', gain=1.0):
        with tf.variable_scope(layer_name):
            weight = tf.get_variable('weights', shape, initializer=tf.orthogonal_initializer(gain=gain))
            bias = tf.get_variable('biases', [shape[1]], initializer=tf.zeros_initializer())
        return weight, bias

    def conv2d(self, x, W, stride, data_format='NHWC'):
        return tf.nn.conv2d(x, W, strides=[1,stride,stride,1], padding = "VALID",
            use_cudnn_on_gpu=self.use_gpu, data_format=data_format)

# Multi-Classification Network
class MultiClassNetwork(Network):
    def __init__(self,
                 action_size,
                 thread_index, # -1 for global
                 device="/cpu:0"):
        Network.__init__(self, action_size, thread_index, device)
        self.graph = tf.Graph()
        logger.info("network: MultiClassNetwork")
        logger.info("action_size: {}".format(self.action_size))
        logger.info("use_mnih_2015: {}".format(colored(self.use_mnih_2015, "green" if self.use_mnih_2015 else "red")))
        logger.info("L1_beta: {}".format(colored(self.l1_beta, "green" if self.l1_beta > 0. else "red")))
        logger.info("L2_beta: {}".format(colored(self.l2_beta, "green" if self.l2_beta > 0. else "red")))
        scope_name = "net_" + str(self._thread_index)
        self.last_hidden_fc_output_size = 512

        with self.graph.as_default():
            # state (input)
            self.s = tf.placeholder(tf.float32, [None, 84, 84, 4])
            self.s_n = tf.div(self.s, 255.)

            with tf.device(self._device), tf.variable_scope(scope_name) as scope:
                if self.use_mnih_2015:
                    self.W_conv1, self.b_conv1 = self.conv_variable([8, 8, 4, 32], layer_name='conv1', gain=np.sqrt(2))
                    self.W_conv2, self.b_conv2 = self.conv_variable([4, 4, 32, 64], layer_name='conv2', gain=np.sqrt(2))
                    self.W_conv3, self.b_conv3 = self.conv_variable([3, 3, 64, 64], layer_name='conv3', gain=np.sqrt(2))
                    self.W_fc1, self.b_fc1 = self.fc_variable([3136, self.last_hidden_fc_output_size], layer_name='fc1', gain=np.sqrt(2))
                    tf.add_to_collection('transfer_params', self.W_conv1)
                    tf.add_to_collection('transfer_params', self.b_conv1)
                    tf.add_to_collection('transfer_params', self.W_conv2)
                    tf.add_to_collection('transfer_params', self.b_conv2)
                    tf.add_to_collection('transfer_params', self.W_conv3)
                    tf.add_to_collection('transfer_params', self.b_conv3)
                    tf.add_to_collection('transfer_params', self.W_fc1)
                    tf.add_to_collection('transfer_params', self.b_fc1)
                else:
                    self.W_conv1, self.b_conv1 = self.conv_variable([8, 8, 4, 16], layer_name='conv1', gain=np.sqrt(2))  # stride=4
                    self.W_conv2, self.b_conv2 = self.conv_variable([4, 4, 16, 32], layer_name='conv2', gain=np.sqrt(2)) # stride=2
                    self.W_fc1, self.b_fc1 = self.fc_variable([2592, self.last_hidden_fc_output_size], layer_name='fc1', gain=np.sqrt(2))
                    tf.add_to_collection('transfer_params', self.W_conv1)
                    tf.add_to_collection('transfer_params', self.b_conv1)
                    tf.add_to_collection('transfer_params', self.W_conv2)
                    tf.add_to_collection('transfer_params', self.b_conv2)
                    tf.add_to_collection('transfer_params', self.W_fc1)
                    tf.add_to_collection('transfer_params', self.b_fc1)

                # weight for policy output layer
                self.W_fc2, self.b_fc2 = self.fc_variable([self.last_hidden_fc_output_size, action_size], layer_name='fc2')
                tf.add_to_collection('transfer_params', self.W_fc2)
                tf.add_to_collection('transfer_params', self.b_fc2)

                if self.use_mnih_2015:
                    h_conv1 = tf.nn.relu(self.conv2d(self.s_n,  self.W_conv1, 4) + self.b_conv1)
                    h_conv2 = tf.nn.relu(self.conv2d(h_conv1, self.W_conv2, 2) + self.b_conv2)
                    h_conv3 = tf.nn.relu(self.conv2d(h_conv2, self.W_conv3, 1) + self.b_conv3)

                    h_conv3_flat = tf.reshape(h_conv3, [-1, 3136])
                    h_fc1 = tf.nn.relu(tf.matmul(h_conv3_flat, self.W_fc1) + self.b_fc1)
                else:
                    h_conv1 = tf.nn.relu(self.conv2d(self.s_n,  self.W_conv1, 4) + self.b_conv1)
                    h_conv2 = tf.nn.relu(self.conv2d(h_conv1, self.W_conv2, 2) + self.b_conv2)

                    h_conv2_flat = tf.reshape(h_conv2, [-1, 2592])
                    h_fc1 = tf.nn.relu(tf.matmul(h_conv2_flat, self.W_fc1) + self.b_fc1)

                # policy (output)
                self._pi = tf.matmul(h_fc1, self.W_fc2) + self.b_fc2
                self.pi = tf.nn.softmax(self._pi)

                self.max_value = tf.reduce_max(self._pi, axis=None)
                self.saver = tf.train.Saver()

    def prepare_loss(self, class_weights=None):
        with self.graph.as_default():
            with tf.device(self._device), tf.name_scope("Loss") as scope:
                # taken action (input for policy)
                self.a = tf.placeholder(tf.float32, shape=[None, self.action_size])

                unweighted_loss = tf.nn.softmax_cross_entropy_with_logits_v2(
                    labels=self.a,
                    logits=self._pi)

                if class_weights is not None:
                    class_weights = tf.constant(class_weights, name='class_weights')
                    weights = tf.reduce_sum(tf.multiply(class_weights, self.a), axis=1)
                    loss = tf.multiply(unweighted_loss, weights, name='weighted_loss')
                else:
                    loss = unweighted_loss

                total_loss = tf.reduce_mean(loss)

                net_vars = self.get_vars_no_bias()
                if self.l1_beta > 0:
                    # https://github.com/tensorflow/models/blob/master/inception/inception/slim/losses.py
                    l1_loss = tf.add_n([tf.reduce_sum(tf.abs(net_vars[i])) for i in range(len(net_vars))]) * self.l1_beta
                    total_loss += l1_loss
                if self.l2_beta > 0:
                    l2_loss = tf.add_n([tf.nn.l2_loss(net_vars[i]) for i in range(len(net_vars))]) * self.l2_beta
                    total_loss += l2_loss

                self.total_loss = total_loss

    def run_policy_and_value(self, sess, s_t):
        raise NotImplementedError()

    def run_policy(self, sess, s_t):
        pi_out = sess.run(
            self.pi,
            feed_dict={
                self.s : [s_t]} )
        return pi_out[0]

    def run_value(self, sess, s_t):
        raise NotImplementedError()

    def get_vars(self):
        if self.use_mnih_2015:
            return [self.W_conv1, self.b_conv1,
                self.W_conv2, self.b_conv2,
                self.W_conv3, self.b_conv3,
                self.W_fc1, self.b_fc1,
                self.W_fc2, self.b_fc2]
        else:
            return [self.W_conv1, self.b_conv1,
                self.W_conv2, self.b_conv2,
                self.W_fc1, self.b_fc1,
                self.W_fc2, self.b_fc2]

    def get_vars_no_bias(self):
        if self.use_mnih_2015:
            return [self.W_conv1, self.W_conv2,
                self.W_conv3, self.W_fc1, self.W_fc2]
        else:
            return [self.W_conv1, self.W_conv2,
                self.W_fc1, self.W_fc2]

    def load(self, sess=None, checkpoint=''):
        assert sess != None
        assert checkpoint != ''
        self.saver.restore(sess, checkpoint)
        logger.info("Successfully loaded: {}".format(checkpoint))

    def prepare_evaluate(self):
        with self.graph.as_default():
            with tf.device(self._device):
                correct_prediction = tf.equal(tf.argmax(self._pi, 1), tf.argmax(self.a, 1))
                self.accuracy = tf.reduce_mean(tf.cast(correct_prediction, tf.float32))


# MTL Binary Classification Network
class MTLBinaryClassNetwork(Network):
    def __init__(self,
                 action_size,
                 thread_index, # -1 for global
                 device="/cpu:0"):
        Network.__init__(self, action_size, thread_index, device)
        self.graph = tf.Graph()
        logger.info("network: MTLBinaryClassNetwork")
        logger.info("action_size: {}".format(self.action_size))
        logger.info("use_mnih_2015: {}".format(colored(self.use_mnih_2015, "green" if self.use_mnih_2015 else "red")))
        logger.info("L1_beta: {}".format(colored(self.l1_beta, "green" if self.l1_beta > 0. else "red")))
        logger.info("L2_beta: {}".format(colored(self.l2_beta, "green" if self.l2_beta > 0. else "red")))
        scope_name = "net_" + str(self._thread_index)
        self.last_hidden_fc_output_size = 512

        with self.graph.as_default():
            # state (input)
            self.s = tf.placeholder(tf.float32, [None, 84, 84, 4])
            self.s_n = tf.div(self.s, 255.)

            with tf.device(self._device), tf.variable_scope(scope_name) as scope:
                if self.use_mnih_2015:
                    self.W_conv1, self.b_conv1 = self.conv_variable([8, 8, 4, 32], layer_name='conv1', gain=np.sqrt(2))
                    self.W_conv2, self.b_conv2 = self.conv_variable([4, 4, 32, 64], layer_name='conv2', gain=np.sqrt(2))
                    self.W_conv3, self.b_conv3 = self.conv_variable([3, 3, 64, 64], layer_name='conv3', gain=np.sqrt(2))
                    self.W_fc1, self.b_fc1 = self.fc_variable([3136, self.last_hidden_fc_output_size], layer_name='fc1', gain=np.sqrt(2))
                    tf.add_to_collection('transfer_params', self.W_conv1)
                    tf.add_to_collection('transfer_params', self.b_conv1)
                    tf.add_to_collection('transfer_params', self.W_conv2)
                    tf.add_to_collection('transfer_params', self.b_conv2)
                    tf.add_to_collection('transfer_params', self.W_conv3)
                    tf.add_to_collection('transfer_params', self.b_conv3)
                    tf.add_to_collection('transfer_params', self.W_fc1)
                    tf.add_to_collection('transfer_params', self.b_fc1)
                else:
                    self.W_conv1, self.b_conv1 = self.conv_variable([8, 8, 4, 16], layer_name='conv1', gain=np.sqrt(2))  # stride=4
                    self.W_conv2, self.b_conv2 = self.conv_variable([4, 4, 16, 32], layer_name='conv2', gain=np.sqrt(2)) # stride=2
                    self.W_fc1, self.b_fc1 = self.fc_variable([2592, self.last_hidden_fc_output_size], layer_name='fc1', gain=np.sqrt(2))
                    tf.add_to_collection('transfer_params', self.W_conv1)
                    tf.add_to_collection('transfer_params', self.b_conv1)
                    tf.add_to_collection('transfer_params', self.W_conv2)
                    tf.add_to_collection('transfer_params', self.b_conv2)
                    tf.add_to_collection('transfer_params', self.W_fc1)
                    tf.add_to_collection('transfer_params', self.b_fc1)

                # weight for policy output layer
                self.W_fc2, self.b_fc2 = [], []
                for n_class in range(action_size):
                    W, b = self.fc_variable([self.last_hidden_fc_output_size, 2], layer_name='fc2_{}'.format(n_class))
                    self.W_fc2.append(W)
                    self.b_fc2.append(b)
                    tf.add_to_collection('transfer_params', self.W_fc2[n_class])
                    tf.add_to_collection('transfer_params', self.b_fc2[n_class])

                if self.use_mnih_2015:
                    h_conv1 = tf.nn.relu(self.conv2d(self.s_n,  self.W_conv1, 4) + self.b_conv1)
                    h_conv2 = tf.nn.relu(self.conv2d(h_conv1, self.W_conv2, 2) + self.b_conv2)
                    h_conv3 = tf.nn.relu(self.conv2d(h_conv2, self.W_conv3, 1) + self.b_conv3)

                    h_conv3_flat = tf.reshape(h_conv3, [-1, 3136])
                    h_fc1 = tf.nn.relu(tf.matmul(h_conv3_flat, self.W_fc1) + self.b_fc1)
                else:
                    h_conv1 = tf.nn.relu(self.conv2d(self.s_n,  self.W_conv1, 4) + self.b_conv1)
                    h_conv2 = tf.nn.relu(self.conv2d(h_conv1, self.W_conv2, 2) + self.b_conv2)

                    h_conv2_flat = tf.reshape(h_conv2, [-1, 2592])
                    h_fc1 = tf.nn.relu(tf.matmul(h_conv2_flat, self.W_fc1) + self.b_fc1)

                # policy (output)
                self._pi, self.pi = [], []
                self.max_value = []
                for n_class in range(action_size):
                    _pi = tf.add(tf.matmul(h_fc1, self.W_fc2[n_class]), self.b_fc2[n_class])
                    self._pi.append(_pi)
                    pi = tf.nn.softmax(self._pi[n_class])
                    self.pi.append(pi)
                    max_value = tf.reduce_max(self._pi[n_class], axis=None)
                    self.max_value.append(max_value)

                self.saver = tf.train.Saver()

    def prepare_loss(self, class_weights=None):
        with self.graph.as_default():
            with tf.device(self._device), tf.name_scope("Loss") as scope:
                # taken action (input for policy)
                self.a = tf.placeholder(tf.float32, shape=[None, 2])
                self.reward = tf.placeholder(tf.float32, shape=[None, 1])

                if self.l1_beta > 0:
                    l1_regularizers = tf.reduce_sum(tf.abs(self.W_conv1)) + tf.reduce_sum(tf.abs(self.W_conv2)) + tf.reduce_sum(tf.abs(self.W_fc1))
                    if self.use_mnih_2015:
                        l1_regularizers += tf.reduce_sum(tf.abs(self.W_conv3))
                if self.l2_beta > 0:
                    l2_regularizers = tf.nn.l2_loss(self.W_conv1) + tf.nn.l2_loss(self.W_conv2) + tf.nn.l2_loss(self.W_fc1)
                    if self.use_mnih_2015:
                        l2_regularizers += tf.nn.l2_loss(self.W_conv3)

                self.total_loss = []
                for n_class in range(self.action_size):
                    if class_weights is not None:
                        class_w = tf.constant(class_weights[n_class], name='class_weights_{}'.format(n_class))
                        logits = tf.multiply(self._pi[n_class], class_w, name='scaled_logits_{}'.format(n_class))
                    else:
                        logits = self._pi[n_class]

                    loss = tf.nn.softmax_cross_entropy_with_logits_v2(
                        labels=self.a,
                        logits=logits)
                    total_loss = tf.reduce_mean(loss)

                    if self.l1_beta > 0:
                        l1_loss = self.l1_beta * (l1_regularizers + tf.reduce_sum(tf.abs(self.W_fc2[n_class])))
                        total_loss += l1_loss
                    if self.l2_beta > 0:
                        l2_loss = self.l2_beta * (l2_regularizers + tf.nn.l2_loss(self.W_fc2[n_class]))
                        total_loss += l2_loss
                    self.total_loss.append(total_loss)

    def run_policy_and_value(self, sess, s_t):
        raise NotImplementedError()

    def run_policy(self, sess, s_t):
        pi_out = sess.run(
            self.pi,
            feed_dict={
                self.s : [s_t]} )
        return pi_out

    def run_value(self, sess, s_t):
        raise NotImplementedError()

    def get_vars(self):
        if self.use_mnih_2015:
            return [self.W_conv1, self.b_conv1,
                self.W_conv2, self.b_conv2,
                self.W_conv3, self.b_conv3,
                self.W_fc1, self.b_fc1,
                self.W_fc2, self.b_fc2]
        else:
            return [self.W_conv1, self.b_conv1,
                self.W_conv2, self.b_conv2,
                self.W_fc1, self.b_fc1,
                self.W_fc2, self.b_fc2]

    def load(self, sess=None, checkpoint=''):
        assert sess != None
        assert checkpoint != ''
        self.saver.restore(sess, checkpoint)
        logger.info("Successfully loaded: {}".format(checkpoint))

    def prepare_evaluate(self):
        with self.graph.as_default():
            with tf.device(self._device):
                self.accuracy = []
                for n_class in range(self.action_size):
                    correct_prediction = tf.equal(tf.argmax(self._pi[n_class], 1), tf.argmax(self.a, 1))
                    self.accuracy.append(tf.reduce_mean(tf.cast(correct_prediction, tf.float32)))
