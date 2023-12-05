# -*- coding: utf-8 -*-
# file: apc_utils_for_dlcf_dca.py
# time: 2021/5/23 0023
# author: xumayi <xumayi@m.scnu.edu.cn>
# github: https://github.com/XuMayi
# Copyright (C) 2021. All Rights Reserved.

import math
import os

import networkx as nx
import numpy as np
import spacy
import termcolor

from pyabsa.utils.pyabsa_utils import fprint
from .apc_utils import text_to_sequence, get_syntax_distance


def prepare_input_for_dlcf_dca(config, tokenizer, text_left, text_right, aspect):
    if hasattr(config, "dynamic_truncate") and config.dynamic_truncate:
        _max_seq_len = config.max_seq_len - len(aspect.split(" "))
        text_left = text_left.split(" ")
        text_right = text_right.split(" ")
        if _max_seq_len < (len(text_left) + len(text_right)):
            cut_len = len(text_left) + len(text_right) - _max_seq_len
            if len(text_left) > len(text_right):
                text_left = text_left[cut_len:]
            else:
                text_right = text_right[: len(text_right) - cut_len]
        text_left = " ".join(text_left)
        text_right = " ".join(text_right)

        # test code
        text_left = " ".join(
            text_left.split(" ")[
            int(-(config.max_seq_len - len(aspect.split())) / 2) - 1:
            ]
        )
        text_right = " ".join(
            text_right.split(" ")[
            : int((config.max_seq_len - len(aspect.split())) / 2) + 1
            ]
        )
        bos_token = tokenizer.bos_token if tokenizer.bos_token else "[CLS]"
        eos_token = tokenizer.eos_token if tokenizer.eos_token else "[SEP]"

        text_raw = text_left + " " + aspect + " " + text_right
        text_spc = (
                bos_token
                + " "
                + text_raw
                + " "
                + eos_token
                + " "
                + aspect
                + " "
                + eos_token
        )
        text_indices = text_to_sequence(tokenizer, text_spc, config.max_seq_len)
        aspect_bert_indices = text_to_sequence(tokenizer, aspect, config.max_seq_len)

        aspect_begin = len(tokenizer.tokenize(bos_token + " " + text_left))

        # if 'dlcf' in config.model_name or config.use_syntax_based_SRD:
        #     syntactical_dist, max_dist = get_syntax_distance(text_raw, aspect, tokenizer, config)
        # else:
        #     syntactical_dist = None

        syntactical_dist, max_dist = get_syntax_distance(
            text_raw, aspect, tokenizer, config
        )

        dlcf_cdm_vec = get_dynamic_cdm_vec(
            config,
            max_dist,
            text_indices,
            aspect_bert_indices,
            aspect_begin,
            syntactical_dist=None,
        )
        dlcf_cdw_vec = get_dynamic_cdw_vec(
            config,
            max_dist,
            text_indices,
            aspect_bert_indices,
            aspect_begin,
            syntactical_dist=None,
        )

        dlcfs_cdm_vec = get_dynamic_cdm_vec(
            config,
            max_dist,
            text_indices,
            aspect_bert_indices,
            aspect_begin,
            syntactical_dist,
        )
        dlcfs_cdw_vec = get_dynamic_cdw_vec(
            config,
            max_dist,
            text_indices,
            aspect_bert_indices,
            aspect_begin,
            syntactical_dist,
        )

        depend_vec, depended_vec = calculate_cluster(text_raw, aspect, config)

        inputs = {
            "dlcf_cdm_vec": dlcf_cdm_vec,
            "dlcf_cdw_vec": dlcf_cdw_vec,
            "dlcfs_cdm_vec": dlcfs_cdm_vec,
            "dlcfs_cdw_vec": dlcfs_cdw_vec,
            "depend_vec": depend_vec,
            "depended_vec": depended_vec,
        }
        return inputs


def get_dynamic_cdw_vec(
        config,
        max_dist,
        bert_spc_indices,
        aspect_indices,
        aspect_begin,
        syntactical_dist=None,
):
    # the function is used to set dynamic threshold and calculate cdm/cdw for DLCF_DCA_BERT
    a = config.dlcf_a
    if max_dist > 0:
        dynamic_threshold = math.log(max_dist, a) + a - 1
    else:
        dynamic_threshold = 3

    cdw_vec = np.zeros((config.max_seq_len), dtype=np.float32)
    aspect_len = np.count_nonzero(aspect_indices)
    text_len = np.count_nonzero(bert_spc_indices) - np.count_nonzero(aspect_indices) - 1
    if syntactical_dist is not None:
        for i in range(min(text_len, config.max_seq_len)):
            if max_dist > 0:
                if syntactical_dist[i] > dynamic_threshold:
                    w = 1 - syntactical_dist[i] / max_dist
                    cdw_vec[i] = w
                else:
                    cdw_vec[i] = 1
            else:
                cdw_vec[i] = 1
    else:
        local_context_begin = max(0, aspect_begin - dynamic_threshold)
        local_context_end = min(
            aspect_begin + aspect_len + dynamic_threshold - 1, config.max_seq_len
        )
        for i in range(min(text_len, config.max_seq_len)):
            if i < local_context_begin:
                w = 1 - (local_context_begin - i) / text_len
            elif local_context_begin <= i <= local_context_end:
                w = 1
            else:
                w = 1 - (i - local_context_end) / text_len
            try:
                assert 0 <= w <= 1  # exception
            except:
                fprint("Warning! invalid CDW weight:", w)
            cdw_vec[i] = 1
    return cdw_vec


def get_dynamic_cdm_vec(
        config,
        max_dist,
        bert_spc_indices,
        aspect_indices,
        aspect_begin,
        syntactical_dist=None,
):
    # the function is used to set dynamic threshold and calculate cdm/cdw for DLCF_DCA_BERT
    a = config.dlcf_a
    if max_dist > 0:
        dynamic_threshold = math.log(max_dist, a) + a - 1
    else:
        dynamic_threshold = 3

    cdm_vec = np.zeros((config.max_seq_len), dtype=np.float32)
    aspect_len = np.count_nonzero(aspect_indices)
    text_len = np.count_nonzero(bert_spc_indices) - np.count_nonzero(aspect_indices) - 1
    if syntactical_dist is not None:
        for i in range(min(text_len, config.max_seq_len)):
            if syntactical_dist[i] <= dynamic_threshold:
                cdm_vec[i] = 1
    else:
        local_context_begin = max(0, aspect_begin - dynamic_threshold)
        local_context_end = min(
            aspect_begin + aspect_len + dynamic_threshold - 1, config.max_seq_len
        )
        for i in range(min(text_len, config.max_seq_len)):
            if local_context_begin <= i <= local_context_end:
                cdm_vec[i] = 1
    return cdm_vec


def configure_dlcf_spacy_model(config):
    if not hasattr(config, "spacy_model"):
        config.spacy_model = "en_core_web_sm"
    global nlp
    try:
        nlp = spacy.load(config.spacy_model)
    except:
        fprint(
            "Can not load {} from spacy, try to download it in order to parse syntax tree:".format(
                config.spacy_model
            ),
            termcolor.colored(
                "\npython -m spacy download {}".format(config.spacy_model), "green"
            ),
        )
        try:
            os.system("python -m spacy download {}".format(config.spacy_model))
            nlp = spacy.load(config.spacy_model)
        except:
            raise RuntimeError(
                "Download failed, you can download {} manually.".format(
                    config.spacy_model
                )
            )
    return nlp


def calculate_cluster(sentence, aspect, config):
    terms = [a.lower() for a in aspect.split()]

    doc_list = []
    doc = [a.lower() for a in sentence.split()]
    for i in range(len(doc)):
        doc_list.append(i)

    doc = nlp(sentence.strip())
    # Load spacy's dependency tree into a networkx graph
    edges = []
    cnt = 0
    term_ids = [0] * len(terms)
    for token in doc:
        # Record the position of aspect terms
        if cnt < len(terms) and token.lower_ == terms[cnt]:
            term_ids[cnt] = token.i
            cnt += 1

        for child in token.children:
            edges.append((token.i, child.i))

    graph = nx.DiGraph(edges)
    graph2 = nx.Graph(edges)

    no_connect = []
    for i, word in enumerate(doc):
        source = i
        for j in term_ids:
            target = j
            try:
                sum = nx.shortest_path_length(graph2, source=source, target=target)
            except:
                if (i not in no_connect) and (i not in term_ids):
                    no_connect.append(i)

    depend_ids = []
    depended_ids = doc_list
    for k in range(len(terms)):
        temp_aspcet_ids = term_ids[k]
        try:
            temp_nodes = list(nx.dfs_preorder_nodes(graph, source=temp_aspcet_ids))
        except:
            temp_nodes = [temp_aspcet_ids]

        for i in range(len(temp_nodes)):
            flag = 1
            for j in range(len(depend_ids)):
                if depend_ids[j] == temp_nodes[i]:
                    flag = 0
            if flag == 1:
                depend_ids.append(temp_nodes[i])

    for i in range(len(depend_ids)):
        s = depend_ids[i]
        if s in depended_ids:
            depended_ids.remove(s)

    for i in range(len(terms)):
        temp_aspcet_ids = term_ids[i]
        if temp_aspcet_ids in depend_ids:
            depend_ids.remove(temp_aspcet_ids)

    for i in range(len(terms)):
        temp_aspcet_ids = term_ids[i]
        if temp_aspcet_ids in depended_ids:
            depended_ids.remove(temp_aspcet_ids)

    for i in range(len(no_connect)):
        if no_connect[i] in depended_ids:
            depended_ids.remove(no_connect[i])

    depend_vec = np.zeros((config.max_seq_len), dtype=np.float32)
    depended_vec = np.zeros((config.max_seq_len), dtype=np.float32)

    depended_vec[0] = 1
    depend_vec[0] = 1
    for i in range(len(depend_ids)):
        if depend_ids[i] < (config.max_seq_len - 1):
            depend_vec[depend_ids[i] + 1] = 1
    for i in range(len(depended_ids)):
        if depended_ids[i] < (config.max_seq_len - 1):
            depended_vec[depended_ids[i] + 1] = 1
    return depend_vec, depended_vec
