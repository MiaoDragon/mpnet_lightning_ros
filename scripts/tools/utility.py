import torch
from torch.autograd import Variable
import copy
import rospy
import os
import importlib

def to_var(x, volatile=False):
    if torch.cuda.is_available():
        x = x.cuda()
    return Variable(x, volatile=volatile)

def save_state(net, torch_seed, np_seed, py_seed, fname):
    # save both model state and optimizer state
    states = {
        'state_dict': net.state_dict(),
        'optimizer': net.opt.state_dict(),
        'torch_seed': torch_seed,
        'np_seed': np_seed,
        'py_seed': py_seed
    }
    torch.save(states, fname)

def load_net_state(net, fname):
    checkpoint = torch.load(fname)
    net.load_state_dict(checkpoint['state_dict'])

def load_opt_state(net, fname):
    checkpoint = torch.load(fname)
    net.opt.load_state_dict(checkpoint['optimizer'])

def load_seed(fname):
    # load both torch random seed, and numpy random seed
    checkpoint = torch.load(fname)
    return checkpoint['torch_seed'], checkpoint['np_seed'], checkpoint['py_seed']

def create_model(ModelConstr):
    mlp_arch_path = rospy.get_param('model/mlp_arch_path')
    cae_arch_path = rospy.get_param('model/cae_arch_path')
    total_input_size = rospy.get_param('model/total_input_size')
    AE_input_size = rospy.get_param('model/AE_input_size')
    mlp_input_size = rospy.get_param('model/mlp_input_size')
    output_size = rospy.get_param('model/output_size')
    n_tasks = rospy.get_param('model/n_tasks')
    n_memories = rospy.get_param('model/n_memories')
    memory_strength = rospy.get_param('model/memory_strength')
    grad_step = rospy.get_param('model/grad_step')

    mlp = importlib.import_module(mlp_arch_path)
    CAE = importlib.import_module(cae_arch_path)
    MLP = mlp.MLP
    model = ModelConstr(total_input_size, AE_input_size, mlp_input_size, \
            output_size, 'deep', n_tasks, n_memories, memory_strength, grad_step, \
            CAE, MLP)
    return model

def create_optimizer(model):
    opt_type = rospy.get_param('model/opt_type')
    learning_rate = rospy.get_param('model/learning_rate')
    if opt_type == 'Adagrad':
        model.set_opt(torch.optim.Adagrad, lr=learning_rate)
    elif opt_type == 'Adam':
        model.set_opt(torch.optim.Adam, lr=learning_rate)
    elif opt_type == 'SGD':
        model.set_opt(torch.optim.SGD, lr=learning_rate, momentum=0.9)
    elif opt_type == 'ASGD':
        model.set_opt(torch.optim.ASGD, lr=learning_rate)

def create_and_load_model(ModelConstr, fname, device):
    rospy.loginfo('Creating and loading model...')
    model = create_model(ModelConstr)
    if os.path.isfile(fname):
        # previous trained model exists, load model
        load_net_state(model, fname)
    # make sure the new loaded weights are transformed as well
    model.to(device=device)
    # create optimizer
    # create this later because I'm not sure if loading previous network weights
    # will overwrite the optimizer parameters
    create_optimizer(model)
    # load optimizer if there exists previous one
    if os.path.isfile(fname):
        load_opt_state(model, fname)
    return model