# PyABSA - Open Framework for Aspect-based Sentiment Analysis

![PyPI - Python Version](https://img.shields.io/badge/python-3.6-blue.svg)
[![PyPI](https://img.shields.io/pypi/v/pyabsa)](https://pypi.org/project/pyabsa/)
[![PyPI_downloads](https://img.shields.io/pypi/dm/pyabsa)](https://pypi.org/project/pyabsa/)
![License](https://img.shields.io/pypi/l/pyabsa?logo=PyABSA)

[![total views](https://raw.githubusercontent.com/yangheng95/PyABSA/traffic/total_views.svg)](https://github.com/yangheng95/PyABSA/tree/traffic#-total-traffic-data-badge)
[![total views per week](https://raw.githubusercontent.com/yangheng95/PyABSA/traffic/total_views_per_week.svg)](https://github.com/yangheng95/PyABSA/tree/traffic#-total-traffic-data-badge)
[![total clones](https://raw.githubusercontent.com/yangheng95/PyABSA/traffic/total_clones.svg)](https://github.com/yangheng95/PyABSA/tree/traffic#-total-traffic-data-badge)
[![total clones per week](https://raw.githubusercontent.com/yangheng95/PyABSA/traffic/total_clones_per_week.svg)](https://github.com/yangheng95/PyABSA/tree/traffic#-total-traffic-data-badge)

[![PWC](https://img.shields.io/endpoint.svg?url=https://paperswithcode.com/badge/back-to-reality-leveraging-pattern-driven/aspect-based-sentiment-analysis-on-semeval)](https://paperswithcode.com/sota/aspect-based-sentiment-analysis-on-semeval?p=back-to-reality-leveraging-pattern-driven)

**Hi, there!** Please star this repo if it helps you! Each Star helps PyABSA go further, many thanks.

# | [Overview](../README.MD) | [HuggingfaceHub](huggingface_readme.md) | [ABDADatasets](dataset_readme.md) | [ABSA Models](model_readme.md) | [Colab Tutorials](tutorial_readme.md) |

## Demos of APC and ATEPC

## Here are tutorials: [APC](https://github.com/yangheng95/PyABSA/blob/v2/examples-v2/aspect_polarity_classification/Aspect_Sentiment_Classification.ipynb) and [ATEPC](https://github.com/yangheng95/PyABSA/blob/v2/examples-v2/aspect_term_extraction/Aspect_Term_Extractor.ipynb)

We also provide enough demos to help you use PyABSA, these demos can be found
in [aspect-based sentiment classification](../examples-v2/aspect_polarity_classification),
[aspect term extraction](../examples-v2/aspect_term_extraction)
and [text classification](../examples-v2/text_classification).

## How to start

- Create a new python environment (Recommended) and install latest PyABSA
- Find a suitable demo script ([ATEPC](https://github.com/yangheng95/PyABSA/tree/release/demos/aspect_term_extraction)
  , [APC](https://github.com/yangheng95/PyABSA/tree/release/demos/aspect_polarity_classification)
  , [Text Classification](https://github.com/yangheng95/PyABSA/tree/release/demos/text_classification)) to prepare your
  training script. (Welcome to share your demo script)
- Format or Annotate your dataset referring to [ABSADatasets](https://github.com/yangheng95/ABSADatasets) or use public
  dataset in ABSADatasets
- Init your config to specify Model, Dataset, hyper-parameters
- Training your model and get checkpoints
- Share your checkpoint and dataset
