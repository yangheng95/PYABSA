# -*- coding: utf-8 -*-
# file: apc_trainer.py
# time: 2021/4/22 0022
# author: yangheng <hy345@exeter.ac.uk>
# github: https://github.com/yangheng95
# Copyright (C) 2021. All Rights Reserved.
import math
import os
import random
import shutil
import time

import numpy
import pandas
import torch
import torch.nn as nn
from findfile import find_file
from sklearn import metrics
from sklearn.metrics import precision_score, recall_score, confusion_matrix
from torch import cuda
from torch.utils.data import (
    DataLoader,
    random_split,
    ConcatDataset,
    RandomSampler,
    SequentialSampler,
)
from tqdm import tqdm
from transformers import BertModel

from pyabsa.utils.file_utils import save_model
from pyabsa.utils.pyabsa_utils import (
    print_args,
    resume_from_checkpoint,
    retry,
    init_optimizer,
)

from ..models.ensembler import APCEnsembler

import pytorch_warmup as warmup


class Instructor:
    def __init__(self, opt, logger):
        if opt.use_amp:
            try:
                self.scaler = torch.cuda.amp.GradScaler()
                print("Use AMP for training!")
            except Exception:
                self.scaler = None
        else:
            self.scaler = None

        self.logger = logger
        self.opt = opt

        self.logger = logger

        self.model = APCEnsembler(self.opt)
        self.opt = self.model.opt
        self.train_set = self.model.train_set
        self.test_set = self.model.test_set
        self.test_dataloader = self.model.test_dataloader
        self.val_dataloader = self.model.val_dataloader
        self.train_dataloader = self.model.train_dataloader
        self.tokenizer = self.model.tokenizer

        initializers = {
            "xavier_uniform_": torch.nn.init.xavier_uniform_,
            "xavier_normal_": torch.nn.init.xavier_normal_,
            "orthogonal_": torch.nn.init.orthogonal_,
        }
        self.initializer = initializers[self.opt.initializer]

        # use DataParallel for training if device count larger than 1
        if self.opt.auto_device == "allcuda":
            self.model.to(self.opt.device)
            self.model = torch.nn.parallel.DataParallel(self.model).module
        else:
            self.model.to(self.opt.device)

        # eta1 and eta2 works only on LSA models, read the LSA paper for more details
        if hasattr(self.model.models[0], "eta1") and hasattr(
            self.model.models[0], "eta2"
        ):
            if self.opt.eta == 0:
                torch.nn.init.uniform_(self.model.models[0].eta1)
                torch.nn.init.uniform_(self.model.models[0].eta2)
            eta1_id = id(self.model.models[0].eta1)
            eta2_id = id(self.model.models[0].eta2)
            base_params = filter(
                lambda p: id(p) != eta1_id and id(p) != eta2_id,
                self.model.models[0].parameters(),
            )
            self.opt.eta_lr = (
                self.opt.learning_rate * 1000
                if "eta_lr" not in self.opt.args
                else self.opt.args["eta_lr"]
            )
            self.optimizer = init_optimizer(self.opt.optimizer)(
                [
                    {"params": base_params},
                    {
                        "params": self.model.models[0].eta1,
                        "lr": self.opt.eta_lr,
                        "weight_decay": self.opt.l2reg,
                    },
                    {
                        "params": self.model.models[0].eta2,
                        "lr": self.opt.eta_lr,
                        "weight_decay": self.opt.l2reg,
                    },
                ],
                lr=self.opt.learning_rate,
                weight_decay=self.opt.l2reg,
            )
        else:
            self.optimizer = init_optimizer(self.opt.optimizer)(
                self.model.parameters(),
                lr=self.opt.learning_rate,
                weight_decay=self.opt.l2reg,
            )
        self.train_dataloaders = []
        self.val_dataloaders = []

        if os.path.exists("init_state_dict.bin"):
            os.remove("init_state_dict.bin")
        if self.opt.cross_validate_fold > 0:
            torch.save(self.model.state_dict(), "init_state_dict.bin")

        self.opt.device = torch.device(self.opt.device)
        if self.opt.device.type == "cuda":
            self.logger.info(
                "cuda memory allocated:{}".format(
                    torch.cuda.memory_allocated(device=self.opt.device)
                )
            )

        print_args(self.opt, self.logger)

    def _reset_params(self):
        for child in self.model.children():
            if type(child) != BertModel:  # skip bert params
                for p in child.parameters():
                    if p.requires_grad:
                        if len(p.shape) > 1:
                            self.initializer(p)
                        else:
                            stdv = 1.0 / math.sqrt(p.shape[0])
                            torch.nn.init.uniform_(p, a=-stdv, b=stdv)

    def reload_model(self, ckpt="./init_state_dict.bin"):
        if os.path.exists(ckpt):
            if self.opt.auto_device == "allcuda":
                self.model.module.load_state_dict(
                    torch.load(find_file(ckpt, or_key=[".bin", "state_dict"]))
                )
            else:
                self.model.load_state_dict(
                    torch.load(find_file(ckpt, or_key=[".bin", "state_dict"]))
                )

    def prepare_dataloader(self, train_set):
        if self.train_dataloader and self.val_dataloader:
            self.val_dataloaders = [self.val_dataloader]
            self.train_dataloaders = [self.train_dataloader]

        elif self.opt.cross_validate_fold < 1:
            train_sampler = RandomSampler(
                self.train_set if not self.train_set else self.train_set
            )
            self.train_dataloaders.append(
                DataLoader(
                    dataset=train_set,
                    batch_size=self.opt.batch_size,
                    sampler=train_sampler,
                    pin_memory=True,
                )
            )

        else:
            split_dataset = train_set
            len_per_fold = len(split_dataset) // self.opt.cross_validate_fold + 1
            folds = random_split(
                split_dataset,
                tuple(
                    [len_per_fold] * (self.opt.cross_validate_fold - 1)
                    + [
                        len(split_dataset)
                        - len_per_fold * (self.opt.cross_validate_fold - 1)
                    ]
                ),
            )

            for f_idx in range(self.opt.cross_validate_fold):
                train_set = ConcatDataset(
                    [x for i, x in enumerate(folds) if i != f_idx]
                )
                val_set = folds[f_idx]
                train_sampler = RandomSampler(train_set if not train_set else train_set)
                val_sampler = SequentialSampler(val_set if not val_set else val_set)
                self.train_dataloaders.append(
                    DataLoader(
                        dataset=train_set,
                        batch_size=self.opt.batch_size,
                        sampler=train_sampler,
                    )
                )
                self.val_dataloaders.append(
                    DataLoader(
                        dataset=val_set,
                        batch_size=self.opt.batch_size,
                        sampler=val_sampler,
                    )
                )

    def _train(self, criterion):
        self.prepare_dataloader(self.train_set)

        if self.opt.warmup_step >= 0:
            self.lr_scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
                self.optimizer,
                T_max=len(self.train_dataloaders[0]) * self.opt.num_epoch,
            )
            self.warmup_scheduler = warmup.UntunedLinearWarmup(self.optimizer)

        if len(self.val_dataloaders) > 1:
            return self._k_fold_train_and_evaluate(criterion)
        else:
            return self._train_and_evaluate(criterion)

    def _train_and_evaluate(self, criterion):
        global_step = 0
        max_fold_acc = 0
        max_fold_f1 = 0
        save_path = "{0}/{1}_{2}".format(
            self.opt.model_path_to_save, self.opt.model_name, self.opt.dataset_name
        )

        self.opt.metrics_of_this_checkpoint = {"acc": 0, "f1": 0}
        self.opt.max_test_metrics = {"max_apc_test_acc": 0, "max_apc_test_f1": 0}

        losses = []

        Total_params = 0
        Trainable_params = 0
        NonTrainable_params = 0

        for param in self.model.parameters():
            mulValue = numpy.prod(
                param.size()
            )  # 使用numpy prod接口计算参数数组所有元素之积
            Total_params += mulValue  # 总参数量
            if param.requires_grad:
                Trainable_params += mulValue  # 可训练参数量
            else:
                NonTrainable_params += mulValue  # 非可训练参数量

        patience = self.opt.patience + self.opt.evaluate_begin
        if self.opt.log_step < 0:
            self.opt.log_step = (
                len(self.train_dataloaders[0])
                if self.opt.log_step < 0
                else self.opt.log_step
            )

        self.logger.info(
            "***** Running training for Aspect Polarity Classification *****"
        )
        self.logger.info("Training set examples = %d", len(self.train_set))
        if self.test_set:
            self.logger.info("Test set examples = %d", len(self.test_set))
        self.logger.info(
            "Total params = %d, Trainable params = %d, Non-trainable params = %d",
            Total_params,
            Trainable_params,
            NonTrainable_params,
        )
        self.logger.info("Batch size = %d", self.opt.batch_size)
        self.logger.info(
            "Num steps = %d",
            len(self.train_dataloaders[0]) // self.opt.batch_size * self.opt.num_epoch,
        )
        postfix = ""
        for epoch in range(self.opt.num_epoch):
            # self.opt.ETA_MV.add_metric(r'$\eta_{l}^{*}$'+str(self.opt.seed), self.model.models[0].eta1.item())
            # self.opt.ETA_MV.add_metric(r'$\eta_{r}^{*}$'+str(self.opt.seed), self.model.models[0].eta2.item())
            # self.opt.ETA_MV.next_trial()
            patience -= 1
            iterator = tqdm(self.train_dataloaders[0], postfix="Epoch:{}".format(epoch))
            for i_batch, sample_batched in enumerate(iterator):
                global_step += 1
                # switch model to training mode, clear gradient accumulators
                self.model.train()
                self.optimizer.zero_grad()
                inputs = {
                    col: sample_batched[col].to(self.opt.device)
                    for col in self.opt.inputs_cols
                }

                if self.opt.use_amp:
                    with torch.cuda.amp.autocast():
                        outputs = self.model(inputs)
                        targets = sample_batched["polarity"].to(self.opt.device)

                        if (
                            isinstance(outputs, dict)
                            and "loss" in outputs
                            and outputs["loss"] != 0
                        ):
                            loss = outputs["loss"]
                        else:
                            loss = criterion(outputs["logits"], targets)

                        if self.opt.auto_device == "allcuda":
                            loss = loss.mean()
                else:
                    outputs = self.model(inputs)
                    targets = sample_batched["polarity"].to(self.opt.device)

                    if (
                        isinstance(outputs, dict)
                        and "loss" in outputs
                        and outputs["loss"] != 0
                    ):
                        loss = outputs["loss"]
                    else:
                        loss = criterion(outputs["logits"], targets)

                    if self.opt.auto_device == "allcuda":
                        loss = loss.mean()

                losses.append(loss.item())

                if self.opt.use_amp and self.scaler:
                    self.scaler.scale(loss).backward()
                    self.scaler.step(self.optimizer)
                    self.scaler.update()
                else:
                    loss.backward()
                    self.optimizer.step()

                if self.opt.warmup_step >= 0:
                    with self.warmup_scheduler.dampening():
                        self.lr_scheduler.step()

                # evaluate if test set is available
                if global_step % self.opt.log_step == 0:
                    if (
                        self.opt.dataset_file["test"]
                        and epoch >= self.opt.evaluate_begin
                    ):
                        if self.val_dataloaders:
                            test_acc, f1 = self._evaluate_acc_f1(
                                self.val_dataloaders[0]
                            )
                        else:
                            test_acc, f1 = self._evaluate_acc_f1(self.test_dataloader)
                        self.opt.metrics_of_this_checkpoint["acc"] = test_acc
                        self.opt.metrics_of_this_checkpoint["f1"] = f1

                        if test_acc > max_fold_acc or f1 > max_fold_f1:
                            if test_acc > max_fold_acc:
                                patience = self.opt.patience
                                max_fold_acc = test_acc

                            if f1 > max_fold_f1:
                                max_fold_f1 = f1
                                patience = self.opt.patience

                            if self.opt.model_path_to_save:
                                if not os.path.exists(self.opt.model_path_to_save):
                                    os.makedirs(self.opt.model_path_to_save)
                                if save_path:
                                    try:
                                        shutil.rmtree(save_path)
                                        # logger.info('Remove sub-optimal trained model:', save_path)
                                    except:
                                        # logger.info('Can not remove sub-optimal trained model:', save_path)
                                        pass
                                save_path = "{0}/{1}_{2}_acc_{3}_f1_{4}/".format(
                                    self.opt.model_path_to_save,
                                    self.opt.model_name,
                                    self.opt.dataset_name,
                                    round(test_acc * 100, 2),
                                    round(f1 * 100, 2),
                                )

                                if (
                                    test_acc
                                    > self.opt.max_test_metrics["max_apc_test_acc"]
                                ):
                                    self.opt.max_test_metrics["max_apc_test_acc"] = (
                                        test_acc
                                    )
                                if f1 > self.opt.max_test_metrics["max_apc_test_f1"]:
                                    self.opt.max_test_metrics["max_apc_test_f1"] = f1

                                save_model(
                                    self.opt, self.model, self.tokenizer, save_path
                                )

                        postfix = (
                            "Epoch:{} | Loss:{:.4f} | Acc:{:.2f}(max:{:.2f}) |"
                            " F1:{:.2f}(max:{:.2f})".format(
                                epoch,
                                loss.item(),
                                test_acc * 100,
                                max_fold_acc * 100,
                                f1 * 100,
                                max_fold_f1 * 100,
                            )
                        )

                    else:
                        if self.opt.save_mode and epoch >= self.opt.evaluate_begin:
                            save_model(
                                self.opt,
                                self.model,
                                self.tokenizer,
                                save_path + "_{}/".format(loss.item()),
                            )
                        postfix = (
                            "Epoch:{} | Loss: {} | No evaluation until epoch:{}".format(
                                epoch, round(loss.item(), 8), self.opt.evaluate_begin
                            )
                        )

                iterator.postfix = postfix
                iterator.refresh()
            if patience < 0:
                break

        if not self.val_dataloaders:
            self.opt.MV.add_metric("Max-Test-Acc w/o Valid Set", max_fold_acc * 100)
            self.opt.MV.add_metric("Max-Test-F1 w/o Valid Set", max_fold_f1 * 100)

        if self.val_dataloaders:
            test_acc, test_f1, test_precision, test_recall, cm = self._evaluate_metrics(
                self.val_dataloaders[0]
            )

            # Log metrics to MetricVisualizer
            self.opt.MV.log_metric("Accuracy", test_acc, epoch)
            self.opt.MV.log_metric("F1", test_f1, epoch)
            self.opt.MV.log_metric("Precision", test_precision, epoch)
            self.opt.MV.log_metric("Recall", test_recall, epoch)

            # Log confusion matrix
            self.opt.MV.log_confusion_matrix(cm, self.opt.index_to_label, epoch)
            print(
                "Loading best model: {} and evaluating on test set ...".format(
                    save_path
                )
            )
            self.reload_model(find_file(save_path, ".state_dict"))
            max_fold_acc, max_fold_f1 = self._evaluate_acc_f1(self.test_dataloader)

            self.opt.MV.add_metric("Max-Test-Acc", max_fold_acc * 100)
            self.opt.MV.add_metric("Max-Test-F1", max_fold_f1 * 100)
            # shutil.rmtree(save_path)

        self.logger.info(self.opt.MV.summary(no_print=True))
        self.opt.MV.summary(save_path="metrics_output", show_plots=True)

        print(
            "Training finished, we hope you can share your checkpoint with community, please see:",
            "https://github.com/yangheng95/PyABSA/blob/release/demos/documents/share-checkpoint.md",
        )

        rolling_intv = 5
        df = pandas.DataFrame(losses)
        losses = list(
            numpy.hstack(df.rolling(rolling_intv, min_periods=1).mean().values)
        )
        self.opt.loss = losses[-1]
        # self.opt.loss = np.average(losses)

        print_args(self.opt)

        if self.val_dataloader or self.opt.save_mode:
            del self.train_dataloaders
            del self.test_dataloader
            del self.val_dataloaders
            del self.model
            cuda.empty_cache()
            time.sleep(3)
            return save_path
        else:
            # direct return model if do not evaluate
            # if self.opt.model_path_to_save:
            #     save_path = '{0}/{1}/'.format(self.opt.model_path_to_save,
            #                                   self.opt.model_name
            #                                   )
            #     save_model(self.opt, self.model, self.tokenizer, save_path)
            del self.train_dataloaders
            del self.test_dataloader
            del self.val_dataloaders
            cuda.empty_cache()
            time.sleep(3)
            return self.model, self.opt, self.tokenizer

    def _evaluate_metrics(self, test_dataloader):
        # switch model to evaluation mode
        self.model.eval()
        n_test_correct, n_test_total = 0, 0
        t_targets_all, t_outputs_all = None, None
        with torch.no_grad():
            for t_batch, t_sample_batched in enumerate(test_dataloader):
                t_inputs = {
                    col: t_sample_batched[col].to(self.opt.device)
                    for col in self.opt.inputs_cols
                }
                t_targets = t_sample_batched["polarity"].to(self.opt.device)
                t_outputs = self.model(t_inputs)

                if isinstance(t_outputs, dict):
                    sen_outputs = t_outputs["logits"]
                else:
                    sen_outputs = t_outputs

                n_test_correct += (
                    (torch.argmax(sen_outputs, -1) == t_targets).sum().item()
                )
                n_test_total += len(sen_outputs)

                if t_targets_all is None:
                    t_targets_all = t_targets
                    t_outputs_all = sen_outputs
                else:
                    t_targets_all = torch.cat((t_targets_all, t_targets), dim=0)
                    t_outputs_all = torch.cat((t_outputs_all, sen_outputs), dim=0)

        test_acc = n_test_correct / n_test_total

        # Convert tensors to numpy arrays
        t_targets_all = t_targets_all.cpu().numpy()
        t_outputs_all = torch.argmax(t_outputs_all, -1).cpu().numpy()

        f1 = metrics.f1_score(
            t_targets_all,
            t_outputs_all,
            labels=list(range(self.opt.polarities_dim)),
            average="macro",
        )
        precision = precision_score(
            t_targets_all,
            t_outputs_all,
            labels=list(range(self.opt.polarities_dim)),
            average="macro",
        )
        recall = recall_score(
            t_targets_all,
            t_outputs_all,
            labels=list(range(self.opt.polarities_dim)),
            average="macro",
        )
        cm = confusion_matrix(
            t_targets_all,
            t_outputs_all,
            labels=list(range(self.opt.polarities_dim)),
        )

        return test_acc, f1, precision, recall, cm

    def _k_fold_train_and_evaluate(self, criterion):
        fold_test_acc = []
        fold_test_f1 = []

        save_path_k_fold = ""
        max_fold_acc_k_fold = 0

        losses = []

        self.opt.metrics_of_this_checkpoint = {"acc": 0, "f1": 0}
        self.opt.max_test_metrics = {"max_apc_test_acc": 0, "max_apc_test_f1": 0}

        for f, (train_dataloader, val_dataloader) in enumerate(
            zip(self.train_dataloaders, self.val_dataloaders)
        ):
            patience = self.opt.patience + self.opt.evaluate_begin
            if self.opt.log_step < 0:
                self.opt.log_step = (
                    len(self.train_dataloaders[0])
                    if self.opt.log_step < 0
                    else self.opt.log_step
                )

            self.logger.info(
                "***** Running training for Aspect Polarity Classification *****"
            )
            self.logger.info("Training set examples = %d", len(self.train_set))
            if self.test_set:
                self.logger.info("Test set examples = %d", len(self.test_set))
            self.logger.info("Batch size = %d", self.opt.batch_size)
            self.logger.info(
                "Num steps = %d",
                len(train_dataloader) // self.opt.batch_size * self.opt.num_epoch,
            )
            if len(self.train_dataloaders) > 1:
                self.logger.info(
                    "No. {} training in {} folds...".format(
                        f + 1, self.opt.cross_validate_fold
                    )
                )
            global_step = 0
            max_fold_acc = 0
            max_fold_f1 = 0
            save_path = "{0}/{1}_{2}".format(
                self.opt.model_path_to_save, self.opt.model_name, self.opt.dataset_name
            )
            for epoch in range(self.opt.num_epoch):
                patience -= 1
                iterator = tqdm(train_dataloader, postfix="Epoch:{}".format(epoch))
                postfix = ""
                for i_batch, sample_batched in enumerate(iterator):
                    global_step += 1
                    # switch model to train mode, clear gradient accumulators
                    self.model.train()
                    self.optimizer.zero_grad()
                    inputs = {
                        col: sample_batched[col].to(self.opt.device)
                        for col in self.opt.inputs_cols
                    }
                    if self.opt.use_amp:
                        with torch.cuda.amp.autocast():
                            outputs = self.model(inputs)
                            targets = sample_batched["polarity"].to(self.opt.device)

                            if (
                                isinstance(outputs, dict)
                                and "loss" in outputs
                                and outputs["loss"] != 0
                            ):
                                loss = outputs["loss"]
                            else:
                                loss = criterion(outputs["logits"], targets)

                            if self.opt.auto_device == "allcuda":
                                loss = loss.mean()
                    else:
                        outputs = self.model(inputs)
                        targets = sample_batched["polarity"].to(self.opt.device)

                        if (
                            isinstance(outputs, dict)
                            and "loss" in outputs
                            and outputs["loss"] != 0
                        ):
                            loss = outputs["loss"]
                        else:
                            loss = criterion(outputs["logits"], targets)

                        if self.opt.auto_device == "allcuda":
                            loss = loss.mean()

                    losses.append(loss.item())

                    if self.opt.use_amp and self.scaler:
                        self.scaler.scale(loss).backward()
                        self.scaler.step(self.optimizer)
                        self.scaler.update()
                    else:
                        loss.backward()
                        self.optimizer.step()

                    if self.opt.warmup_step >= 0:
                        with self.warmup_scheduler.dampening():
                            self.lr_scheduler.step()

                    # evaluate if test set is available
                    if global_step % self.opt.log_step == 0:
                        if (
                            self.opt.dataset_file["test"]
                            and epoch >= self.opt.evaluate_begin
                        ):
                            test_acc, f1 = self._evaluate_acc_f1(val_dataloader)

                            self.opt.metrics_of_this_checkpoint["acc"] = test_acc
                            self.opt.metrics_of_this_checkpoint["f1"] = f1

                            if test_acc > max_fold_acc or f1 > max_fold_f1:
                                if test_acc > max_fold_acc:
                                    patience = self.opt.patience
                                    max_fold_acc = test_acc

                                if f1 > max_fold_f1:
                                    max_fold_f1 = f1
                                    patience = self.opt.patience

                                if self.opt.model_path_to_save:
                                    if not os.path.exists(self.opt.model_path_to_save):
                                        os.makedirs(self.opt.model_path_to_save)
                                    if save_path:
                                        try:
                                            shutil.rmtree(save_path)
                                            # logger.info('Remove sub-optimal trained model:', save_path)
                                        except:
                                            # logger.info('Can not remove sub-optimal trained model:', save_path)
                                            pass
                                    save_path = "{0}/{1}_{2}_acc_{3}_f1_{4}/".format(
                                        self.opt.model_path_to_save,
                                        self.opt.model_name,
                                        self.opt.dataset_name,
                                        round(test_acc * 100, 2),
                                        round(f1 * 100, 2),
                                    )

                                    if (
                                        test_acc
                                        > self.opt.max_test_metrics["max_apc_test_acc"]
                                    ):
                                        self.opt.max_test_metrics[
                                            "max_apc_test_acc"
                                        ] = test_acc
                                    if (
                                        f1
                                        > self.opt.max_test_metrics["max_apc_test_f1"]
                                    ):
                                        self.opt.max_test_metrics["max_apc_test_f1"] = (
                                            f1
                                        )

                                    save_model(
                                        self.opt, self.model, self.tokenizer, save_path
                                    )

                            postfix = (
                                "Epoch:{} | Loss:{:.4f} | Acc:{:.2f}(max:{:.2f}) |"
                                " F1:{:.2f}(max:{:.2f})".format(
                                    epoch,
                                    loss.item(),
                                    test_acc * 100,
                                    max_fold_acc * 100,
                                    f1 * 100,
                                    max_fold_f1 * 100,
                                )
                            )
                        else:
                            postfix = "Epoch:{} | Loss: {} | No evaluation until epoch:{}".format(
                                epoch, round(loss.item(), 8), self.opt.evaluate_begin
                            )

                    iterator.postfix = postfix
                    iterator.refresh()
                if patience < 0:
                    break
            max_fold_acc, max_fold_f1 = self._evaluate_acc_f1(self.test_dataloader)
            if max_fold_acc > max_fold_acc_k_fold:
                save_path_k_fold = save_path
            fold_test_acc.append(max_fold_acc)
            fold_test_f1.append(max_fold_f1)

            self.opt.MV.add_metric("Fold{}-Max-Test-Acc".format(f), max_fold_acc * 100)
            self.opt.MV.add_metric("Fold{}-Max-Test-F1".format(f), max_fold_f1 * 100)

            self.logger.info(self.opt.MV.summary(no_print=True))

            self.reload_model()

        max_test_acc = numpy.max(fold_test_acc)
        max_test_f1 = numpy.max(fold_test_f1)

        self.opt.MV.add_metric("Max-Test-Acc", max_test_acc * 100)
        self.opt.MV.add_metric("Max-Test-F1", max_test_f1 * 100)

        self.logger.info(self.opt.MV.summary(no_print=True))
        self.reload_model(save_path_k_fold)
        print(
            "Training finished, we hope you can share your checkpoint with everybody, please see:",
            "https://github.com/yangheng95/PyABSA#how-to-share-checkpoints-eg-checkpoints-trained-on-your-custom-dataset-with-community",
        )

        rolling_intv = 5
        df = pandas.DataFrame(losses)
        losses = list(
            numpy.hstack(df.rolling(rolling_intv, min_periods=1).mean().values)
        )
        self.opt.loss = losses[-1]
        # self.opt.loss = np.average(losses)

        print_args(self.opt)

        if os.path.exists("./init_state_dict.bin"):
            os.remove("./init_state_dict.bin")
        if self.val_dataloaders or self.opt.save_mode:
            del self.train_dataloaders
            del self.test_dataloader
            del self.val_dataloaders
            del self.model
            cuda.empty_cache()
            time.sleep(3)
            return save_path
        else:
            # direct return model if do not evaluate
            # if self.opt.model_path_to_save:
            #     save_path = '{0}/{1}/'.format(self.opt.model_path_to_save,
            #                                   self.opt.model_name
            #                                   )
            #     save_model(self.opt, self.model, self.tokenizer, save_path)
            del self.train_dataloaders
            del self.test_dataloader
            del self.val_dataloaders
            cuda.empty_cache()
            time.sleep(3)
            return self.model, self.opt, self.tokenizer

    def _evaluate_acc_f1(self, test_dataloader):
        # switch model to evaluation mode
        self.model.eval()
        n_test_correct, n_test_total = 0, 0
        t_targets_all, t_outputs_all = None, None
        with torch.no_grad():
            for t_batch, t_sample_batched in enumerate(test_dataloader):
                t_inputs = {
                    col: t_sample_batched[col].to(self.opt.device)
                    for col in self.opt.inputs_cols
                }

                t_targets = t_sample_batched["polarity"].to(self.opt.device)

                t_outputs = self.model(t_inputs)

                if isinstance(t_outputs, dict):
                    sen_outputs = t_outputs["logits"]
                else:
                    sen_outputs = t_outputs

                n_test_correct += (
                    (torch.argmax(sen_outputs, -1) == t_targets).sum().item()
                )
                n_test_total += len(sen_outputs)

                if t_targets_all is None:
                    t_targets_all = t_targets
                    t_outputs_all = sen_outputs
                else:
                    t_targets_all = torch.cat((t_targets_all, t_targets), dim=0)
                    t_outputs_all = torch.cat((t_outputs_all, sen_outputs), dim=0)

        test_acc = n_test_correct / n_test_total
        f1 = metrics.f1_score(
            t_targets_all.cpu(),
            torch.argmax(t_outputs_all, -1).cpu(),
            labels=list(range(self.opt.polarities_dim)),
            average="macro",
        )

        if self.opt.args.get("show_metric", False):
            print(
                "\n---------------------------- APC Classification Report ----------------------------\n"
            )
            print(
                metrics.classification_report(
                    t_targets_all.cpu(),
                    torch.argmax(t_outputs_all, -1).cpu(),
                    target_names=[
                        self.opt.index_to_label[x] for x in self.opt.index_to_label
                    ],
                )
            )
            print(
                "\n---------------------------- APC Classification Report ----------------------------\n"
            )
        return test_acc, f1

    def run(self):
        # Loss and Optimizer
        criterion = nn.CrossEntropyLoss()
        return self._train(criterion)


@retry
def train4apc(opt, from_checkpoint_path, logger):
    random.seed(opt.seed)
    numpy.random.seed(opt.seed)
    torch.manual_seed(opt.seed)
    torch.cuda.manual_seed(opt.seed)

    opt.device = torch.device(opt.device)

    # in case of handling ConnectionError exception
    trainer = Instructor(opt, logger)
    resume_from_checkpoint(trainer, from_checkpoint_path)

    return trainer.run()
