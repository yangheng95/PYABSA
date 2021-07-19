# -*- coding: utf-8 -*-
# file: apc_utils.py
# time: 2021/5/23 0023
# author: xumayi <xumayi@m.scnu.edu.cn>
# github: https://github.com/XuMayi
# Copyright (C) 2021. All Rights Reserved.

import torch
import torch.nn as nn

from transformers.models.bert.modeling_bert import BertPooler
from pyabsa.network.sa_encoder import Encoder


def dependency_hidden(bert_local_out, depend, depended):
    depend_out = bert_local_out.clone()
    depended_out = bert_local_out.clone()
    for i in range(bert_local_out.size()[0]):
        for j in range(1, bert_local_out.size()[1]):
            if j - 1 not in depend[i]:
                depend_out[i][j] = depend_out[i][j] * 0
    for i in range(bert_local_out.size()[0]):
        for j in range(1, bert_local_out.size()[1]):
            if j - 1 not in depended[i]:
                depended_out[i][j] = depended_out[i][j] * 0
    return depend_out, depended_out


def weight_distrubute_local(bert_local_out, depend_weight, depended_weight, depend, depended, opt, no_connect):
    bert_local_out2 = torch.zeros_like(bert_local_out)
    for j in range(depend.size()[0]):
        bert_local_out2[j][0] = bert_local_out[j][0]

    for j in range(depend.size()[0]):
        for i in range(depend.size()[1]):
            if depend[j][i] != -1 and (depend[j][i] + 1) < opt.max_seq_len:
                bert_local_out2[j][depend[j][i] + 1] = depend_weight[j].item() * bert_local_out[j][depend[j][i] + 1]

    for j in range(depended.size()[0]):
        for i in range(depended.size()[1]):
            if depended[j][i] != -1 and (depended[j][i] + 1) < opt.max_seq_len:
                bert_local_out2[j][depended[j][i] + 1] = depended_weight[j].item() * bert_local_out[j][
                    depended[j][i] + 1]

    for j in range(no_connect.size()[0]):
        for i in range(no_connect.size()[1]):
            if no_connect[j][i] != -1 and (no_connect[j][i] + 1) < opt.max_seq_len:
                bert_local_out2[j][no_connect[j][i] + 1] = 0

    return bert_local_out2


class PointwiseFeedForward(nn.Module):
    ''' A two-feed-forward-layer module '''

    def __init__(self, d_hid, d_inner_hid=None, d_out=None, dropout=0):
        super(PointwiseFeedForward, self).__init__()
        if d_inner_hid is None:
            d_inner_hid = d_hid
        if d_out is None:
            d_out = d_inner_hid
        self.w_1 = nn.Conv1d(d_hid, d_inner_hid, 1)  # position-wise
        self.w_2 = nn.Conv1d(d_inner_hid, d_out, 1)  # position-wise
        self.dropout = nn.Dropout(dropout)
        self.relu = nn.ReLU()

    def forward(self, x):
        output = self.relu(self.w_1(x.transpose(1, 2)))
        output = self.w_2(output).transpose(2, 1)
        output = self.dropout(output)
        return output

class DLCF_DCA_BERT(nn.Module):
    def __init__(self, bert, opt):
        super(DLCF_DCA_BERT, self).__init__()
        self.bert4global = bert
        self.bert4local = self.bert4global

        self.hidden = opt.embed_dim
        self.opt = opt
        self.opt.bert_dim = opt.embed_dim
        self.dropout = nn.Dropout(opt.dropout)
        self.bert_SA_ = Encoder(bert.config, opt)

        self.mean_pooling_double = PointwiseFeedForward(self.hidden * 2, self.hidden, self.hidden)
        self.bert_pooler = BertPooler(bert.config)
        self.dense = nn.Linear(self.hidden, opt.polarities_dim)

        if opt.dca_layer >= 1:
            self.bert_d_sa1 = Encoder(bert.config, opt)
            self.bert_d_pooler1 =  BertPooler(bert.config)
            self.lin1 = nn.Sequential(
                nn.Linear(opt.bert_dim, opt.bert_dim * 2),
                nn.GELU(),
                nn.Linear(opt.bert_dim * 2, 1),
                nn.Sigmoid(),
            )
        if opt.dca_layer >= 2:
            self.bert_d_sa2 = Encoder(bert.config, opt)
            self.bert_d_pooler2 =  BertPooler(bert.config)
            self.lin2 = nn.Sequential(
                nn.Linear(opt.bert_dim, opt.bert_dim * 2),
                nn.GELU(),
                nn.Linear(opt.bert_dim * 2, 1),
                nn.Sigmoid(),
            )
        if opt.dca_layer >= 3:
            self.bert_d_sa3 = Encoder(bert.config, opt)
            self.bert_d_pooler3 =  BertPooler(bert.config)
            self.lin3 = nn.Sequential(
                nn.Linear(opt.bert_dim, opt.bert_dim * 2),
                nn.GELU(),
                nn.Linear(opt.bert_dim * 2, 1),
                nn.Sigmoid(),
            )
        if opt.dca_layer >= 4:
            self.bert_d_sa4 = Encoder(bert.config, opt)
            self.bert_d_pooler4 =  BertPooler(bert.config)
            self.lin4 = nn.Sequential(
                nn.Linear(opt.bert_dim, opt.bert_dim * 2),
                nn.GELU(),
                nn.Linear(opt.bert_dim * 2, 1),
                nn.Sigmoid(),
            )
        if opt.dca_layer >= 5:
            self.bert_d_sa5 = Encoder(bert.config, opt)
            self.bert_d_pooler5 =  BertPooler(bert.config)
            self.lin5 = nn.Sequential(
                nn.Linear(opt.bert_dim, opt.bert_dim * 2),
                nn.GELU(),
                nn.Linear(opt.bert_dim * 2, 1),
                nn.Sigmoid(),
            )
        if opt.dca_layer >= 6:
            self.bert_d_sa6 = Encoder(bert.config, opt)
            self.bert_d_pooler6 =  BertPooler(bert.config)
            self.lin6 = nn.Sequential(
                nn.Linear(opt.bert_dim, opt.bert_dim * 2),
                nn.GELU(),
                nn.Linear(opt.bert_dim * 2, 1),
                nn.Sigmoid(),
            )
        if opt.dca_layer >= 7:
            self.bert_d_sa7 = Encoder(bert.config, opt)
            self.bert_d_pooler7 =  BertPooler(bert.config)
            self.lin7 = nn.Sequential(
                nn.Linear(opt.bert_dim, opt.bert_dim * 2),
                nn.GELU(),
                nn.Linear(opt.bert_dim * 2, 1),
                nn.Sigmoid(),
            )


    def weight_calculate(self, sa, pool, lin, d_w, ded_w, depend_out, depended_out):
        depend_sa_out = sa(depend_out)
        depend_sa_out = self.dropout(depend_sa_out)
        depended_sa_out = sa(depended_out)
        depended_sa_out = self.dropout(depended_sa_out)

        depend_pool_out = pool(depend_sa_out)
        depend_pool_out = self.dropout(depend_pool_out)
        depended_pool_out = pool(depended_sa_out)
        depended_pool_out = self.dropout(depended_pool_out)

        depend_weight = lin(depend_pool_out)
        depend_weight = self.dropout(depend_weight)
        depended_weight = lin(depended_pool_out)
        depended_weight = self.dropout(depended_weight)

        for i in range(depend_weight.size()[0]):
            depend_weight[i] = depend_weight[i].item() * d_w[i].item()
            depended_weight[i] = depended_weight[i].item() * ded_w[i].item()
            weight_sum = depend_weight[i].item() + depended_weight[i].item()
            if weight_sum != 0:
                depend_weight[i] = (2 * depend_weight[i] / weight_sum) ** self.opt.dca_p
                if depend_weight[i] > 2:
                    depend_weight[i] = 2
                depended_weight[i] = (2 * depended_weight[i] / weight_sum) ** self.opt.dca_p
                if depended_weight[i] > 2:
                    depended_weight[i] = 2
            else:
                depend_weight[i] = 1
                depended_weight[i] = 1
        return depend_weight, depended_weight

    def forward(self, inputs):
        if self.opt.use_bert_spc:
            text_bert_indices = inputs[0]
        else:
            text_bert_indices = inputs[1]
        text_local_indices = inputs[1]
        lcf_matrix = inputs[2]
        depend = inputs[3]
        depended = inputs[4]
        no_connect = inputs[5]

        global_context_features = self.bert4global(text_bert_indices)['last_hidden_state']
        local_context_features = self.bert4local(text_local_indices)['last_hidden_state']

        bert_local_out = torch.mul(local_context_features, lcf_matrix)

        depend_weight = torch.ones(bert_local_out.size()[0])
        depended_weight = torch.ones(bert_local_out.size()[0])

        if self.opt.dca_layer >= 1:
            depend_out, depended_out = dependency_hidden(bert_local_out, depend, depended)
            depend_weight, depended_weight = self.weight_calculate(self.bert_d_sa1, self.bert_d_pooler1, self.lin1,
                                                                   depend_weight, depended_weight, depend_out,
                                                                   depended_out)
            bert_local_out = weight_distrubute_local(bert_local_out, depend_weight, depended_weight, depend, depended,
                                                     self.opt, no_connect)
        if self.opt.dca_layer >= 2:
            depend_out, depended_out = dependency_hidden(bert_local_out, depend, depended)
            depend_weight, depended_weight = self.weight_calculate(self.bert_d_sa2, self.bert_d_pooler2, self.lin2,
                                                                   depend_weight, depended_weight, depend_out,
                                                                   depended_out)
            bert_local_out = weight_distrubute_local(bert_local_out, depend_weight, depended_weight, depend, depended,
                                                     self.opt, no_connect)
        if self.opt.dca_layer >= 3:
            depend_out, depended_out = dependency_hidden(bert_local_out, depend, depended)
            depend_weight, depended_weight = self.weight_calculate(self.bert_d_sa3, self.bert_d_pooler3, self.lin3,
                                                                   depend_weight, depended_weight, depend_out,
                                                                   depended_out)
            bert_local_out = weight_distrubute_local(bert_local_out, depend_weight, depended_weight, depend, depended,
                                                     self.opt, no_connect)
        if self.opt.dca_layer >= 4:
            depend_out, depended_out = dependency_hidden(bert_local_out, depend, depended)
            depend_weight, depended_weight = self.weight_calculate(self.bert_d_sa4, self.bert_d_pooler4, self.lin4,
                                                                   depend_weight, depended_weight, depend_out,
                                                                   depended_out)
            bert_local_out = weight_distrubute_local(bert_local_out, depend_weight, depended_weight, depend, depended,
                                                     self.opt, no_connect)
        if self.opt.dca_layer >= 5:
            depend_out, depended_out = dependency_hidden(bert_local_out, depend, depended)
            depend_weight, depended_weight = self.weight_calculate(self.bert_d_sa5, self.bert_d_pooler5, self.lin5,
                                                                   depend_weight, depended_weight, depend_out,
                                                                   depended_out)
            bert_local_out = weight_distrubute_local(bert_local_out, depend_weight, depended_weight, depend, depended,
                                                     self.opt, no_connect)
        if self.opt.dca_layer >= 6:
            depend_out, depended_out = dependency_hidden(bert_local_out, depend, depended)
            depend_weight, depended_weight = self.weight_calculate(self.bert_d_sa6, self.bert_d_pooler6, self.lin6,
                                                                   depend_weight, depended_weight, depend_out,
                                                                   depended_out)
            bert_local_out = weight_distrubute_local(bert_local_out, depend_weight, depended_weight, depend, depended,
                                                     self.opt, no_connect)
        if self.opt.dca_layer >= 7:
            depend_out, depended_out = dependency_hidden(bert_local_out, depend, depended)
            depend_weight, depended_weight = self.weight_calculate(self.bert_d_sa7, self.bert_d_pooler7, self.lin7,
                                                                   depend_weight, depended_weight, depend_out,
                                                                   depended_out)
            bert_local_out = weight_distrubute_local(bert_local_out, depend_weight, depended_weight, depend, depended,
                                                     self.opt, no_connect)

        out_cat = torch.cat((bert_local_out, global_context_features), dim=-1)
        out_cat = self.mean_pooling_double(out_cat)
        out_cat = self.bert_SA_(out_cat)
        out_cat = self.bert_pooler(out_cat)
        dense_out = self.dense(out_cat)
        return dense_out