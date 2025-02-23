# ========= External Libraries =================
# import datetime
import bz2
import json
import os
import sys
# import threading
# from concurrent.futures import ThreadPoolExecutor
# from concurrent.futures import as_completed
# ----------------------------------------------

# ========== Project Root Path =================
this_path = os.path.abspath(sys.path[0])
project_dir = 'Web3HackerNetwork'
w3hndex = this_path.index(project_dir)
root_path = this_path[0:w3hndex + len(project_dir)]
# ---------- Local Library Path ----------------
# sys.path.insert(0, f'{root_path}/python')
# ---------- Local Libraries -------------------
# from w3hn.datapipe.ingest.file_hacker_commit import FileHackerCommitIngester
# from w3hn.datapipe.ingest.repo_file import RepoFileIngester
# from w3hn.aws.aws_util import S3Util
# import w3hn.hadoop.parquet_util as pq_util
# ----------------------------------------------

print(__file__)

owner = 'DemocracyClub'
repo_name = 'yournextrepresentative'
rel_data_path = 'python/sandbox/bob/data'
rel_sample_dir = f'{rel_data_path}/json/{owner}/{repo_name}/'
rel_sample_path = f'{rel_sample_dir}/dependency_map.json.bz2'
sample_path = f'{root_path}/{rel_sample_path}'

with open(sample_path, 'rb') as deps_bz2:
    deps = json.loads(bz2.decompress(deps_bz2.read()))

deps_set = set()
for file_path, libs in deps.items():
    for lib in libs:
        unique_key = f'{file_path}\t{lib}'
        # print(unique_key)
        deps_set.add(unique_key)

    
srted = list(deps_set)
srted.sort()
for val in srted:
    (path, lib) = val.split('\t', 2)
    print(path, lib)
