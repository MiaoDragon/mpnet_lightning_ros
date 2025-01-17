import sys, os
sys.path.insert(1, '/root/catkin_ws/src/lightning_ros/scripts')
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
import torch.nn as nn
import torch
from gem_utility import *
import numpy as np
import copy
# Auxiliary functions useful for GEM's inner optimization.
class End2EndMPNet(nn.Module):
    def __init__(self, total_input_size, AE_input_size, mlp_input_size, output_size, AEtype, \
                 n_tasks, n_memories, memory_strength, grad_step, CAE, MLP, device=torch.device('cpu')):
        super(End2EndMPNet, self).__init__()
        self.encoder = CAE.Encoder()
        self.mlp = MLP(mlp_input_size, output_size)
        self.mse = nn.MSELoss()
        self.opt = torch.optim.Adagrad(list(self.encoder.parameters())+list(self.mlp.parameters()))
        '''
        Below is the attributes defined in GEM implementation
        reference: https://arxiv.org/abs/1706.08840
        code from: https://github.com/facebookresearch/GradientEpisodicMemory
        '''
        self.margin = memory_strength
        self.n_memories = n_memories
        # allocate episodic memory
        self.memory_data = torch.FloatTensor(
            n_tasks, self.n_memories, total_input_size)
        self.memory_labs = torch.FloatTensor(n_tasks, self.n_memories, output_size)
        self.memory_data = self.memory_data.to(device)
        self.memory_labs = self.memory_labs.to(device)

        # allocate temporary synaptic memory
        self.grad_dims = []
        for param in self.parameters():
            self.grad_dims.append(param.data.numel())
        # edit: need one more dimension for newly observed data
        self.grads = torch.Tensor(sum(self.grad_dims), n_tasks+1)
        self.grads = self.grads.to(device)
        # allocate counters
        self.observed_tasks = []
        self.old_task = -1
        self.mem_cnt = np.zeros(n_tasks).astype(int)
        self.num_seen = np.zeros(n_tasks).astype(int)
        self.grad_step = grad_step
        self.total_input_size = total_input_size
        self.AE_input_size = AE_input_size
        self.device = device
    def clear_memory(self):
        # set the counter to 0
        self.mem_cnt[:] = 0
        # set observed task to empty
        self.observed_tasks = []
        self.old_task = -1
    def set_opt(self, opt, lr=1e-2, momentum=None):
        # edit: can change optimizer type when setting
        if momentum is None:
            self.opt = opt(list(self.encoder.parameters())+list(self.mlp.parameters()), lr=lr)
        else:
            self.opt = opt(list(self.encoder.parameters())+list(self.mlp.parameters()), lr=lr, momentum=momentum)
    def forward(self, x):
        # xobs is the input to encoder
        # x is the input to mlp
        z = self.encoder(x[:,:self.AE_input_size])
        mlp_in = torch.cat((z,x[:,self.AE_input_size:]), 1)    # keep the first dim the same (# samples)
        return self.mlp(mlp_in)
    def loss(self, pred, truth):
        return self.mse(pred, truth)

    def load_memory(self, data):
        # data: (tasks, xs, ys)
        # continuously load memory based on previous memory loading
        tasks, xs, ys = data
        for i in range(len(tasks)):
            if tasks[i] != self.old_task:
                # new task, clear mem_cnt
                self.observed_tasks.append(tasks[i])
                self.old_task = tasks[i]
                self.mem_cnt[tasks[i]] = 0
            x = torch.tensor(xs[i])
            y = torch.tensor(ys[i])
            x = x.to(self.device)
            y = y.to(self.device)
            self.remember(x, tasks[i], y)

    def remember(self, x, t, y):
        # follow reservoir sampling
        # i-th item is remembered with probability min(B/i, 1)
        for i in range(len(x)):
            self.num_seen[t] += 1
            prob_thre = min(self.n_memories, self.num_seen[t])
            rand_num = np.random.choice(self.num_seen[t], 1) # 0---self.num_seen[t]-1
            if rand_num < prob_thre:
                # keep the new item
                if self.mem_cnt[t] < self.n_memories:
                    self.memory_data[t, self.mem_cnt[t]].copy_(x.data[i])
                    self.memory_labs[t, self.mem_cnt[t]].copy_(y.data[i])
                    self.mem_cnt[t] += 1
                else:
                    # randomly choose one to rewrite
                    idx = np.random.choice(self.n_memories, size=1)
                    idx = idx[0]
                    self.memory_data[t, idx].copy_(x.data[i])
                    self.memory_labs[t, idx].copy_(y.data[i])

    '''
    Below is the added GEM feature
    reference: https://arxiv.org/abs/1706.08840
    code from: https://github.com/facebookresearch/GradientEpisodicMemory
    '''
    def observe(self, x, t, y, remember=True):
        # remember: remember this data or not
        # update memory
        # everytime we treat the new data as a new task
        # compute gradient on all tasks
        # (prevent forgetting previous experience of same task, too)
        for _ in range(self.grad_step):

            if len(self.observed_tasks) >= 1:
                for tt in range(len(self.observed_tasks)):
                    if self.mem_cnt[tt] == 0 and tt == len(self.observed_tasks) - 1:
                        # nothing to train on
                        continue
                    self.zero_grad()
                    # fwd/bwd on the examples in the memory
                    past_task = self.observed_tasks[tt]
                    if tt == len(self.observed_tasks) - 1:
                        ptloss = self.loss(
                            self.forward(
                            self.memory_data[past_task][:self.mem_cnt[past_task]]),   # TODO
                            self.memory_labs[past_task][:self.mem_cnt[past_task]])   # up to current
                    else:
                        ptloss = self.loss(
                            self.forward(
                            self.memory_data[past_task]),   # TODO
                            self.memory_labs[past_task])
                    ptloss.backward()
                    store_grad(self.parameters, self.grads, self.grad_dims,
                               past_task)

            # now compute the grad on the current minibatch
            self.zero_grad()
            loss = self.loss(self.forward(x), y)
            loss.backward()
            # check if gradient violates constraints
            # treat gradient of current data as a new task (max of observed task + 1)
            # just to give it a new task label
            if len(self.observed_tasks) >= 1:
                # copy gradient
                new_t = max(self.observed_tasks)+1  # a new dimension
                store_grad(self.parameters, self.grads, self.grad_dims, new_t)
                indx = torch.LongTensor(self.observed_tasks).to(self.device) # here we need all observed tasks
                #indx = torch.cuda.FloatTensor(self.observed_tasks[:-1]) if torch.cuda.is_available() \
                #    else torch.FloatTensor(self.observed_tasks[:-1])
                # here is different, we are using new_t instead of t to ditinguish between
                # newly observed data and previous data
                dotp = torch.mm(self.grads[:, new_t].unsqueeze(0),
                                self.grads.index_select(1, indx))
                #print('dot product computed')
                if (dotp < 0).sum() != 0:
                    # remember norm
                    norm = torch.norm(self.grads[:, new_t], 2)
                    project2cone2(self.grads[:, new_t].unsqueeze(1),
                                  self.grads.index_select(1, indx), self.margin)
                    new_norm = torch.norm(self.grads[:, new_t], 2)
                    self.grads[:, new_t].copy_(self.grads[:, new_t] / new_norm * norm)
                    # before overwrite, to avoid gradient explosion, renormalize the gradient
                    # so that new gradient has the same l2 norm as previous
                    # it can be proved theoretically that this does not violate the non-negativity
                    # of inner product between memory and gradient
                    # copy gradients back
                    overwrite_grad(self.parameters, self.grads[:, new_t],
                                   self.grad_dims)
            self.opt.step()
            print('optimizer stepping...')
        # after training, store into memory

        # when storing into memory, we use the correct task label
        # Update ring buffer storing examples from current task
        if remember:
            # only remember when the flag is TRUE
            if t != self.old_task:
                # new task, clear mem_cnt
                self.observed_tasks.append(t)
                self.old_task = t
                self.mem_cnt[t] = 0
            self.remember(x, t, y)
