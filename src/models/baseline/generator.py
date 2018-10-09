"""
taken from https://github.com/ZiJianZhao/SeqGAN-PyTorch
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable

class Generator(nn.Module):
    def __init__(self, vocab_size, embed_dim, hidden_dim, use_cuda=True, **kwargs):
        super(Generator, self).__init__(**kwargs)
        # the number of discrete values an input can take on
        self.vocab_size = vocab_size
        self.embed_dim = embed_dim
        self.hidden_dim = hidden_dim
        self.use_cuda = use_cuda
        self.num_layers = 1

        self.embedder = nn.Embedding(vocab_size, embed_dim)
        self.lstm = nn.LSTM(embed_dim, hidden_dim)
        self.fc = nn.Linear(hidden_dim, vocab_size)
        self.softmax = nn.LogSoftmax()
        self.init_params()

    def init_params(self):
        for param in self.parameters():
            param.data.uniform_(-0.05, 0.05)
        return

    def init_hidden_and_cell(self, batch_size):
        hidden = Variable(torch.zeros((self.num_layers, batch_size, self.hidden_dim)))
        cell = Variable(torch.zeros((self.num_layers, batch_size, self.hidden_dim)))
        if self.use_cuda and torch.cuda.is_available():
            hidden, cell = hidden.cuda(), cell.cuda()
        return hidden, cell

    def forward(self, x):
        embedded = self.embedder(x)
        h0, c0 = self.init_hidden_and_cell(x.size(0))
        lstm_out, _ = self.lstm(embedded, (h0, c0))
        softmax = self.softmax(self.fc(lstm_out.view(-1, self.hidden_dim)))
        return softmax

    def single_step(self, x, hidden, cell):
        """
        Args:
            x: (batch_size, 1) sequence of tokens generated by the generator
            hidden: (1, batch_size, hidden_dim), lstm hidden state
            cell: (1, batch_size, hidden_dim), lstm cell state
        """
        embedded = self.embedder(x)
        output, (hidden, cell) = self.lstm(embedded, (hidden, cell))
        pred = F.softmax(self.fc(lstm_out.view(-1, self.hidden_dim)))
        return pred, hidden, cell

    def sample(self, batch_size, seq_len, seed=None):
        """
        why would you need batch size ... for this method. Seems weird.

        this method creates (batch_size) sequences of length (seq_len).
        If no seed is provided, it begins with a single time step of length 0.
        If a seed is provided, it generates seq_len - seed_len samples.

        generation in this method happens one step at a time, in the very inefficient way
        that totally avoids batching. When a seed is provided, this method literally chunks
        each timestep into its own tensor so it can operate this way.

        I get that this has to work this way for no seed, but feel like maybe it isn't
        necessary when a seed is provided.
        """
        samples = []
        hidden, cell = self.init_hidden_and_cell(batch_size)
        if seed is None:
            # if data is not provided, create zeros to stand in
            inpt = Variable(torch.zeros((batch_size, 1)).long())
            if self.use_cuda:
                inpt = inpt.cuda()
            for i in range(seq_len):
                output, hidden, cell = self.step(inpt, hidden, cell)
                inpt = output.multinomial(1) # sample the softmax distribution once
                samples.append(inpt)
        else:
            seed_len = seed.size(1)
            seed_symbols = seed.chunk(seed.size(1), dim=1) # each element becomes its own tensor
            samples.extend(seed_symbols)
            # run through the seed to set the network state
            for i in range(seed_len):
                output, hidden, cell = self.step(seed_symbols[i], hidden, cell)
            inpt = output.multinomial(1)
            # actual sampling occurs here
            for i in range(seed_len, seq_len):
                samples.append(inpt)
                output, hidden, cell = self.step(inpt, hidden, cell)
                inpt = output.multinomial(1)
        return torch.cat(samples, dim=1)