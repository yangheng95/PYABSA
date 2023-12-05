# -*- coding: utf-8 -*-
# file: cdd_trainer.py
# time: 02/11/2022 21:34
# author: YANG, HENG <hy345@exeter.ac.uk> (杨恒)
# github: https://github.com/yangheng95
# GScholar: https://scholar.google.com/citations?user=NPq5a_0AAAAJ&hl=en
# ResearchGate: https://www.researchgate.net/profile/Heng-Yang-17/research
# Copyright (C) 2022. All Rights Reserved.

from typing import Union

from pyabsa.framework.flag_class.flag_template import (
    DeviceTypeOption,
    ModelSaveOption,
    TaskCodeOption,
    TaskNameOption,
)
from ..configuration.cdd_configuration import CDDConfigManager
from ..instructor.cdd_instructor import CDDTrainingInstructor
from ..prediction.code_defect_detector import CodeDefectDetector
from pyabsa.framework.trainer_class.trainer_template import Trainer


class CDDTrainer(Trainer):
    def __init__(
            self,
            config: CDDConfigManager = None,
            dataset=None,
            from_checkpoint: str = None,
            checkpoint_save_mode: int = ModelSaveOption.SAVE_MODEL_STATE_DICT,
            auto_device: Union[bool, str] = DeviceTypeOption.AUTO,
            path_to_save=None,
            load_aug=False,
    ):
        """
        Init a trainer for trainer a APC, ATEPC, TC or TAD model, after trainer,
        you need to call load_trained_model() to get the trained model for inference.

        :param config: PyABSA.config.ConfigManager
        :param dataset: Dataset name, or a dataset_manager path, or a list of dataset_manager paths
        :param from_checkpoint: A checkpoint path to train based on
        :param checkpoint_save_mode: Save trained model to checkpoint,
                                     "checkpoint_save_mode=1" to save the state_dict,
                                     "checkpoint_save_mode=2" to save the whole model,
                                     "checkpoint_save_mode=3" to save the fine-tuned BERT,
                                     otherwise avoid saving checkpoint but return the trained model after trainer
        :param auto_device: True or False, otherwise 'allcuda', 'cuda:1', 'cpu' works
        :param path_to_save=None: Specify path to save checkpoints
        :param load_aug=False: Load the available augmentation dataset if any

        """
        super(CDDTrainer, self).__init__(
            config=config,
            dataset=dataset,
            from_checkpoint=from_checkpoint,
            checkpoint_save_mode=checkpoint_save_mode,
            auto_device=auto_device,
            path_to_save=path_to_save,
            load_aug=load_aug,
        )

        self.training_instructor = CDDTrainingInstructor
        self.inference_model_class = CodeDefectDetector
        self.config.task_code = TaskCodeOption.CodeDefectDetection
        self.config.task_name = TaskNameOption().get(TaskCodeOption.CodeDefectDetection)

        self._run()
