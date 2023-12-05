# -*- coding: utf-8 -*-
# file: __init__.py
# time: 2021/4/22 0022
# author: YANG, HENG <hy345@exeter.ac.uk> (杨恒)
# github: https://github.com/yangheng95

# Copyright (C) 2021. All Rights Reserved.

__name__ = "pyabsa"
__version__ = "2.3.4"


from pyabsa.utils.notification_utils.notification_utils import (
    check_emergency_notification,
)

check_emergency_notification()

from pyabsa.framework.flag_class import *

from pyabsa.utils.data_utils.dataset_item import DatasetItem
from pyabsa.utils.absa_utils.make_absa_dataset import make_ABSA_dataset
from pyabsa.utils.absa_utils.absa_utils import (
    generate_inference_set_for_apc,
    convert_apc_set_to_atepc_set,
)
from pyabsa.utils.data_utils.dataset_manager import (
    download_all_available_datasets,
    download_dataset_by_name,
)
from pyabsa.utils.file_utils.file_utils import load_dataset_from_file


from pyabsa.framework.checkpoint_class.checkpoint_utils import (
    available_checkpoints,
    download_checkpoint,
)
from pyabsa.framework.dataset_class.dataset_dict_class import DatasetDict
from pyabsa.tasks import (
    AspectPolarityClassification,
    AspectTermExtraction,
    AspectSentimentTripletExtraction,
    TextClassification,
    TextAdversarialDefense,
    RNAClassification,
    RNARegression,
    ABSAInstruction,
)

# for compatibility of v1.x
from pyabsa.framework.checkpoint_class.checkpoint_template import (
    APCCheckpointManager,
    ATEPCCheckpointManager,
    ASTECheckpointManager,
    TCCheckpointManager,
    TADCheckpointManager,
    RNACCheckpointManager,
    RNARCheckpointManager,
)
from pyabsa.tasks.AspectPolarityClassification import APCDatasetList

from pyabsa.utils.file_utils.file_utils import meta_load, meta_save

from pyabsa.utils.cache_utils.cache_utils import clean

ABSADatasetList = APCDatasetList
# for compatibility of v1.x

from pyabsa.utils.check_utils.package_version_check import (
    validate_pyabsa_version,
    query_release_notes,
    check_pyabsa_update,
    check_package_version,
)

validate_pyabsa_version()
