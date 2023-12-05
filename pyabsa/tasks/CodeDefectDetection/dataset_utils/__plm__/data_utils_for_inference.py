# -*- coding: utf-8 -*-
# file: data_utils_for_inference.py
# time: 02/11/2022 15:39
# author: YANG, HENG <hy345@exeter.ac.uk> (杨恒)
# github: https://github.com/yangheng95
# GScholar: https://scholar.google.com/citations?user=NPq5a_0AAAAJ&hl=en
# ResearchGate: https://www.researchgate.net/profile/Heng-Yang-17/research
# Copyright (C) 2022. All Rights Reserved.

import tqdm
from torch.utils.data import Dataset

from pyabsa.framework.dataset_class.dataset_template import PyABSADataset
from pyabsa.framework.tokenizer_class.tokenizer_class import pad_and_truncate
from pyabsa.utils.file_utils.file_utils import load_dataset_from_file
from pyabsa.utils.pyabsa_utils import fprint
from ..cdd_utils import read_defect_examples


class BERTCDDInferenceDataset(Dataset):
    def __init__(self, config, tokenizer):
        self.tokenizer = tokenizer
        self.config = config
        self.data = []

    def parse_sample(self, text):
        return [text]

    def prepare_infer_sample(self, text: str, ignore_error):
        if isinstance(text, list):
            self.process_data(text, ignore_error=ignore_error)
        else:
            self.process_data(self.parse_sample(text), ignore_error=ignore_error)

    def prepare_infer_dataset(self, infer_file, ignore_error):
        lines = load_dataset_from_file(infer_file, config=self.config)
        samples = []
        for sample in lines:
            if sample:
                samples.extend(self.parse_sample(sample))
        self.process_data(samples, ignore_error)

    def process_data(self, samples, ignore_error=True):
        samples = read_defect_examples(
            samples,
            self.config.get("data_num", None),
            self.config.get("remove_comments", True),
            # tokenizer=self.tokenizer,
        )
        all_data = []
        if len(samples) > 100:
            it = tqdm.tqdm(samples, desc="preparing text classification dataloader")
        else:
            it = samples
        for ex_id, text in enumerate(it):
            try:
                # handle for empty lines in inference datasets
                if text is None or "" == text.strip():
                    raise RuntimeError("Invalid Input!")

                code_src, _, label = text.strip().partition("$LABEL$")
                if "$FEATURE$" in code_src:
                    code_src, feature = code_src.split("$FEATURE$")
                # print(len(self.tokenizer.tokenize(code_src.replace('\n', ''))))

                code_ids = self.tokenizer.text_to_sequence(
                    code_src,
                    max_length=self.config.max_seq_len,
                    padding="do_not_pad",
                    truncation=False,
                )
                code_ids = self.prepare_token_ids(
                    code_ids, self.config.get("sliding_window", False)
                )
                for ids in code_ids:
                    all_data.append(
                        {
                            "ex_id": ex_id,
                            "code": code_src,
                            "source_ids": ids,
                            "label": self.config.label_to_index[label],
                            "corrupt_label": 0,
                        }
                    )

            except Exception as e:
                if ignore_error:
                    fprint("Ignore error while processing:", text)
                else:
                    raise e

        self.data = all_data

        self.data = PyABSADataset.covert_to_tensor(self.data)

        return self.data

    def prepare_token_ids(self, code_ids, sliding_window=False):
        all_code_ids = []
        code_ids = code_ids[1:-1]
        if sliding_window is False:
            code_ids = pad_and_truncate(
                code_ids,
                self.config.max_seq_len - 2,
                value=self.tokenizer.pad_token_id,
            )
            all_code_ids.append(
                [self.tokenizer.cls_token_id] + code_ids + [self.tokenizer.eos_token_id]
            )
            if all_code_ids[-1].count(self.tokenizer.eos_token_id) != 1:
                raise ValueError("last token id is not eos token id")
            return all_code_ids

        else:
            code_ids = pad_and_truncate(
                code_ids,
                self.config.max_seq_len - 2,
                value=self.tokenizer.pad_token_id,
            )
            # for x in range(len(code_ids) // ((self.config.max_seq_len - 2) // 2) + 1):
            #     _code_ids = code_ids[x * (self.config.max_seq_len - 2) // 2:
            #                          (x + 1) * (self.config.max_seq_len - 2) // 2 + (self.config.max_seq_len - 2) // 2]
            #     print(x * (self.config.max_seq_len - 2) // 2)
            #     print((x + 1) * (self.config.max_seq_len - 2) // 2 + (self.config.max_seq_len - 2) // 2)
            for x in range(len(code_ids) // (self.config.max_seq_len - 2) + 1):
                _code_ids = code_ids[
                            x
                            * (self.config.max_seq_len - 2): (x + 1)
                                                             * (self.config.max_seq_len - 2)
                            ]
                _code_ids = pad_and_truncate(
                    _code_ids,
                    self.config.max_seq_len - 2,
                    value=self.tokenizer.pad_token_id,
                )
                if _code_ids:
                    all_code_ids.append(
                        [self.tokenizer.cls_token_id]
                        + _code_ids
                        + [self.tokenizer.eos_token_id]
                    )
                if all_code_ids[-1].count(self.tokenizer.eos_token_id) != 1:
                    raise ValueError("last token id is not eos token id")
            return all_code_ids

    def __getitem__(self, index):
        return self.data[index]

    def __len__(self):
        return len(self.data)
