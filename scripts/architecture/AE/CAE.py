import argparse
import os
import torch
from torch import nn
from torch.autograd import Variable

mse_loss = nn.MSELoss()
class Encoder(nn.Module):
	def __init__(self):
		super(Encoder, self).__init__()
		print('using deep encoder')
		self.encoder = nn.Sequential(nn.Linear(2800, 512),nn.PReLU(),nn.Linear(512, 256),nn.PReLU(),nn.Linear(256, 128),nn.PReLU(),nn.Linear(128, 28))

	def net_loss(self, out_D, D):
	    # given a net, obtain the loss
	    # from CAE python file
	    keys=list(self.state_dict().keys())
	    W=Variable(self.state_dict()[keys[9]])
	    if torch.cuda.is_available():
	        W = W.cuda()
	    lam = 1e-3
	    mse = mse_loss(out_D, D)
	    contractive_loss = torch.sum(W**2, dim=1).sum().mul_(lam)
	    return mse + contractive_loss
	    #return mse    ## TODO:

	def forward(self, x):
		x = self.encoder(x)
		return x

class Decoder(nn.Module):
	def __init__(self):
		super(Decoder, self).__init__()
		self.decoder = nn.Sequential(nn.Linear(28, 128),nn.PReLU(),nn.Linear(128, 256),nn.PReLU(),nn.Linear(256, 512),nn.PReLU(),nn.Linear(512, 2800))
	def forward(self, x):
		x = self.decoder(x)
		return x
