import itertools
from typing import Iterable, Tuple, Dict

import dask
import dask.array
import numpy as np

from .core import Dataset, DatasetGenerator, load, _dask_shape
from hub.collections.tensor import Tensor
from hub.collections import dataset
from hub.collections import tensor as hub_tensor


def _generate(generator: DatasetGenerator, input):
    output = generator(input)
    keys = sorted(output.keys())
    return [output[key] for key in keys]


def _meta_preprocess(meta: dict):
    meta = dict(meta)
    assert (
        len({v["shape"][0] for v in meta.values()}) == 1
    ), "first dim should be equal for all tensors"
    for key, value in meta.items():
        assert "dtype" in value
        assert "shape" in value
    return meta


# def _generate_input_preprocess(input):
#     if isinstance(input, Tensor):
#         return input._array
#     else:
#         return input


def generate(generator: DatasetGenerator, input) -> Dataset:
    """ Generates dataset based on DatabaseGenerator class instance and iterable input
    For every element in input runs generators __call__ function.
    That function should return dict of numpy arrays containing single or multiple outputs for axis 0 of generating dataset
    """
    meta = _meta_preprocess(generator.meta())
    keys = sorted(meta.keys())
    tasks = [dask.delayed(_generate, nout=len(meta))(generator, i) for i in input]
    if len(tasks) == 0:
        return Dataset(
            {
                key: Tensor(
                    meta[key],
                    dask.array.from_array(np.empty(shape=(0,), dtype="uint8")),
                )
                for ki, key in enumerate(keys)
            }
        )

    return Dataset(
        {
            key: Tensor(
                meta[key],
                dask.array.concatenate(
                    [
                        dask.array.from_delayed(
                            task[ki],
                            shape=_dask_shape(meta[key]["shape"]),
                            dtype=meta[key]["dtype"],
                        )
                        for task in tasks
                    ]
                ),
                delayed_objs=[task[ki] for task in tasks],
            )
            for ki, key in enumerate(keys)
        }
    )


def from_tensors(
    tensors: dict,
    license: str = None,
    description: str = None,
    citation: str = None,
    howtoload: str = None,
) -> Dataset:
    """ Creates a dataset from dict of tensors
    """
    return Dataset(
        tensors,
        metainfo={
            "license": license,
            "description": description,
            "citation": citation,
            "howtoload": howtoload,
        },
    )


def _meta_concat(metas: Tuple[Dict[str, object]]):
    _meta = metas[0]
    for meta in metas:
        assert _meta["dtype"] == meta["dtype"]
        assert _meta["shape"][1:] == meta["shape"][1:]
        assert _meta.get("dtag") == meta.get("dtag")
        assert _meta["dcompress"] == meta["dcompress"]

    _meta["shape"] = (sum([meta["shape"][0] for meta in metas]),) + _meta["shape"][1:]
    if _meta["shape"][0] < 0:
        _meta["shape"][0] = -1

    return _meta


def concat(datasets: Iterable[Dataset]) -> Dataset:
    """ Concats multiple datasets into one along axis 0
    This is equivalent to concat every tensor with the same key
    """
    keys = [sorted(dataset._tensors.keys()) for dataset in datasets]
    for key in keys:
        assert key == keys[0]
    keys = keys[0]
    return Dataset(
        {
            key: Tensor(
                _meta_concat([dataset._tensors[key]._meta for dataset in datasets]),
                dask.array.concatenate(
                    [dataset._tensors[key]._array for dataset in datasets]
                ),
                tuple(
                    itertools.chain(
                        *[
                            dataset._tensors[key]._delayed_objs or []
                            for dataset in datasets
                        ]
                    )
                ),
            )
            for key in keys
        }
    )


def merge(datasets: Iterable[Dataset]) -> Dataset:
    """ Merges multiple datasets that have distinct keys into one big datasets containing all keys
    """
    tensors = {}
    for dataset in datasets:
        for tname, tvalue in dataset._tensors.items():
            assert tname not in tensors
            tensors[tname] = tvalue
    return Dataset(tensors)

# ItemClass to Dtags mapping
dtags = {
    'Audio': 'audio',
    'BBoxFeature': 'box',
    'Image': 'image',
    'Dtype': 'tensor',
    'Tensor': 'tensor',
    'ClassLabel': 'text',
    'Text': 'text',
    'Video': 'video',
#    'Sequence': 'object',
#    'FeaturesDict': 'object',
}

# Dtag to Archiver mapping
codecs = {
    'audio': 'lz4:4',
    'box': 'lz4:4',
    'image': 'lz4:4',
    'tensor': 'lz4:4',
    'text': 'lz4:4',
    'video': 'lz4:4',
}


def from_tensorflow(ds_tf, info, n_examples=-1):
    #0. Auxilary variables
    tensors = {feature: [] for feature in info.features.keys()}
    #1. Subsampling the input dataset for testing issues
    if n_examples > 0:
        ds_tf = ds_tf.take(n_examples)
    #2. Mapping features to collected tensors from the input dataset
    for ex in ds_tf:
        for feature, tensor in ex.items():
            if feature in dtags:
                tensors[feature] += [tensor]
    #3. Mapping features to concatenated tensors
    for feature in tensors:
        data = np.array(tensors[feature])
        name = type(info.features[feature]).__name__
        dtag = dtags.get(name, 'tensor')
        codec = codecs[dtag]
        tensors[feature] = hub_tensor.from_array(data, dtag=dtag, dcompress=codec)
    ds_hb = dataset.from_tensors(
        tensors,
        citation=info.citation,
        description=info.description,
#        license=info.redistribution_info
    )
    return ds_hb
