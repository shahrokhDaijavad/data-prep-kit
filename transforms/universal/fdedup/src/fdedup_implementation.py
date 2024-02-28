from argparse import ArgumentParser, Namespace
from typing import Any

import pyarrow as pa
import ray
from ray.util import ActorPool
from ray.actor import ActorHandle
from ray.util.metrics import Gauge


from data_processing.data_access import DataAccessFactory
from data_processing.ray import (
    DefaultTableTransformConfiguration,
    DefaultTableTransformRuntime,
    TransformTableProcessor,
    RayUtils,
)
from data_processing.transform import AbstractTableTransform
from data_processing.utils import TransformUtils, RANDOM_SEED, str2bool
from text_normalizer import normalize as text_normalize
import numpy as np
import mmh3
import sentencepiece
import time

from fdedup_support import (
    find,
    fuzzy_optimal_param,
    MurmurMH,
    DocCollector,
    DocsMinHash,
    BucketsHash,
    BucketsHashProcessor,
    BucketsHashProcessorInvoker,
    REQUEST_LEN
)


class FdedupPreprocessor(AbstractTableTransform):
    """
    Implements fuzzy dedup data preprocessor (building tables and minhashes).
    """

    def __init__(self, config: dict):
        """
        Initialize based on the dictionary of configuration information.
        :param config: initialization parameters, with the following keys
            doc_column - name of doc column
            doc_id_int_column - name of int doc id column
            word_shingle_size - word shingle size
            mm_min_hash - MurmurMH class
            num_bands - number of bands
            length_band band length
            remote_buckets - bucket actors
            remote_minhashes - minhash actors
            is_japanese - japanese flag
            delimiter - delimiter
        """
        super().__init__(config)
        self.doc_column = config.get("doc_column", "")
        self.doc_id_column = config.get("doc_id_int_column", "")
        self.word_shingle_size = config.get("word_shingle_size", 1)
        self.delimiter = config.get("delimiter", " ")
        self.mn_min_hash = config.get("mm_min_hash", None)
        self.num_bands = config.get("num_bands", 1)
        self.length_band = config.get("length_band", 1)
        self.buckets = config.get("remote_buckets", [])
        self.minhashes = config.get("remote_minhashes", [])
        self.is_japanese = config.get("is_japanese", False)
        if self.is_japanese:
            self.sp = sentencepiece.SentencePieceProcessor()
            self.sp.load("./ja.sp.model")

    def _generate_word_shingles(self, text: str) -> list[str]:
        """
        Generate word shingles
        :param text: document
        :return: list of shingles
        """
        if self.is_japanese:
            # We are using special shingles generation for japanese text
            shingles = []
            try:
                words = self.sp.encode_as_pieces(text_normalize(text))
                word_count = len(words)
                for i in range(0, max(1, word_count - self.word_shingle_size + 1)):
                    shingles.append(self.delimiter.join(words[i: i + self.word_shingle_size]))
            except Exception as e:
                print(f"Exception during japanese shingle building {e}")
                self.is_japanese = False
            return shingles
        else:
            # for all other languages
            separators = find(text, self.delimiter)
            if len(separators) + 1 <= self.word_shingle_size:
                return [text]
            bounds = [-1] + separators + [len(text)]
            return [
                text[bounds[i] + 1: bounds[i + self.word_shingle_size]]
                for i in range(0, len(bounds) - self.word_shingle_size)
            ]

    def _generate_minhashes(self, shingles: list[str]) -> np.array:
        """
        Generate minhashes
        :param shingles:
        :return: generated minhashes
        """
        min_hashes = self.mn_min_hash.minhash(len(shingles), shingles)
        num_min_hashes = len(min_hashes)
        assert self.num_bands * self.length_band <= num_min_hashes, (
            f"num_bans*band_len must be <= num min hashes, was num_bands={self.num_bands}, "
            f"bands_len={self.length_band}, num_min hashes={num_min_hashes}"
        )
        return min_hashes

    def _generate_buckets(self, min_hashes: np.array) -> list[int]:
        """
        Generate buckets
        :param min_hashes: array of minhashes
        :return:
        """
        return [
            mmh3.hash64(min_hashes[i * self.length_band: (i + 1) * self.length_band],
                        seed=RANDOM_SEED, signed=False)[0]
            for i in range(self.num_bands)
        ]

    def _submit_buckets_minhashes(
            self, buckets: dict[int, list[int]], minhashes: list[tuple[int, int, np.array]]
    ) -> None:
        """
        Submit buckets to hash
        :param buckets: buckets
        :param minhashes: minhashes
        :return: None
        """
        # bucket requests
        request = [[] for _ in range(len(self.buckets))]
        for key, value in buckets.items():
            request[key % len(self.buckets)].append((key, value))
        # Submit requests to appropriate bucket collectors
        remote_replies = []
        i = 0
        for req in request:
            if len(req) > 0:  # Only submit if the length is greater then 0
                remote_replies.append(self.buckets[i].add_buckets.remote(req))
            i += 1
        # Minhashes
        request = [[] for _ in range(len(self.minhashes))]
        for minh in minhashes:
            request[minh[0] % len(self.minhashes)].append(minh)
        # Submit requests to appropriate minhash collectors
        i = 0
        for req in request:
            if len(req) > 0:  # Only submit if the length is greater then 0
                remote_replies.append(self.minhashes[i].add_minhashes.remote(req))
            i += 1
        # wait for completion
        RayUtils.wait_for_execution_completion(replies=remote_replies)

    def transform(self, table: pa.Table) -> tuple[list[pa.Table], dict[str, Any]]:
        """
        Preprocessing table content.
        :param table: table
        :return: resulting table, statistics
        """
        def flush(limit: int) -> None:
            """
            flushing buckets and minhashes to dedicated actors
            :param limit: number of buckets to flush
            :return: None
                """
            if len(buckets) >= limit:  # time to submit
                nonlocal num_buckets
                nonlocal num_minhashes
                self._submit_buckets_minhashes(buckets, minhashes)
                num_buckets = num_buckets + len(buckets)
                num_minhashes = num_minhashes + len(minhashes)
                buckets.clear()
                minhashes.clear()

        # make sure that the doc column exists
        if not TransformUtils.validate_columns(table=table, required=[self.doc_column, self.doc_id_column]):
            return [], {}
        # Inner variables
        buckets = {}
        minhashes = []
        num_buckets = 0
        num_minhashes = 0
        docs = table[self.doc_column]
        doc_ids = table[self.doc_id_column]
        # for every document/its integer id
        for n in range(table.num_rows):
            doc = docs[n].as_py()
            doc_id = doc_ids[n].as_py()
            shingles = self._generate_word_shingles(TransformUtils.normalize_string(doc))
            if len(shingles) > 0:
                mh = self._generate_minhashes(shingles)
                minhashes.append((doc_id, len(doc), mh))
                candidates = self._generate_buckets(mh)

                for b_hash in candidates:
                    bucket_array = buckets.get(b_hash)
                    if bucket_array is None:
                        buckets[b_hash] = [doc_id]
                    else:
                        bucket_array.append(doc_id)
                flush(REQUEST_LEN)
        flush(0)
        # peg stats
        stats = {
            "generated buckets": num_buckets,
            "generated minhashes": num_minhashes
        }
        return [], stats


class FdedupFilter(AbstractTableTransform):
    """
    Filtering documents
    """
    def __init__(self, config: dict):
        """
        Initialize based on the dictionary of configuration information.
        The dictionary should contain the following:
            doc_column - name of doc column
            doc_id_int_column - name of int doc id column
            cluster_column - name of the cluster column
            remote_docs - list of remote doc collectors
        """
        super().__init__(config)
        self.doc_column = config.get("doc_column", "")
        self.doc_id_column = config.get("doc_id_int_column", "")
        self.cluster_column = config.get("cluster_column", "")
        self.docs = config.get("remote_docs", "")

    def transform(self, table: pa.Table) -> tuple[list[pa.Table], dict[str, Any]]:
        """
        De duping (filtering) table content.
        :param table: table
        :return: resulting table, statistics
        """
        # make sure that the doc column exists
        if not TransformUtils.validate_columns(table=table, required=[self.doc_column, self.doc_id_column]):
            return [], {}
        # inner variables
        ids = table.column(self.doc_id_column)
        # Submit requests to an appropriate doc collectors
        request = [[] for _ in range(len(self.docs))]
        for value in ids:
            doc_id = value.as_py()
            request[doc_id % len(self.docs)].append(doc_id)
        remote_replies = []
        i = 0
        for req in request:
            if len(req) > 0:  # Only submit if the length is greater then 0
                remote_replies.append(self.docs[i].filter.remote(req))
            i += 1
        # Process replies
        unique = {}
        while remote_replies:
            # Wait for replies
            ready, not_ready = ray.wait(remote_replies)
            reply = ray.get(ready)[0]
            unique.update(reply)
            remote_replies = not_ready
        # Filter out table
        mask = []
        clusters = []
        # Actual filtering
        for n in range(table.num_rows):
            doc_id = ids[n].as_py()
            if doc_id in unique:
                mask.append(True)
                clusters.append(unique.pop(doc_id))
            else:
                mask.append(False)
        # build out table
        out_table = TransformUtils.add_column(table=table.filter(mask), name=self.cluster_column, content=clusters)
        # build execution statistics
        stats = {"source_documents": table.num_rows, "result_documents": out_table.num_rows}
        return [out_table], stats


class FdedupRuntime(DefaultTableTransformRuntime):
    """
    Fuzzy dedup runtime support. Here we are using set environment to implement first two steps of fuzzy dedup
    processing - preprocessing and bucket hash processing
    """
    def __init__(self, params: dict[str, Any]):
        """
        Create filter runtime
        :param params: parameters, that should include
            doc_column - name of the document column
            id_column - name of the integer doc id column
            cluster_column - name of the cluster column
            worker_options - start options for preprocessor - from the orchestrator configuration
            bucket_cpu - number of cpus for bucket actor
            doc_cpu - number of cpus for doc actor
            mhash_cpu - number of cpus for minhash actor
            d_actors - number of document actors
            b_actors - number of bucket actors
            m_actors - number of minhash actors
            n_preprocessors: int,
            # fuzzy specific parameters
            num_permutations - number of permutations
            threshold - threshold
            world_shingle_size - word shingles size
            is_japanese - japanese data flag
            delimiters - delimiter
        """
        super().__init__(params)
        self.sum_buckets = 0
        self.sum_buckets_mem = 0
        self.sum_mh = 0
        self.sum_mh_mem = 0
        self.document_collectors = []

    def set_environment(self, data_access_factory: DataAccessFactory,
                        statistics: ActorHandle, files: list[str]) -> dict[str, Any]:
        """
        Set environment for filter execution
        :param data_access_factory - data access factory
        :param statistics - reference to the statistics object
        :param files - list of files to process
        :return: dictionary of filter init params
        """
        threshold = self.params.get("threshold", 0.8)
        num_permutations = self.params.get("num_permutations", 64)
        # compute fuzzy dedup parameters
        num_buckets, length_bucket = fuzzy_optimal_param(
            threshold=threshold, num_perm=num_permutations,
            false_positive_weight=0.5, false_negative_weight=0.5
        )
        print(f"Fuzzy: num buckets {num_buckets}, bucket length {length_bucket}")
        mm_min_hash = MurmurMH(num_perm=num_permutations, seed=RANDOM_SEED)
        # Build bucket and minhash collectors
        bucket_collectors = RayUtils.create_actors(
            clazz=BucketsHash,
            params={},
            actor_options={"num_cpus": self.params.get("bucket_cpu", 0.5)},
            n_actors=self.params.get("b_actors", 1),
        )
        print(f"created {len(bucket_collectors)} bucket actors")
        minhash_collectors = RayUtils.create_actors(
            clazz=DocsMinHash,
            params={},
            actor_options={"num_cpus": self.params.get("mhash_cpu", 0.5)},
            n_actors=self.params.get("m_actors", 1),
        )
        print(f"created {len(minhash_collectors)} minhash actors")
        # At this point we do not need doc collectors, so we can increase the amount
        # of preprocessors to improve performance
        worker_options = self.params.get("worker_options", None)
        n_readers = (self.params.get("n_preprocessors", 1) +
                     int(self.params.get("d_actors", 1) * self.params.get("doc_cpu", 1) /
                         worker_options["num_cpus"]))
        print(f"Table preprocessing uses {n_readers} readers")
        # Create preprocessing actors
        processor_params = {
            "data_access_factory": data_access_factory,
            "transform_class": FdedupPreprocessor,
            "statistics": statistics,
            "transform_params": {
                "doc_column": self.params.get("doc_column", ""),
                "doc_id_int_column": self.params.get("id_column", ""),
                "word_shingle_size": self.params.get("world_shingle_size", 1),
                "mm_min_hash": mm_min_hash,
                "num_bands": num_buckets,
                "length_band": length_bucket,
                "remote_buckets": bucket_collectors,
                "remote_minhashes": minhash_collectors,
                "is_japanese": self.params.get("is_japanese", False),
                "delimiter": self.params.get("delimiter", " ")
            },
            "base_table_stats": False,
        }
        processors_list = RayUtils.create_actors(
            clazz=TransformTableProcessor,
            params=processor_params,
            actor_options=worker_options,
            n_actors=n_readers,
        )
        print(f"created {len(processors_list)} table processor actors")
        # Execute preprocessing
        # create gauges
        files_in_progress_gauge = Gauge("preprocessing_files_in_progress",
                                        "Number of files in progress, preprocessing")
        files_completed_gauge = Gauge("preprocessing_files_processed_total",
                                      "Number of files completed, preprocessing")
        available_cpus_gauge = Gauge("preprocessing_available_cpus",
                                     "Number of available CPUs, preprocessing")
        available_gpus_gauge = Gauge("preprocessing_available_gpus",
                                     "Number of available GPUs, preprocessing")
        available_memory_gauge = Gauge("preprocessing_available_memory",
                                       "Available memory, preprocessing")
        available_object_memory_gauge = Gauge("preprocessing_available_object_store",
                                              "Available object store, preprocessing")
        print_interval = int(len(files) / 100)
        if print_interval == 0:
            print_interval = 1
        # process data
        processors = ActorPool(processors_list)
        RayUtils.process_files(
            executors=processors,
            files=files,
            print_interval=print_interval,
            files_in_progress_gauge=files_in_progress_gauge,
            files_completed_gauge=files_completed_gauge,
            available_cpus_gauge=available_cpus_gauge,
            available_gpus_gauge=available_gpus_gauge,
            available_memory_gauge=available_memory_gauge,
            object_memory_gauge=available_object_memory_gauge,
        )
        # Clean up processors
        for processor in processors_list:
            ray.kill(actor=processor, no_restart=True)
        del processors
        # Create document collectors
        self.document_collectors = RayUtils.create_actors(
            clazz=DocCollector,
            params={},
            actor_options={"num_cpus": self.params.get("doc_cpu", 0.5)},
            n_actors=self.params.get("d_actors", 1),
        )
        print(f"created {len(self.document_collectors)} document actors")
        # create bucket processors
        bucket_processors_list = RayUtils.create_actors(
            clazz=BucketsHashProcessor,
            params={
                "remote_docs": self.document_collectors,
                "remote_minhashes": minhash_collectors,
                "mm_min_hash": mm_min_hash,
                "threshold": threshold * num_permutations,
                "statistics": statistics,
            },
            actor_options=worker_options,
            n_actors=self.params.get("n_preprocessors", 1),
        )
        print(f"created {len(bucket_processors_list)} bucket processor actors")
        # create bucket processors invoker
        bucket_processor_invoker = (BucketsHashProcessorInvoker.options(num_cpus=self.params.get("bucket_cpu", 0.5)).
                                    remote(bucket_processors=bucket_processors_list))
        # Add invoker to the buckets
        bucket_replies = [
            collector.add_processing_submitter.remote(submitter=bucket_processor_invoker)
            for collector in bucket_collectors
        ]
        RayUtils.wait_for_execution_completion(replies=bucket_replies)
        # start bucket processing and wait for completion
        start = time.time()
        bucket_replies = [collector.process_buckets.remote() for collector in bucket_collectors]
        RayUtils.wait_for_execution_completion(replies=bucket_replies)
        # Wait for pool to complete
        ray.get(bucket_processor_invoker.wait_for_completion.remote())
        print(f"Done processing buckets in {(time.time() - start) / 60} min")
        # At this point we do not need bucket and minhash actors, remove them
        # but first get usage information
        # Bucket collector
        replies = [collector.get_size.remote() for collector in bucket_collectors]
        while replies:
            ready, not_ready = ray.wait(replies)
            b_amount, b_memory = ray.get(ready)[0]
            self.sum_buckets += b_amount
            self.sum_buckets_mem += b_memory
            replies = not_ready
        for collector in bucket_collectors:
            ray.kill(actor=collector, no_restart=True)
        # minhash collector
        replies = [collector.get_size.remote() for collector in minhash_collectors]
        while replies:
            ready, not_ready = ray.wait(replies)
            m_amount, m_memory = ray.get(ready)[0]
            self.sum_mh += m_amount
            self.sum_mh_mem += m_memory
            replies = not_ready
        for collector in minhash_collectors:
            ray.kill(actor=collector, no_restart=True)
        # Clean up processors
        for processor in bucket_processors_list:
            ray.kill(actor=processor, no_restart=True)
        ray.kill(bucket_processor_invoker)
        # At this point we are ready for filtering
        return {
            "doc_column": self.params.get("doc_column", ""),
            "doc_id_int_column": self.params.get("id_column", ""),
            "cluster_column": self.params.get("cluster_column", ""),
            "remote_docs": self.document_collectors,
        }

    def compute_execution_stats(self, stats: dict[str, Any]) -> dict[str, Any]:
        """
        Compute execution statistics
        :param stats: output of statistics
        :return: job execution statistics
        """
        # Get document collector statistics
        sum_docs = 0
        sum_docs_mem = 0
        sum_removed = 0
        sum_removed_mem = 0
        replies = [collector.get_size.remote() for collector in self.document_collectors]
        while replies:
            ready, not_ready = ray.wait(replies)
            #            print(f"Getting document collector stats {ray.get(ready)}")
            d_amount, d_memory, r_amount, r_memory = ray.get(ready)[0]
            sum_docs += d_amount
            sum_docs_mem += d_memory
            sum_removed += r_amount
            sum_removed_mem += r_memory
            replies = not_ready
        overall_hash_memory = self.sum_buckets_mem + self.sum_mh_mem + sum_docs_mem + sum_docs_mem + sum_removed_mem
        dedup_prst = 100 * (1.0 - stats.get("result_documents", 1) / stats.get("source_documents", 0))
        return {
            "number of buckets": self.sum_buckets,
            "number of docs": sum_docs,
            "number of removed docs": sum_removed,
            "number of min hashes": self.sum_mh,
            "overall hash memory": overall_hash_memory,
            "de duplication %": dedup_prst,
        } | stats


class FdedupTableTransformConfiguration(DefaultTableTransformConfiguration):
    """
    Provides support for configuring and using the associated Transform class include
    configuration with CLI args and combining of metadata.
    """

    def __init__(self):
        super().__init__(name="fdedup", runtime_class=FdedupRuntime, transform_class=FdedupFilter)
        self.params = {}

    def add_input_params(self, parser: ArgumentParser) -> None:
        """
        Add Transform-specific arguments to the given  parser.
        """
        parser.add_argument("--doc_column", type=str, default="contents", help="document column name")
        parser.add_argument("--id_column", type=str, default="int_document_id",
                            help="integer document id column name")
        parser.add_argument("--cluster_column", type=str, default="cluster", help="cluster column name")
        parser.add_argument("--bucket_cpu", type=float, default=0.5, help="number of CPUs per bucket hash")
        parser.add_argument("--mhash_cpu", type=float, default=0.5, help="number of CPUs per minhash hash")
        parser.add_argument("--doc_cpu", type=float, default=0.5, help="number of CPUs per doc hash")
        parser.add_argument("--num_doc_actors", type=int, default=1, help="number of doc actors to use")
        parser.add_argument("--num_minhash_actors", type=int, default=1, help="number of minhash actors to use")
        parser.add_argument("--num_bucket_actors", type=int, default=1, help="number of bucket actors to use")
        parser.add_argument("--num_preprocessors", type=int, default=1, help="number of preprocessors to use")
        parser.add_argument("--num_permutations", type=int, default=64, help="number of permutations")
        parser.add_argument("--threshold", type=float, default=0.8, help="threshold")
        parser.add_argument("--shingles_size", type=int, default=5, help="number of words in shingle")
        parser.add_argument("--delimiters", type=str, default=" ", help="delimiter for splitting document")
        parser.add_argument(
            "--japanese_data", type=lambda x: bool(str2bool(x)), default=False, help="japanese data indicator"
        )

    def apply_input_params(self, args: Namespace) -> bool:
        """
        Validate and apply the arguments that have been parsed
        :param args: user defined arguments.
        :return: True, if validate pass or False otherwise
        """
        # columns
        self.params["doc_column"] = args.doc_column
        self.params["id_column"] = args.id_column
        self.params["cluster_column"] = args.cluster_column
        # infrastructure
        self.params["worker_options"] = args.worker_options
        self.params["bucket_cpu"] = args.bucket_cpu
        self.params["doc_cpu"] = args.doc_cpu
        self.params["mhash_cpu"] = args.mhash_cpu
        self.params["d_actors"] = args.num_doc_actors
        self.params["b_actors"] = args.num_bucket_actors
        self.params["m_actors"] = args.num_minhash_actors
        self.params["n_preprocessors"] = args.num_preprocessors
        # fuzzy specific parameters
        self.params["num_permutations"] = args.num_permutations
        self.params["threshold"] = args.threshold
        self.params["world_shingle_size"] = args.shingles_size
        self.params["is_japanese"] = args.japanese_data
        self.params["delimiters"] = args.delimiters


        print(f"fuzzy dedup params are {self.params}")
        return True
