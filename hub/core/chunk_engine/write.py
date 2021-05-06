import os
import numpy as np
import pickle

from typing import Any, Callable, List, Tuple

from hub.core.chunk_engine import generate_chunks
from .util import array_to_bytes, index_map_entry_to_bytes
from .write_impl import MemoryProvider


def chunk_and_write_array(
    array: np.ndarray,
    key: str,
    compressor: Callable,
    chunk_size: int,
    storage: MemoryProvider,
    cache_chain: List[MemoryProvider] = [],
    batched: bool = False,
):
    """
    Chunk, cache, & write array to `storage`.
    """

    if batched:
        # TODO: implement batched
        raise NotImplemented

    # TODO: this can be replaced with hilbert curve or something
    b = array_to_bytes(array)
    start_chunk, end_chunk = chunk_and_write_bytes(
        b,
        key=key,
        compressor=compressor,
        chunk_size=chunk_size,
        storage=storage,
        cache_chain=cache_chain,
    )

    index_map = []

    # TODO: encode index_map_entry as array instead of dictionary
    index_map.append(
        {
            "start_chunk": start_chunk,
            "end_chunk": end_chunk,
            "dtype": array.dtype,
            "shape": array.shape,
        }
    )

    # TODO: chunk index_map (& add to the previous chunk until full)
    # TODO: make note of this in docstring: no need to cache. for most efficiency, we should try to use `batched` as often as possible.
    index_map_key = os.path.join(key, "index_map")
    write_to_storage(index_map_key, pickle.dumps(index_map), storage)


def chunk_and_write_bytes(
    b: bytes,
    key: str,
    compressor: Callable,
    chunk_size: int,
    storage: MemoryProvider,
    cache_chain: List[MemoryProvider] = [],
    use_index_map: bool = True,
) -> Tuple[int, int]:
    """
    Chunk, cache, & write bytes to `storage`.
    """

    lcnb = None
    chunk_gen = generate_chunks(b, chunk_size, last_chunk_num_bytes=lcnb)

    for local_chunk_index, chunk in enumerate(chunk_gen):
        # TODO: get global_chunk_index (don't just use local_chunk_index)
        chunk_key = os.path.join(key, ("c%i" % local_chunk_index))
        compressed_chunk = compressor(chunk)
        # TODO: fill previous chunk if it is incomplete
        write_bytes_with_caching(chunk_key, compressed_chunk, cache_chain, storage)

    flush_cache(cache_chain, storage)

    # TODO global start/end chunk instead of local
    start_chunk = 0
    end_chunk = local_chunk_index
    return start_chunk, end_chunk


def write_bytes_with_caching(key, b, cache_chain, storage):
    if len(cache_chain) <= 0:
        # if `cache_chain` is empty, store to main provider.
        write_to_storage(key, b, storage)

    else:
        # if `cache_chain` is not empty, prioritize cache storage over main provider.
        cache_success = write_to_cache(key, b, cache_chain)

        if not cache_success:
            flush_cache(cache_chain, storage)
            cache_success = write_to_cache(key, b, cache_chain)

            if not cache_success:
                # TODO move into exceptions.py
                raise Exception("Caching failed even after flushing.")


def write_to_cache(key, b, cache_chain):
    # TODO: cross-cache storage (maybe the data doesn't fit in 1 cache, should we do so partially?)
    for cache in cache_chain:
        if cache.has_space(len(b)):
            cache[key] = b
            return True

    return False


def write_to_storage(key, b, storage):
    storage[key] = b


def flush_cache(cache_chain, storage):
    # TODO: send all cached data -> storage & clear the caches.

    for cache in cache_chain:
        keys = []
        for key, chunk in cache:
            storage[key] = chunk
            keys.append(key)

        for key in keys:
            del cache[key]

        # TODO: test flushing to make surec cache.used_space will return 0