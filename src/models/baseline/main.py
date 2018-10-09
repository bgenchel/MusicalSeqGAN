"""
taken from https://github.com/ZiJianZhao/SeqGAN-PyTorch
"""
import argparse
import numpy as np
import os
import random
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.autograd import Variable
from tqdm import tqdm

from generator import Generator
from discriminator import Discriminator
from rollout import Rollout
# things I haven't really looked through yet but had to copy in due to time constraint
from target_lstm import TargetLSTM
from data_iter import GenDataIter, DisDataIter

parser = argparse.ArgumentParser(description="Training Parameter")
parser.add_argument('--cuda', action='store', default=None, type=int, help="the Cuda device to use")
args = parser.parse_args()
print(args)

# Basic Training Paramters
SEED = 88 # seems like quite a long seed
BATCH_SIZE = 64
TOTAL_BATCH = 200 # ??
GENERATED_NUM = 10000 # ??
POSITIVE_FILE = 'real.data' # not sure what is meant by 'positive'
NEGATIVE_FILE = 'gene.data' # not sure what is meant by 'negative'
EVAL_FILE = 'eval.data'
VOCAB_SIZE = 5000 # ??
PRE_EPOCH_NUM = 120 # ??

if torch.cuda.is_available() and (args.cuda is not None) and (args.cuda >=0):
   torch.cuda.set_device(args.cuda) 
   args.cuda = True # ??? 

# Generator Params
gen_embed_dim = 32
gen_hidden_dim = 32
gen_seq_len = 20

# Discriminator Parameters
dscr_embed_dim = 64
dscr_num_filters = [100, 200, 200, 200, 200, 100, 100, 100, 100, 100, 160, 160]
dscr_filter_sizes = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20] # didn't know there were this many layers
dscr_dropout = 0.75
dscr_num_classes = 2 # why not just have one class that indicates probability of being real?

def generate_samples(model, num_samples, batch_size, output_file):
    samples = []
    for _ in range(int(num_samples / batch_size)):
        # why cpu?
        sample_batch = model.sample(batch_size, gen_seq_len).cpu().data.numpy().tolist()
        samples.extend(sample_batch)
        with open(output_file, 'w') as fout:
            for sample in samples:
                str_sample = ' '.join([str(s) for s in sample])
                fout.write('%s\n' % str_sample)
    return

def train_epoch(model, data_iter, loss_fn, optimizer):
    total_loss = 0.0
    total_words = 0.0 # ???
    for (data, target) in tqdm(data_iter, desc=' - Training'):
        data_var = Variable(data)
        target_var = Variable(target)
        if args.cuda:
            data_var, target_var = data_var.cuda(), target_var.cuda()
        target_var = target_var.contiguous().view(-1) # serialize the target into a contiguous vector ?
        pred = model.forward(data_var)
        loss = loss_fn(pred, target_var)
        total_loss += loss.item()
        total_words += data_var.size(0) * data_var.size(1)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
    data_iter.reset()
    return math.exp(total_loss / total_words) # weird measure ... to return

def eval_epoch(model, data_iter, loss_fn):
    total_loss = 0.0
    total_words = 0.0
    for (data, target) in tqdm(data_iter, desc= " - Evaluation"):
        data_var = Variable(data, volatile=True) # ??? why declare volatile also what is volatile.
        target_var = Variable(target, volatile=True)
        if args.cuda:
            data_var, target_var = data_var.cuda(), target_var.cuda()
        target_var = target_var.contiguous().view(-1) # serialize the target into a contiguous vector ?
        pred = model.forward(data_var)
        loss = loss_fn(pred, target_var)
        total_loss += loss.item()
        total_words += data_var.size(0) * data_var.size(1)
    data_iter.reset()
    return math.exp(total_loss / total_words) # weird measure ... to return

class GANLoss(nn.Module):
    """ 
    Reward-Refined NLLLoss Function for adversarial reinforcement training of generator
    """
    def __init__(self):
        super(GANLoss, self).__init__()

    def forward(self, prob, target, reward):
        """
        Args:
            prob: (N, C) - torch Variable
            target: (N,) - torch Variable
            reward: (N,) - torch Variable
        """
        N = target.size(0)
        C = prob.size(1)
        one_hot = torch.zeros((N, C))
        one_hot.scatter_(1, target.data.view((-1, 1)), 1) # write 1 into all positions specified by target in the 1st dim
        one_hot = Variable(one_hot.type(torch.ByteTensor)) # sets the type, so it can be used in masked_select
        if prob.is_cuda():
            one_hot = one_hot.cuda()
        loss = torch.masked_select(prob, one_hot)
        loss = loss * reward # why does a greater reward = greater loss? This should be opposite the case.
        loss = -torch.sum(loss)
        return loss

# definitely need to go through this still
def main():
    random.seed(SEED)
    np.random.seed(SEED)

    # Define Networks
    generator = Generator(VOCAB_SIZE, gen_embed_dim, gen_hidden_dim, args.cuda)
    discriminator = Discriminator(VOCAB_SIZE, dscr_embed_dim, dscr_filter_sizes, dscr_num_filters, dscr_num_classes, dscr_dropout)
    target_lstm = TargetLSTM(VOCAB_SIZE, gen_embed_dim, gen_hidden_dim, args.cuda)
    if args.cuda:
        generator = generator.cuda()
        discriminator = discriminator.cuda()
        target_lstm = target_lstm.cuda()
    # Generate toy data using target lstm
    print('Generating data ...')
    generate_samples(target_lstm, BATCH_SIZE, GENERATED_NUM, POSITIVE_FILE)
    
    # Load data from file
    gen_data_iter = GenDataIter(POSITIVE_FILE, BATCH_SIZE)

    # Pretrain Generator using MLE
    gen_criterion = nn.NLLLoss(size_average=False)
    gen_optimizer = optim.Adam(generator.parameters())
    if args.cuda:
        gen_criterion = gen_criterion.cuda()
    print('Pretrain with MLE ...')
    for epoch in range(PRE_EPOCH_NUM):
        loss = train_epoch(generator, gen_data_iter, gen_criterion, gen_optimizer)
        print('Epoch [%d] Model Loss: %f'% (epoch, loss))
        generate_samples(generator, BATCH_SIZE, GENERATED_NUM, EVAL_FILE)
        eval_iter = GenDataIter(EVAL_FILE, BATCH_SIZE)
        loss = eval_epoch(target_lstm, eval_iter, gen_criterion)
        print('Epoch [%d] True Loss: %f' % (epoch, loss))

    # Pretrain Discriminator
    dis_criterion = nn.NLLLoss(size_average=False)
    dis_optimizer = optim.Adam(discriminator.parameters())
    if args.cuda:
        dis_criterion = dis_criterion.cuda()
    print('Pretrain Dsicriminator ...')
    for epoch in range(5):
        generate_samples(generator, BATCH_SIZE, GENERATED_NUM, NEGATIVE_FILE)
        dis_data_iter = DisDataIter(POSITIVE_FILE, NEGATIVE_FILE, BATCH_SIZE)
        for _ in range(3):
            loss = train_epoch(discriminator, dis_data_iter, dis_criterion, dis_optimizer)
            print('Epoch [%d], loss: %f' % (epoch, loss))
    # Adversarial Training 
    rollout = Rollout(generator, 0.8)
    print('#####################################################')
    print('Start Adeversatial Training...\n')
    gen_gan_loss = GANLoss()
    gen_gan_optm = optim.Adam(generator.parameters())
    if args.cuda:
        gen_gan_loss = gen_gan_loss.cuda()
    gen_criterion = nn.NLLLoss(size_average=False)
    if args.cuda:
        gen_criterion = gen_criterion.cuda()
    dis_criterion = nn.NLLLoss(size_average=False)
    dis_optimizer = optim.Adam(discriminator.parameters())
    if args.cuda:
        dis_criterion = dis_criterion.cuda()
    for total_batch in range(TOTAL_BATCH):
        ## Train the generator for one step
        for it in range(1):
            samples = generator.sample(BATCH_SIZE, gen_seq_len)
            # construct the input to the genrator, add zeros before samples and delete the last column
            zeros = torch.zeros((BATCH_SIZE, 1)).type(torch.LongTensor)
            if samples.is_cuda:
                zeros = zeros.cuda()
            inputs = Variable(torch.cat([zeros, samples.data], dim = 1)[:, :-1].contiguous())
            targets = Variable(samples.data).contiguous().view((-1,))
            # calculate the reward
            rewards = rollout.get_reward(samples, 16, discriminator)
            rewards = Variable(torch.Tensor(rewards))
            if args.cuda:
                rewards = torch.exp(rewards.cuda()).contiguous().view((-1,))
            prob = generator.forward(inputs)
            loss = gen_gan_loss(prob, targets, rewards)
            gen_gan_optm.zero_grad()
            loss.backward()
            gen_gan_optmsm.step()

        if total_batch % 1 == 0 or total_batch == TOTAL_BATCH - 1:
            generate_samples(generator, BATCH_SIZE, GENERATED_NUM, EVAL_FILE)
            eval_iter = GenDataIter(EVAL_FILE, BATCH_SIZE)
            loss = eval_epoch(target_lstm, eval_iter, gen_criterion)
            print('Batch [%d] True Loss: %f' % (total_batch, loss))
        rollout.update_params()
        
        for _ in range(4):
            generate_samples(generator, BATCH_SIZE, GENERATED_NUM, NEGATIVE_FILE)
            dis_data_iter = DisDataIter(POSITIVE_FILE, NEGATIVE_FILE, BATCH_SIZE)
            for _ in range(2):
                loss = train_epoch(discriminator, dis_data_iter, dis_criterion, dis_optimizer)

if __name__ == '__main__':
    main()
