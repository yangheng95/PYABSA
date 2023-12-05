import json
import os
import pickle
from typing import Union

import numpy as np
import torch
import tqdm
from findfile import find_file, find_cwd_dir
from sklearn import metrics
from termcolor import colored
from torch.utils.data import DataLoader
from transformers import AutoModel

from pyabsa import TaskCodeOption, LabelPaddingOption, DeviceTypeOption
from pyabsa.framework.prediction_class.predictor_template import InferenceModel
from pyabsa.framework.tokenizer_class.tokenizer_class import PretrainedTokenizer
from pyabsa.utils.data_utils.dataset_manager import detect_infer_dataset
from pyabsa.utils.pyabsa_utils import set_device, print_args, fprint, rprint
from ..dataset_utils.__classic__.data_utils_for_inference import (
    GloVeCDDInferenceDataset,
)
from ..dataset_utils.__plm__.data_utils_for_inference import BERTCDDInferenceDataset
from ..models import BERTCDDModelList, GloVeCDDModelList


class CodeDefectDetector(InferenceModel):
    task_code = TaskCodeOption.CodeDefectDetection

    def __init__(self, checkpoint=None, cal_perplexity=False, **kwargs):
        """
        from_train_model: load inference model from trained model
        """

        super().__init__(checkpoint, task_code=self.task_code, **kwargs)

        # load from a trainer
        if self.checkpoint and not isinstance(self.checkpoint, str):
            fprint("Load text classifier from trainer")
            self.model = self.checkpoint[0]
            self.config = self.checkpoint[1]
            self.tokenizer = self.checkpoint[2]
        else:
            try:
                if "fine-tuned" in self.checkpoint:
                    raise ValueError(
                        "Do not support to directly load a fine-tuned model, please load a .state_dict or .model instead!"
                    )
                fprint("Load code defect detector from", self.checkpoint)
                state_dict_path = find_file(
                    self.checkpoint, key=".state_dict", exclude_key=["__MACOSX"]
                )
                model_path = find_file(
                    self.checkpoint, key=".model", exclude_key=["__MACOSX"]
                )
                tokenizer_path = find_file(
                    self.checkpoint, key=".tokenizer", exclude_key=["__MACOSX"]
                )
                config_path = find_file(
                    self.checkpoint, key=".config", exclude_key=["__MACOSX"]
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
                    if hasattr(BERTCDDModelList, self.config.model.__name__):
                        if state_dict_path:
                            if kwargs.get("offline", False):
                                self.bert = AutoModel.from_pretrained(
                                    find_cwd_dir(
                                        self.config.pretrained_bert.split("/")[-1]
                                    )
                                )
                            else:
                                self.bert = AutoModel.from_pretrained(
                                    self.config.pretrained_bert
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

                    else:
                        self.embedding_matrix = self.config.embedding_matrix
                        self.tokenizer = self.config.tokenizer
                        if model_path:
                            self.model = torch.load(
                                model_path, map_location=DeviceTypeOption.CPU
                            )
                        else:
                            self.model = self.config.model(
                                self.embedding_matrix, self.config
                            ).to(self.config.device)
                            self.model.load_state_dict(
                                torch.load(
                                    state_dict_path, map_location=DeviceTypeOption.CPU
                                )
                            )

                self.tokenizer = self.config.tokenizer

                if kwargs.get("verbose", False):
                    fprint("Config used in Training:")
                    print_args(self.config)

            except Exception as e:
                raise RuntimeError(
                    "Exception: {} Fail to load the model from {}! ".format(
                        e, self.checkpoint
                    )
                )

            if not hasattr(
                    GloVeCDDModelList, self.config.model.__name__
            ) and not hasattr(BERTCDDModelList, self.config.model.__name__):
                raise KeyError(
                    "The checkpoint and PyABSA you are loading is not from classifier model."
                )

        if hasattr(BERTCDDModelList, self.config.model.__name__):
            self.dataset = BERTCDDInferenceDataset(
                config=self.config, tokenizer=self.tokenizer
            )

        elif hasattr(GloVeCDDModelList, self.config.model.__name__):
            self.dataset = GloVeCDDInferenceDataset(
                config=self.config, tokenizer=self.tokenizer
            )

        self.__post_init__(**kwargs)

    def _log_write_args(self):
        n_trainable_params, n_nontrainable_params = 0, 0
        for p in self.model.parameters():
            n_params = torch.prod(torch.tensor(p.shape))
            if p.requires_grad:
                n_trainable_params += n_params
            else:
                n_nontrainable_params += n_params
        fprint(
            "n_trainable_params: {0}, n_nontrainable_params: {1}".format(
                n_trainable_params, n_nontrainable_params
            )
        )
        for arg in vars(self.config):
            if getattr(self.config, arg) is not None:
                fprint(">>> {0}: {1}".format(arg, getattr(self.config, arg)))

    def batch_infer(
            self,
            target_file=None,  # A file containing text inputs to perform inference on
            print_result=True,  # Whether to print the result of each prediction
            save_result=False,  # Whether to save the result of each prediction
            ignore_error=True,  # Whether to ignore errors encountered during inference
            **kwargs  # Additional keyword arguments to be passed to batch_predict method
    ):
        """
        Perform batch inference on a given target file.

        Args:
        - target_file: A file containing text inputs to perform inference on
        - print_result: Whether to print the result of each prediction
        - save_result: Whether to save the result of each prediction
        - ignore_error: Whether to ignore errors encountered during inference
        - **kwargs: Additional keyword arguments to be passed to batch_predict method

        Returns:
        - A list of prediction results
        """
        return self.batch_predict(
            target_file=target_file,
            print_result=print_result,
            save_result=save_result,
            ignore_error=ignore_error,
            **kwargs
        )

    def infer(
            self,
            text: Union[str, list] = None,  # The text inputs to perform inference on
            print_result=True,  # Whether to print the result of each prediction
            ignore_error=True,  # Whether to ignore errors encountered during inference
            **kwargs  # Additional keyword arguments to be passed to predict method
    ):
        """
        Perform inference on a given text input.

        Args:
        - text: The text inputs to perform inference on
        - print_result: Whether to print the result of each prediction
        - ignore_error: Whether to ignore errors encountered during inference
        - **kwargs: Additional keyword arguments to be passed to predict method

        Returns:
        - A list of prediction results
        """
        return self.predict(
            text=text, print_result=print_result, ignore_error=ignore_error, **kwargs
        )

    def batch_predict(
            self,
            target_file=None,
            print_result=True,
            save_result=False,
            ignore_error=True,
            **kwargs
    ):
        """
        Predict from a file of labelences.
        param: target_file: the file path of the labelences to be predicted.
        param: print_result: whether to print the result.
        param: save_result: whether to save the result.
        param: ignore_error: whether to ignore the error when predicting.
        param: kwargs: other parameters.
        """
        self.config.eval_batch_size = kwargs.get("eval_batch_size", 32)

        save_path = os.path.join(
            os.getcwd(),
            "{}.{}.result.json".format(
                self.config.task_name, self.config.model.__name__
            ),
        )

        target_file = detect_infer_dataset(
            target_file, task_code=TaskCodeOption.CodeDefectDetection
        )
        if not target_file:
            raise FileNotFoundError("Can not find inference datasets!")

        self.dataset.prepare_infer_dataset(target_file, ignore_error=ignore_error)
        self.infer_dataloader = DataLoader(
            dataset=self.dataset,
            batch_size=self.config.eval_batch_size,
            pin_memory=True,
            shuffle=False,
        )
        return self._run_prediction(
            save_path=save_path if save_result else None, print_result=print_result
        )

    def predict(
            self,
            text: Union[str, list] = None,
            print_result=True,
            ignore_error=True,
            **kwargs
    ):
        """
        Predict from a labelence or a list of labelences.
        param: text: the labelence or a list of labelence to be predicted.
        param: print_result: whether to print the result.
        param: ignore_error: whether to ignore the error when predicting.
        param: kwargs: other parameters.
        """
        self.config.eval_batch_size = kwargs.get("eval_batch_size", 32)
        self.infer_dataloader = DataLoader(
            dataset=self.dataset, batch_size=self.config.eval_batch_size, shuffle=False
        )
        if text:
            self.dataset.prepare_infer_sample(text, ignore_error=ignore_error)
        else:
            raise RuntimeError("Please specify your datasets path!")
        if isinstance(text, str):
            return self._run_prediction(print_result=print_result)[0]
        else:
            return self._run_prediction(print_result=print_result)

    def _run_prediction(self, save_path=None, print_result=True):
        _params = filter(lambda p: p.requires_grad, self.model.parameters())

        correct = {True: "Correct", False: "Wrong"}
        results = []
        with torch.no_grad():
            self.model.eval()
            n_correct = 0
            n_labeled = 0
            n_total = 0
            targets_all, t_outputs_all = None, None
            c_targets_all, t_c_outputs_all = None, None

            if len(self.infer_dataloader.dataset) >= 100:
                it = tqdm.tqdm(self.infer_dataloader, desc="run inference")
            else:
                it = self.infer_dataloader
            for _, sample in enumerate(it):
                try:
                    inputs = [
                        sample[col].to(self.config.device)
                        for col in self.config.inputs_cols
                    ]
                except Exception as e:
                    # bug fix for typo in config
                    inputs = [
                        sample[col].to(self.config.device) for col in self.config.inputs
                    ]
                targets = sample["label"].to(self.config.device)
                c_targets = sample["corrupt_label"].to(self.config.device)
                outputs = self.model(inputs)
                logits, c_logits = outputs["logits"], outputs["c_logits"]

                valid_index = targets != -100
                targets = targets[valid_index]
                logits = logits[valid_index]

                _logits = torch.tensor([]).to(self.config.device).view(-1, 2)
                _c_logits = torch.tensor([]).to(self.config.device).view(-1, 2)
                _targets = torch.tensor([]).to(self.config.device).view(-1)
                _c_targets = torch.tensor([]).to(self.config.device).view(-1)
                ex_ids = sorted(set(sample["ex_id"].tolist()))
                for ex_id in ex_ids:
                    ex_index = sample["ex_id"] == ex_id
                    _logits = torch.cat(
                        (_logits, torch.mean(logits[ex_index], dim=0).unsqueeze(0)),
                        dim=0,
                    )
                    _c_logits = torch.cat(
                        (_c_logits, torch.mean(c_logits[ex_index], dim=0).unsqueeze(0)),
                        dim=0,
                    )
                    _targets = torch.cat(
                        (_targets, targets[ex_index].max().unsqueeze(0)), dim=0
                    )
                    _c_targets = torch.cat(
                        (_c_targets, c_targets[ex_index].max().unsqueeze(0)), dim=0
                    )

                logits = _logits
                c_logits = _c_logits
                targets = _targets
                c_targets = _c_targets

                t_probs = torch.softmax(logits, dim=-1)

                if targets_all is None:
                    targets_all = np.array(
                        [
                            self.config.label_to_index[x]
                            if x in self.config.label_to_index
                            else LabelPaddingOption.LABEL_PADDING
                            for x in targets
                        ]
                    )
                    t_outputs_all = np.array(logits.cpu()).astype(np.float32)
                else:
                    targets_all = np.concatenate(
                        (
                            targets_all,
                            [
                                self.config.label_to_index[x]
                                if x in self.config.label_to_index
                                else LabelPaddingOption.LABEL_PADDING
                                for x in targets
                            ],
                        ),
                        axis=0,
                    )
                    t_outputs_all = np.concatenate(
                        (t_outputs_all, np.array(logits.cpu()).astype(np.float32)),
                        axis=0,
                    )
                if c_targets_all is None:
                    c_targets_all = np.array(
                        [
                            self.config.label_to_index[x]
                            if x in self.config.label_to_index
                            else LabelPaddingOption.LABEL_PADDING
                            for x in c_targets
                        ]
                    )
                    t_c_outputs_all = np.array(c_logits.cpu()).astype(np.float32)

                for i, i_probs in enumerate(t_probs):
                    label = self.config.index_to_label[int(i_probs.argmax(axis=-1))]
                    corrupt_label = self.config.index_to_label[
                        int(c_logits[i].argmax(axis=-1))
                    ]
                    if targets[i] != LabelPaddingOption.LABEL_PADDING:
                        # model accepts an int label, so we can not pass the str label to the model.
                        # we need to convert the int label to str label.
                        real_label = self.config.index_to_label[int(targets[i])]
                    else:
                        real_label = "N.A."
                    if (
                            real_label != LabelPaddingOption.LABEL_PADDING
                            and real_label != str(LabelPaddingOption.LABEL_PADDING)
                    ):
                        n_labeled += 1

                    text_raw = sample["code"][i]
                    ex_id = sample["ex_id"][i]

                    if self.cal_perplexity:
                        ids = self.MLM_tokenizer(
                            text_raw,
                            truncation=True,
                            padding="max_length",
                            max_length=self.config.max_seq_len,
                            return_tensors="pt",
                        )
                        ids["labels"] = ids["input_ids"].clone()
                        ids = ids.to(self.config.device)
                        loss = self.MLM(**ids)["loss"]
                        perplexity = float(torch.exp(loss / ids["input_ids"].size(1)))
                    else:
                        perplexity = "N.A."
                    if not results or results[-1]["ex_id"] != ex_id:
                        results.append(
                            {
                                "ex_id": ex_id,
                                "code": text_raw,
                                "label": label,
                                "confidence": float(max(i_probs)),
                                "probs": i_probs.cpu().numpy(),
                                "corrupt_label": corrupt_label,
                                "corrupt_ref_label": c_targets[i],
                                "corrupt_confidence": float(max(c_logits[i])),
                                "ref_label": real_label,
                                "ref_check": correct[label == real_label]
                                if real_label != str(LabelPaddingOption.LABEL_PADDING)
                                else "",
                                "perplexity": perplexity,
                            }
                        )
                    n_total += 1

        try:
            if print_result:
                for ex_id, result in enumerate(results):
                    text_printing = result["code"][:]
                    if result["ref_label"] != LabelPaddingOption.LABEL_PADDING:
                        if result["label"] == result["ref_label"]:
                            text_info = colored(
                                "#{}\t -> <{}(ref:{} confidence:{})>\t".format(
                                    result["ex_id"],
                                    result["label"],
                                    result["ref_label"],
                                    result["confidence"],
                                ),
                                "green",
                            )
                        else:
                            text_info = colored(
                                "#{}\t -> <{}(ref:{}) confidence:{}>\t".format(
                                    result["ex_id"],
                                    result["label"],
                                    result["ref_label"],
                                    result["confidence"],
                                ),
                                "red",
                            )
                    else:
                        text_info = "#{}\t -> {}\t".format(
                            result["ex_id"], result["label"]
                        )
                    if self.cal_perplexity:
                        text_printing += colored(
                            " --> <perplexity:{}>\t".format(result["perplexity"]),
                            "yellow",
                        )
                    text_printing = text_info + text_printing

                    fprint("Example {}".format(text_printing))
            if save_path:
                with open(save_path, "w", encoding="utf8") as fout:
                    json.dump(str(results), fout, ensure_ascii=False)
                    fprint("inference result saved in: {}".format(save_path))
        except Exception as e:
            fprint("Can not save result: {}, Exception: {}".format(text_raw, e))

        if len(results) > 1:
            fprint("Total samples:{}".format(n_total))
            fprint("Labeled samples:{}".format(n_labeled))

            report = metrics.classification_report(
                targets_all,
                np.argmax(t_outputs_all, -1),
                digits=4,
                target_names=[
                    self.config.index_to_label[x]
                    for x in sorted(self.config.index_to_label.keys()) if x != -100
                ],
            )
            fprint(
                "\n---------------------------- Classification Report ----------------------------\n"
            )
            rprint(report)
            fprint(
                "\n---------------------------- Classification Report ----------------------------\n"
            )

            report = metrics.confusion_matrix(
                targets_all,
                np.argmax(t_outputs_all, -1),
                labels=[
                    self.config.label_to_index[x] for x in self.config.label_to_index if x != '-100' and x != ''
                ],
            )
            fprint(
                "\n---------------------------- Confusion Matrix ----------------------------\n"
            )
            rprint(report)
            fprint(
                "\n---------------------------- Confusion Matrix ----------------------------\n"
            )

            report = metrics.classification_report(
                targets_all,
                np.argmax(t_outputs_all, -1),
                digits=4,
                target_names=[
                    self.config.index_to_label[x] for x in self.config.index_to_label
                ],
            )
            fprint(
                "\n---------------------------- Corrupt Detection Report ----------------------------\n"
            )
            rprint(report)
            fprint(
                "\n---------------------------- Corrupt Detection Report ----------------------------\n"
            )

            report = metrics.confusion_matrix(
                c_targets_all,
                np.argmax(t_c_outputs_all, -1),
                labels=[
                    self.config.label_to_index[x] for x in self.config.label_to_index if x != '-100' and x != ''
                ],
            )
            fprint(
                "\n---------------------------- Corrupt Detection Confusion Matrix ----------------------------\n"
            )
            rprint(report)
            fprint(
                "\n---------------------------- Corrupt Detection Confusion Matrix ----------------------------\n"
            )
        return results

    def clear_input_samples(self):
        self.dataset.all_data = []


class Predictor(CodeDefectDetector):
    pass
