# -*- coding: utf-8 -*-
# file: aspect_term_extraction.py
# time: 2021/5/26 0026
# author: YANG, HENG <hy345@exeter.ac.uk> (杨恒)
# github: https://github.com/yangheng95
# Copyright (C) 2021. All Rights Reserved.

import json
import os
import pickle
from collections import OrderedDict
from pathlib import Path
from typing import Union, List

import torch
import torch.nn.functional as F
import tqdm
from findfile import find_file, find_cwd_dir
from termcolor import colored
from torch.utils.data import DataLoader, SequentialSampler, TensorDataset
from transformers import AutoTokenizer, AutoModel

from pyabsa.framework.flag_class.flag_template import (
    LabelPaddingOption,
    TaskCodeOption,
    DeviceTypeOption,
)
from pyabsa.framework.prediction_class.predictor_template import InferenceModel
from pyabsa.utils.data_utils.dataset_item import DatasetItem
from pyabsa.utils.data_utils.dataset_manager import detect_infer_dataset
from pyabsa.utils.pyabsa_utils import set_device, print_args, fprint
from ..dataset_utils.__lcf__.atepc_utils import (
    load_atepc_inference_datasets,
    process_iob_tags,
)
from ..dataset_utils.__lcf__.data_utils_for_inference import (
    ATEPCProcessor,
    convert_ate_examples_to_features,
    convert_apc_examples_to_features,
)
from ..dataset_utils.__lcf__.data_utils_for_training import split_aspect
from ..models import ATEPCModelList


class AspectExtractor(InferenceModel):
    task_code = TaskCodeOption.Aspect_Term_Extraction_and_Classification

    def __init__(self, checkpoint=None, **kwargs):
        # load from a trainer
        super().__init__(checkpoint, task_code=self.task_code, **kwargs)

        if self.checkpoint and not isinstance(self.checkpoint, str):
            fprint("Load aspect extractor from trainer")
            self.model = self.checkpoint[0]
            self.config = self.checkpoint[1]
            self.tokenizer = self.checkpoint[2]
        else:
            if "fine-tuned" in self.checkpoint:
                raise ValueError(
                    "Do not support to directly load a fine-tuned model, please load a .state_dict or .model instead!"
                )
            fprint("Load aspect extractor from", self.checkpoint)
            try:
                state_dict_path = find_file(
                    self.checkpoint, ".state_dict", exclude_key=["__MACOSX"]
                )
                model_path = find_file(
                    self.checkpoint, ".model", exclude_key=["__MACOSX"]
                )
                tokenizer_path = find_file(
                    self.checkpoint, ".tokenizer", exclude_key=["__MACOSX"]
                )
                config_path = find_file(
                    self.checkpoint, ".config", exclude_key=["__MACOSX"]
                )

                fprint("config: {}".format(config_path))
                fprint("state_dict: {}".format(state_dict_path))
                fprint("model: {}".format(model_path))
                fprint("tokenizer: {}".format(tokenizer_path))

                with open(config_path, mode="rb") as f:
                    self.config = pickle.load(f)
                    self.config.auto_device = kwargs.get("auto_device", True)
                    set_device(self.config, self.config.auto_device)

                if state_dict_path or model_path:
                    if state_dict_path:
                        if kwargs.get("offline", False):
                            self.bert = AutoModel.from_pretrained(
                                find_cwd_dir(
                                    self.config.pretrained_bert.split("/")[-1]
                                ),
                            )
                        else:
                            self.bert = AutoModel.from_pretrained(
                                self.config.pretrained_bert,
                            )

                        self.model = self.config.model(self.bert, self.config)
                        self.model.load_state_dict(
                            torch.load(
                                state_dict_path, map_location=DeviceTypeOption.CPU
                            ),
                            strict=False,
                        )
                    elif model_path:
                        self.model = torch.load(
                            model_path, map_location=DeviceTypeOption.CPU
                        )
                    with open(tokenizer_path, mode="rb") as f:
                        try:
                            if kwargs.get("offline", False):
                                self.tokenizer = AutoTokenizer.from_pretrained(
                                    find_cwd_dir(
                                        self.config.pretrained_bert.split("/")[-1]
                                    ),
                                    do_lower_case="uncased"
                                                  in self.config.pretrained_bert,
                                )
                            else:
                                self.tokenizer = AutoTokenizer.from_pretrained(
                                    self.config.pretrained_bert,
                                    do_lower_case="uncased"
                                                  in self.config.pretrained_bert,
                                )
                        except ValueError:
                            self.tokenizer = pickle.load(f)

            except Exception as e:
                raise RuntimeError(
                    "Exception: {} Fail to load the model from {}! ".format(
                        e, self.checkpoint
                    )
                )

            if not hasattr(ATEPCModelList, self.model.__class__.__name__):
                raise KeyError(
                    "The checkpoint you are loading is not from any ATEPC model."
                )

        self.processor = ATEPCProcessor(self.tokenizer)
        self.num_labels = len(self.config.label_list) + 1

        if kwargs.get("verbose", False):
            fprint("Config used in Training:")
            print_args(self.config)

        if self.config.gradient_accumulation_steps < 1:
            raise ValueError(
                "Invalid gradient_accumulation_steps parameter: {}, should be >= 1".format(
                    self.config.gradient_accumulation_steps
                )
            )

        self.eval_dataloader = None

        self.__post_init__(**kwargs)

    def merge_result(self, sentence_res, results):
        """merge ate sentence result and apc results, and restore to original sentence order
        Args:
            sentence_res ([tuple]): list of ate sentence results, which has (tokens, iobs)
            results ([dict]): list of apc results
        Returns:
            [dict]: merged extraction/polarity results for each input example
        """
        final_res = []
        if results["polarity_res"] is not None:
            merged_results = OrderedDict()
            pre_example_id = None
            # merge ate and apc results, assume they are same ordered
            for item1, item2 in zip(results["extraction_res"], results["polarity_res"]):
                cur_example_id = item1[3]
                assert (
                        cur_example_id == item2["example_id"]
                ), "ate and apc results should be same ordered"
                if pre_example_id is None or cur_example_id != pre_example_id:
                    merged_results[cur_example_id] = {
                        "sentence": item2["sentence"],
                        "aspect": [item2["aspect"]],
                        "position": [item2["pos_ids"]],
                        "sentiment": [item2["sentiment"]],
                        "probs": [item2["probs"]],
                        "confidence": [item2["confidence"]],
                    }
                else:
                    merged_results[cur_example_id]["aspect"].append(item2["aspect"])
                    merged_results[cur_example_id]["position"].append(item2["pos_ids"])
                    merged_results[cur_example_id]["sentiment"].append(
                        item2["sentiment"]
                    )
                    merged_results[cur_example_id]["probs"].append(item2["probs"])
                    merged_results[cur_example_id]["confidence"].append(
                        item2["confidence"]
                    )
                # remember example id
                pre_example_id = item1[3]
            for i, item in enumerate(sentence_res):
                asp_res = merged_results.get(i)
                final_res.append(
                    {
                        "sentence": " ".join(item[0]),
                        "IOB": item[1],
                        "tokens": item[0],
                        "aspect": asp_res["aspect"] if asp_res else [],
                        "position": asp_res["position"] if asp_res else [],
                        "sentiment": asp_res["sentiment"] if asp_res else [],
                        "probs": asp_res["probs"] if asp_res else [],
                        "confidence": asp_res["confidence"] if asp_res else [],
                    }
                )
        else:
            for item in sentence_res:
                final_res.append(
                    {"sentence": " ".join(item[0]), "IOB": item[1], "tokens": item[0]}
                )

        return final_res

    def extract_aspect(
            self,
            inference_source: Union[List[Path], list, str],
            save_result=True,
            print_result=True,
            pred_sentiment=True,
            **kwargs
    ):
        """
        Extract aspects and their corresponding polarities from a list of input files.

        Args:
            self: An instance of the model class.
            inference_source: A list of file paths, or a directory containing files to be processed.
            save_result (bool): Whether to save the output to a file. Default is True.
            print_result (bool): Whether to print the output to the console. Default is True.
            pred_sentiment (bool): Whether to predict the sentiment of each aspect. Default is True.
            **kwargs: Additional keyword arguments to be passed to the `batch_predict` method.

        Returns:
            The predicted aspects and their corresponding polarities.
        """
        return self.batch_predict(
            inference_source, save_result, print_result, pred_sentiment, **kwargs
        )

    def predict(
            self,
            text: Union[str, List[str]],
            save_result=True,
            print_result=True,
            pred_sentiment=True,
            **kwargs
    ):
        """
        Args:
            text (str): input example
            save_result (bool): whether to save the result to file
            print_result (bool): whether to print the result to console
            pred_sentiment (bool): whether to predict sentiment
        """
        if isinstance(text, str):
            return self.batch_predict(
                [text], save_result, print_result, pred_sentiment, **kwargs
            )[0]
        elif isinstance(text, list):
            return self.batch_predict(
                text, save_result, print_result, pred_sentiment, **kwargs
            )

    def batch_predict(
            self,
            target_file: Union[List[Path], list, str],
            save_result=True,
            print_result=True,
            pred_sentiment=True,
            **kwargs
    ):
        """
        Args:
            target_file (list): list of input examples or a list of files to be predicted
            save_result (bool, optional): save result to file. Defaults to True.
            print_result (bool, optional): print result to console. Defaults to True.
            pred_sentiment (bool, optional): predict sentiment. Defaults to True.
        Returns:
        """

        self.config.eval_batch_size = kwargs.get("eval_batch_size", 32)

        results = {"extraction_res": OrderedDict(), "polarity_res": OrderedDict()}
        if isinstance(target_file, DatasetItem) or isinstance(target_file, str):
            # using integrated inference dataset
            inference_set = detect_infer_dataset(
                target_file, task_code=TaskCodeOption.Aspect_Polarity_Classification
            )
            target_file = load_atepc_inference_datasets(inference_set)

        elif isinstance(target_file, list):
            pass

        else:
            raise ValueError(
                "Please run inference using examples list or inference dataset path (list)!"
            )

        if target_file:
            extraction_res, sentence_res = self._extract(target_file)
            results["extraction_res"] = extraction_res
            if pred_sentiment:
                results["polarity_res"] = self._run_prediction(
                    results["extraction_res"]
                )
            results = self.merge_result(sentence_res, results)
            if save_result:
                save_path = os.path.join(
                    os.getcwd(),
                    "{}.{}.result.json".format(
                        self.config.task_name, self.config.model.__name__
                    ),
                )
                fprint(
                    "The results of aspect term extraction have been saved in {}".format(
                        save_path
                    )
                )
                with open(save_path, "w", encoding="utf8") as f:
                    json.dump(results, f, ensure_ascii=False)
            if print_result:
                for ex_id, r in enumerate(results):
                    colored_text = r["sentence"][:]
                    for aspect, sentiment, confidence in zip(
                            r["aspect"], r["sentiment"], r["confidence"]
                    ):
                        if sentiment.upper() == "POSITIVE":
                            colored_aspect = colored(
                                "<{}:{} Confidence:{}>".format(
                                    aspect, sentiment, confidence
                                ),
                                "green",
                            )
                        elif sentiment.upper() == "NEUTRAL":
                            colored_aspect = colored(
                                "<{}:{} Confidence:{}>".format(
                                    aspect, sentiment, confidence
                                ),
                                "cyan",
                            )
                        elif sentiment.upper() == "NEGATIVE":
                            colored_aspect = colored(
                                "<{}:{} Confidence:{}>".format(
                                    aspect, sentiment, confidence
                                ),
                                "red",
                            )
                        else:
                            colored_aspect = colored(
                                "<{}:{} Confidence:{}>".format(
                                    aspect, sentiment, confidence
                                ),
                                "magenta",
                            )
                        colored_text = colored_text.replace(
                            " {} ".format(aspect), " {} ".format(colored_aspect), 1
                        )
                    res_format = "Example {}: {}".format(ex_id, colored_text)
                    fprint(res_format)

            return results

    # Temporal code, pending configimization
    def _extract(self, examples):
        sentence_res = []  # extraction result by sentence
        extraction_res = []  # extraction result flatten by aspect

        self.infer_dataloader = None
        examples = self.processor.get_examples_for_aspect_extraction(examples)
        infer_features = convert_ate_examples_to_features(
            examples,
            self.config.label_list,
            self.config.max_seq_len,
            self.tokenizer,
            self.config,
        )
        all_spc_input_ids = torch.tensor(
            [f.input_ids_spc for f in infer_features], dtype=torch.long
        )
        all_segment_ids = torch.tensor(
            [f.segment_ids for f in infer_features], dtype=torch.long
        )
        all_input_mask = torch.tensor(
            [f.input_mask for f in infer_features], dtype=torch.long
        )
        all_label_ids = torch.tensor(
            [f.label_id for f in infer_features], dtype=torch.long
        )
        all_polarities = torch.tensor(
            [f.polarity for f in infer_features], dtype=torch.long
        )
        all_valid_ids = torch.tensor(
            [f.valid_ids for f in infer_features], dtype=torch.long
        )
        all_lmask_ids = torch.tensor(
            [f.label_mask for f in infer_features], dtype=torch.long
        )

        all_tokens = [f.tokens for f in infer_features]
        infer_data = TensorDataset(
            all_spc_input_ids,
            all_segment_ids,
            all_input_mask,
            all_label_ids,
            all_polarities,
            all_valid_ids,
            all_lmask_ids,
        )
        # Run prediction for full raw_data
        infer_sampler = SequentialSampler(infer_data)
        self.infer_dataloader = DataLoader(
            infer_data,
            sampler=infer_sampler,
            pin_memory=True,
            batch_size=self.config.eval_batch_size,
        )

        # extract_aspects
        self.model.eval()
        if "index_to_IOB_label" not in self.config.args:
            label_map = {i: label for i, label in enumerate(self.config.label_list, 1)}
        else:
            label_map = self.config.index_to_IOB_label
        if len(infer_data) >= 100:
            it = tqdm.tqdm(self.infer_dataloader, desc="extracting aspect terms")
        else:
            it = self.infer_dataloader
        for i_batch, (
                input_ids_spc,
                segment_ids,
                input_mask,
                label_ids,
                polarity,
                valid_ids,
                l_mask,
        ) in enumerate(it):
            input_ids_spc = input_ids_spc.to(self.config.device)
            segment_ids = segment_ids.to(self.config.device)
            input_mask = input_mask.to(self.config.device)
            label_ids = label_ids.to(self.config.device)
            polarity = polarity.to(self.config.device)
            valid_ids = valid_ids.to(self.config.device)
            l_mask = l_mask.to(self.config.device)
            with torch.no_grad():
                ate_logits, apc_logits = self.model(
                    input_ids_spc,
                    token_type_ids=segment_ids,
                    attention_mask=input_mask,
                    labels=None,
                    polarity=polarity,
                    valid_ids=valid_ids,
                    attention_mask_label=l_mask,
                )
            if self.config.use_bert_spc:
                label_ids = self.model.get_batch_token_labels_bert_base_indices(
                    label_ids
                )
            ate_logits = torch.argmax(F.log_softmax(ate_logits, dim=2), dim=2)
            ate_logits = ate_logits.detach().cpu().numpy()
            label_ids = label_ids.to(DeviceTypeOption.CPU).numpy()
            for i, i_ate_logits in enumerate(ate_logits):
                pred_iobs = []
                sentence_res.append(
                    (all_tokens[i + (self.config.eval_batch_size * i_batch)], pred_iobs)
                )
                for j, m in enumerate(label_ids[i]):
                    if j == 0:
                        continue
                    elif len(pred_iobs) == len(
                            all_tokens[i + (self.config.eval_batch_size * i_batch)]
                    ):
                        break
                    else:
                        pred_iobs.append(label_map.get(i_ate_logits[j], "O"))

                ate_result = []
                polarity = []
                for t, l in zip(
                        all_tokens[i + (self.config.eval_batch_size * i_batch)], pred_iobs
                ):
                    ate_result.append("{}({})".format(t, l))
                    if "ASP" in l:
                        polarity.append(
                            abs(LabelPaddingOption.SENTIMENT_PADDING)
                        )  # 1 tags the valid position aspect terms
                    else:
                        polarity.append(LabelPaddingOption.SENTIMENT_PADDING)

                POLARITY_PADDING = [LabelPaddingOption.SENTIMENT_PADDING] * len(
                    polarity
                )
                example_id = i_batch * self.config.eval_batch_size + i
                pred_iobs = process_iob_tags(pred_iobs)
                for idx in range(1, len(polarity)):
                    if polarity[idx - 1] != str(
                            LabelPaddingOption.SENTIMENT_PADDING
                    ) and split_aspect(pred_iobs[idx - 1], pred_iobs[idx]):
                        _polarity = polarity[:idx] + POLARITY_PADDING[idx:]
                        polarity = POLARITY_PADDING[:idx] + polarity[idx:]
                        extraction_res.append(
                            (
                                all_tokens[i + (self.config.eval_batch_size * i_batch)],
                                pred_iobs,
                                _polarity,
                                example_id,
                            )
                        )

                    if (
                            polarity[idx] != str(LabelPaddingOption.SENTIMENT_PADDING)
                            and idx == len(polarity) - 1
                            and split_aspect(pred_iobs[idx])
                    ):
                        _polarity = polarity[: idx + 1] + POLARITY_PADDING[idx + 1:]
                        polarity = POLARITY_PADDING[: idx + 1] + polarity[idx + 1:]
                        extraction_res.append(
                            (
                                all_tokens[i + (self.config.eval_batch_size * i_batch)],
                                pred_iobs,
                                _polarity,
                                example_id,
                            )
                        )

        return extraction_res, sentence_res

    def _run_prediction(self, examples):
        res = []  # sentiment classification result
        # ate example id map to apc example id
        example_id_map = dict([(apc_id, ex[3]) for apc_id, ex in enumerate(examples)])

        self.infer_dataloader = None
        examples = self.processor.get_examples_for_sentiment_classification(examples)
        infer_features = convert_apc_examples_to_features(
            examples,
            self.config.label_list,
            self.config.max_seq_len,
            self.tokenizer,
            self.config,
        )
        all_spc_input_ids = torch.tensor(
            [f.input_ids_spc for f in infer_features], dtype=torch.long
        )
        all_segment_ids = torch.tensor(
            [f.segment_ids for f in infer_features], dtype=torch.long
        )
        all_input_mask = torch.tensor(
            [f.input_mask for f in infer_features], dtype=torch.long
        )
        all_label_ids = torch.tensor(
            [f.label_id for f in infer_features], dtype=torch.long
        )
        all_valid_ids = torch.tensor(
            [f.valid_ids for f in infer_features], dtype=torch.long
        )
        all_lmask_ids = torch.tensor(
            [f.label_mask for f in infer_features], dtype=torch.long
        )
        lcf_cdm_vec = torch.tensor(
            [f.lcf_cdm_vec for f in infer_features], dtype=torch.float32
        )
        lcf_cdw_vec = torch.tensor(
            [f.lcf_cdw_vec for f in infer_features], dtype=torch.float32
        )
        all_tokens = [f.tokens for f in infer_features]
        all_aspects = [f.aspect for f in infer_features]
        all_positions = [f.positions for f in infer_features]
        infer_data = TensorDataset(
            all_spc_input_ids,
            all_segment_ids,
            all_input_mask,
            all_label_ids,
            all_valid_ids,
            all_lmask_ids,
            lcf_cdm_vec,
            lcf_cdw_vec,
        )
        # Run prediction for full raw_data
        self.model.config.use_bert_spc = True

        infer_sampler = SequentialSampler(infer_data)
        self.infer_dataloader = DataLoader(
            infer_data,
            sampler=infer_sampler,
            pin_memory=True,
            batch_size=self.config.eval_batch_size,
        )

        # extract_aspects
        self.model.eval()

        # Correct = {True: 'Correct', False: 'Wrong'}
        if len(infer_data) >= 100:
            it = tqdm.tqdm(self.infer_dataloader, desc="classifying aspect sentiments")
        else:
            it = self.infer_dataloader
        for i_batch, batch in enumerate(it):
            (
                input_ids_spc,
                segment_ids,
                input_mask,
                label_ids,
                valid_ids,
                l_mask,
                lcf_cdm_vec,
                lcf_cdw_vec,
            ) = batch
            input_ids_spc = input_ids_spc.to(self.config.device)
            segment_ids = segment_ids.to(self.config.device)
            input_mask = input_mask.to(self.config.device)
            label_ids = label_ids.to(self.config.device)
            valid_ids = valid_ids.to(self.config.device)
            l_mask = l_mask.to(self.config.device)
            lcf_cdm_vec = lcf_cdm_vec.to(self.config.device)
            lcf_cdw_vec = lcf_cdw_vec.to(self.config.device)
            with torch.no_grad():
                ate_logits, apc_logits = self.model(
                    input_ids_spc,
                    token_type_ids=segment_ids,
                    attention_mask=input_mask,
                    labels=None,
                    valid_ids=valid_ids,
                    attention_mask_label=l_mask,
                    lcf_cdm_vec=lcf_cdm_vec,
                    lcf_cdw_vec=lcf_cdw_vec,
                )
                for i, i_apc_logits in enumerate(apc_logits):
                    if (
                            "index_to_label" in self.config.args
                            and int(i_apc_logits.argmax(axis=-1))
                            in self.config.index_to_label
                    ):
                        sent = self.config.index_to_label.get(
                            int(i_apc_logits.argmax(axis=-1))
                        )
                    else:
                        sent = int(torch.argmax(i_apc_logits, -1))
                    result = {}
                    probs = [
                        float(x)
                        for x in F.softmax(i_apc_logits, dim=-1).cpu().numpy().tolist()
                    ]
                    apc_id = i_batch * self.config.eval_batch_size + i
                    result["sentence"] = " ".join(all_tokens[apc_id])
                    result["tokens"] = all_tokens[apc_id]
                    result["probs"] = probs
                    result["confidence"] = round(max(probs), 4)
                    result["aspect"] = all_aspects[apc_id]
                    result["pos_ids"] = [x - 1 for x in all_positions[apc_id]]
                    result["sentiment"] = sent
                    result["example_id"] = example_id_map[apc_id]
                    res.append(result)

        return res


class Predictor(AspectExtractor):
    pass
