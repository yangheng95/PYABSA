# -*- coding: utf-8 -*-
# file: apc_config_handler.py
# time: 2021/5/26 0026
# author: yangheng <yangheng@m.scnu.edu.cn>
# github: https://github.com/yangheng95
# Copyright (C) 2021. All Rights Reserved.

from pyabsa.tasks.apc.models import BERT_SPC
from pyabsa.tasks.glove_apc.models import TNet_LF

import copy

# if you find the optimal param set of some situation, e.g., some model on some datasets
# please share the config use template param_dict
_apc_param_dict_template = {'model': BERT_SPC,
                            'optimizer': "",
                            'learning_rate': 0.00002,
                            'pretrained_bert_name': "bert-base-uncased",
                            'use_bert_spc': True,
                            'max_seq_len': 80,
                            'SRD': 3,
                            'use_syntax_based_SRD': False,
                            'sigma': 0.3,
                            'lcf': "cdw",
                            'window': "lr",
                            'eta': -1,
                            'dropout': 0,
                            'l2reg': 0.0001,
                            'num_epoch': 10,
                            'batch_size': 16,
                            'initializer': 'xavier_uniform_',
                            'seed': {1, 2, 3},
                            'embed_dim': 768,
                            'hidden_dim': 768,
                            'polarities_dim': 3,
                            'log_step': 10,
                            'dynamic_truncate': True,
                            'srd_alignment': True,  # for srd_alignment
                            'evaluate_begin': 0,
                            'similarity_threshold': 1,  # disable same text check for different examples
                            'cross_validate_fold': -1
                            # split train and test datasets into 5 folds and repeat 3 training
                            }

_apc_param_dict_base = {'model': BERT_SPC,
                        'optimizer': "adam",
                        'learning_rate': 0.00002,
                        'pretrained_bert_name': "bert-base-uncased",
                        'use_bert_spc': True,
                        'max_seq_len': 80,
                        'SRD': 3,
                        'use_syntax_based_SRD': False,
                        'sigma': 0.3,
                        'lcf': "cdw",
                        'window': "lr",
                        'eta': -1,
                        'dropout': 0,
                        'l2reg': 0.0001,
                        'num_epoch': 10,
                        'batch_size': 16,
                        'initializer': 'xavier_uniform_',
                        'seed': {1, 2, 3},
                        'embed_dim': 768,
                        'hidden_dim': 768,
                        'polarities_dim': 3,
                        'log_step': 10,
                        'dynamic_truncate': True,
                        'srd_alignment': True,  # for srd_alignment
                        'evaluate_begin': 0,
                        'similarity_threshold': 1,  # disable same text check for different examples
                        'cross_validate_fold': -1  # split train and test datasets into 5 folds and repeat 3 training
                        }

_apc_param_dict_english = {'model': BERT_SPC,
                           'optimizer': "adam",
                           'learning_rate': 0.00002,
                           'pretrained_bert_name': "bert-base-uncased",
                           'use_bert_spc': True,
                           'max_seq_len': 80,
                           'SRD': 3,
                           'a': 2, # the a in dlcf_dca_bert
                           'p': 1, # the p in dlcf_dca_bert
                           'layer': 3, # the layer in dlcf_dca_bert
                           'use_syntax_based_SRD': False,
                           'sigma': 0.3,
                           'lcf': "cdw",
                           'window': "lr",
                           'eta': -1,
                           'dropout': 0.5,
                           'l2reg': 0.0001,
                           'num_epoch': 10,
                           'batch_size': 16,
                           'initializer': 'xavier_uniform_',
                           'seed': {1, 2, 3},
                           'embed_dim': 768,
                           'hidden_dim': 768,
                           'polarities_dim': 3,
                           'log_step': 5,
                           'dynamic_truncate': True,
                           'srd_alignment': True,  # for srd_alignment
                           'evaluate_begin': 2,
                           'similarity_threshold': 1,  # disable same text check for different examples
                           'cross_validate_fold': -1  # split train and test datasets into 5 folds and repeat 3 training
                           }

_apc_param_dict_multilingual = {'model': BERT_SPC,
                                'optimizer': "adam",
                                'learning_rate': 0.00002,
                                'pretrained_bert_name': "bert-base-multilingual-uncased",
                                'use_bert_spc': True,
                                'max_seq_len': 80,
                                'SRD': 3,
                                'use_syntax_based_SRD': False,
                                'sigma': 0.3,
                                'lcf': "cdw",
                                'window': "lr",
                                'eta': -1,
                                'dropout': 0.5,
                                'l2reg': 0.0001,
                                'num_epoch': 10,
                                'batch_size': 16,
                                'initializer': 'xavier_uniform_',
                                'seed': {1, 2, 3},
                                'embed_dim': 768,
                                'hidden_dim': 768,
                                'polarities_dim': 3,
                                'log_step': 5,
                                'dynamic_truncate': True,
                                'srd_alignment': True,  # for srd_alignment
                                'evaluate_begin': 2,
                                'similarity_threshold': 1,  # disable same text check for different examples
                                'cross_validate_fold': -1
                                # split train and test datasets into 5 folds and repeat 3 training
                                }

_apc_param_dict_chinese = {'model': BERT_SPC,
                           'optimizer': "adam",
                           'learning_rate': 0.00002,
                           'pretrained_bert_name': "bert-base-chinese",
                           'use_bert_spc': True,
                           'max_seq_len': 80,
                           'SRD': 3,
                           'use_syntax_based_SRD': False,
                           'sigma': 0.3,
                           'lcf': "cdw",
                           'window': "lr",
                           'eta': -1,
                           'dropout': 0.5,
                           'l2reg': 0.00001,
                           'num_epoch': 10,
                           'batch_size': 16,
                           'initializer': 'xavier_uniform_',
                           'seed': {1, 2, 3},
                           'embed_dim': 768,
                           'hidden_dim': 768,
                           'polarities_dim': 3,
                           'log_step': 5,
                           'dynamic_truncate': True,
                           'srd_alignment': True,  # for srd_alignment
                           'evaluate_begin': 2,
                           'similarity_threshold': 1,  # disable same text check for different examples
                           'cross_validate_fold': -1  # split train and test datasets into 5 folds and repeat 3 training
                           }

_apc_param_dict_glove = {'model': TNet_LF,
                         'optimizer': "adam",
                         'learning_rate': 0.001,
                         'max_seq_len': 100,
                         'dropout': 0.1,
                         'l2reg': 0.0001,
                         'num_epoch': 20,
                         'batch_size': 16,
                         'initializer': 'xavier_uniform_',
                         'seed': {1, 2, 3},
                         'embed_dim': 300,
                         'hidden_dim': 300,
                         'polarities_dim': 3,
                         'log_step': 5,
                         'hops': 3,  # valid in MemNet and RAM only
                         'evaluate_begin': 0,
                         'similarity_threshold': 1,  # disable same text check for different examples
                         'cross_validate_fold': -1  # split train and test datasets into 5 folds and repeat 3 training
                         }


def get_apc_param_dict_template():
    return copy.deepcopy(_apc_param_dict_template)


def get_apc_param_dict_base():
    return copy.deepcopy(_apc_param_dict_base)


def get_apc_param_dict_english():
    return copy.deepcopy(_apc_param_dict_english)


def get_apc_param_dict_chinese():
    return copy.deepcopy(_apc_param_dict_chinese)


def get_apc_param_dict_multilingual():
    return copy.deepcopy(_apc_param_dict_multilingual)


def get_apc_param_dict_glove():
    return copy.deepcopy(_apc_param_dict_glove)
