# -*- coding: utf-8 -*-
# file: lstm.py
# author: songyouwei <youwei0314@gmail.com>
# Copyright (C) 2018. All Rights Reserved.

import torch.nn as nn
from transformers.models.bert.modeling_bert import BertPooler


class BERT_MLP(nn.Module):
    inputs = ["text_indices"]

    def __init__(self, bert, config):
        super(BERT_MLP, self).__init__()
        self.bert = bert
        self.pooler = BertPooler(bert.config)
        self.dense = nn.Linear(config.hidden_dim, config.output_dim)

    def forward(self, inputs):
        text_raw_indices = inputs[0]
        last_hidden_state = self.bert(text_raw_indices)["last_hidden_state"]
        pooled_out = self.pooler(last_hidden_state)
        out = self.dense(pooled_out)
        return out
