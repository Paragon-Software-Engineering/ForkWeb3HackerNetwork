import datetime
import dateutil.parser
import duckdb
# import hashlib
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import sys

sys.path.append("../../../python/lib")
from aws_util import S3Util
import parquet_util as pq_util

bucket = "numstat-bucket"
raw_path = "data_pipeline/raw"
repo_file_path = raw_path+"/repo_file"

# owner = 'apache'
# repo_name = 'ant'
# owner = 'cilium'
# repo_name = 'cilium'

# def synthetic_partition_key(owner, repo_name):
#     partition_name = f'{owner}\t{repo_name}'
#     print(f'Partition Name: {partition_name}')
#     key_hash = hashlib.md5(partition_name.encode('utf-8')).hexdigest()
#     synthetic_key = key_hash[slice(0, 2)]
#     return synthetic_key

def extract_repo_file_data(owner, repo_name, numstat_object):
    repo_files = dict()
    synthetic_key = pq_util.repo_partition_key(owner, repo_name)
    for commit in numstat_object:
        commit_date = dateutil.parser.isoparse(commit['Date'])
        for file_path in commit['file_list']:
            file_entry = commit['file_list'][file_path]
            if file_path in repo_files:
                file_metadata = repo_files[file_path]
                file_metadata['num_commits'] += 1
                if commit_date < file_metadata['first_commit_date']:
                    file_metadata['first_commit_date'] = commit_date
                if commit_date > file_metadata['last_commit_date']:
                    file_metadata['last_commit_date'] = commit_date
                file_metadata['total_inserts'] += file_entry['inserts']
                file_metadata['total_deletes'] += file_entry['deletes']
            else:
                file_metadata = dict()
                file_metadata['num_commits'] = 1
                file_metadata['first_commit_date'] = commit_date
                file_metadata['last_commit_date'] = commit_date
                file_metadata['total_inserts'] = file_entry['inserts']
                file_metadata['total_deletes'] = file_entry['deletes']
                file_metadata['binary'] = file_entry['binary']
                repo_files[file_path] = file_metadata
    return repo_files

def create_table(repo_files, owner, repo_name):
    unique_files = list(repo_files.keys())
    unique_files.sort()
    count = len(unique_files)
    synthetic_key = pq_util.repo_partition_key(owner, repo_name)
    partition_key_array = [synthetic_key for i in range(count)]
    owner_array = [owner for i in range(count)]
    repo_name_array = [repo_name for i in range(count)]
    file_path_array = np.array(unique_files)
    num_commits_array = [0 for i in range(count)]
    first_commit_date_array = [datetime.datetime.now() for i in range(count)]
    last_commit_date_array = [datetime.datetime.now() for i in range(count)]
    total_inserts_array = [0 for i in range(count)]
    total_deletes_array = [0 for i in range(count)]
    binary_array = [0 for i in range(count)]

    for index in range(count):
        file_path = unique_files[index]
        meta = repo_files[file_path]
        file_path_array[index] = file_path
        num_commits_array[index] = meta['num_commits']
        first_commit_date_array[index] = meta['first_commit_date']
        last_commit_date_array[index] = meta['last_commit_date']
        total_inserts_array[index] = meta['total_inserts']
        total_deletes_array[index] = meta['total_deletes']
        binary_array[index] = meta['binary']
    
    col_partition_key = pa.array(partition_key_array)
    col_owner = pa.array(owner_array)
    col_repo_name = pa.array(repo_name_array)
    col_file_path = pa.array(file_path_array)
    col_num_commits = pa.array(num_commits_array)
    col_first_commit_date = pa.array(first_commit_date_array)
    col_last_commit_date = pa.array(last_commit_date_array)
    col_total_inserts = pa.array(total_inserts_array)
    col_total_deletes = pa.array(total_deletes_array)
    col_binary = pa.array(binary_array)

    data = [col_owner, col_repo_name, col_file_path,
            col_num_commits, col_first_commit_date, col_last_commit_date,
            col_total_inserts, col_total_deletes, col_binary,
            col_partition_key]
    column_names = ["owner", "repo_name", "file_path",
                    "num_commits", "first_commit_date", "last_commit_date",
                    "total_inserts", "total_deletes", "binary",
                    "partition_key"]
    batch = pa.RecordBatch.from_arrays(data, column_names)
    inferred_table = pa.Table.from_batches([batch])
    explicit_fields = [
        pa.field("owner", pa.string()),
        pa.field("repo_name", pa.string()),
        pa.field("file_path", pa.string()),
        pa.field("num_commits", pa.int64()),
        pa.field("first_commit_date", pa.timestamp('us', tz='UTC')),
        pa.field("last_commit_date", pa.timestamp('us', tz='UTC')),
        pa.field("total_inserts", pa.int64()),
        pa.field("total_deletes", pa.int64()),
        pa.field("binary", pa.int8()),
        pa.field("partition_key", pa.string()),
    ]
    explicit_schema = pa.schema(explicit_fields)
    explicit_table = inferred_table.cast(explicit_schema)
    return explicit_table

def merge_existing(owner, repo_name, table):
    partition_key = pq_util.repo_partition_key(owner, repo_name)
    legacy_dataset = pq.ParquetDataset(bucket + "/" + repo_file_path,
                                       filesystem=s3_util.pyarrow_fs(),
                                       partitioning="hive")
    legacy_table = legacy_dataset.read()
    sql = f"""SELECT *
               FROM legacy_table
               WHERE partition_key = '{partition_key}'
                 AND (
                   owner != '{owner}'
                   OR
                   repo_name != '{repo_name}'
                 )"""
    duck_conn = duckdb.connect()
    other_repos_table = duck_conn.execute(sql).arrow()
    merged_table = pa.concat_tables([other_repos_table, table], promote=False)
    merged_table = merged_table.sort_by([('owner','ascending'),
                                         ('repo_name','ascending'),
                                         ('file_path','ascending')])
    return merged_table

def update_parquet(owner, repo_name, table):
    s3fs = s3_util.pyarrow_fs()
    partition_key = pq_util.repo_partition_key(owner, repo_name)
    partition_path = repo_file_path+f"/partition_key={partition_key}"
    if s3_util.path_exists(partition_path):
        print(f'Found existing dataset at {partition_path}')
        table = merge_existing(owner, repo_name, table)
        s3fs.delete_dir(f'{bucket}/{partition_path}')
    pq.write_to_dataset(table,
                        root_path='numstat-bucket/data_pipeline/raw/repo_file',
                        partition_cols=['partition_key'],
                        filesystem=s3fs)

def update_repo_files_parquet(owner, repo_name, numstat_object, repo_path="ignored"):
    repo_files = extract_repo_file_data(owner, repo_name, numstat_object)
    table = create_table(repo_files, owner, repo_name)
    update_parquet(owner, repo_name, table)

def create_multiple_repo_files_parquet(numstat_path_list):
    partitions = dict()
    s3_util = S3Util(profile="enigmatt")
    s3fs = s3_util.pyarrow_fs()
    for path in numstat_path_list:
        tail = path[slice(path.index('/') + 1, len(path))]
        owner = tail[slice(0,tail.index('/'))]
        tail = tail[slice(tail.index('/') + 1, len(tail))]
        repo_name = tail[slice(0,tail.index('/'))]
        partition_key = pq_util.repo_partition_key(owner, repo_name)
        if partition_key not in partitions:
            partitions[partition_key] = list()
        partitions[partition_key].append(f'{owner}\t{repo_name}')
    for partition_key in partitions:
        repo_keys = partitions[partition_key]
        print(f'{partition_key}: '+str(len(repo_keys)))
        table = None
        for repo_key in repo_keys:
            owner = repo_key[slice(0,repo_key.index('\t'))]
            repo_name = repo_key[slice(repo_key.index('\t') + 1, len(repo_key))]
            print(f'{owner}\t{repo_name}')
            try:
                numstat_object = s3_util.get_numstat(owner, repo_name)
                repo_files = extract_repo_file_data(owner, repo_name, numstat_object)
                if table == None:
                    table = create_table(repo_files, owner, repo_name)
                else:
                    new_table = create_table(repo_files, owner, repo_name)
                    table = pa.concat_tables([table, new_table], promote=False)
            except:
                None # broken nusmtat, skip this repo
        root_path = 'numstat-bucket/data_pipeline/raw/repo_file'
        # pq.write_to_dataset(table,
        #                     root_path=root_path,
        #                     partition_cols=['partition_key'],
        #                     filesystem=s3fs)

# print(datetime.datetime.now())
# s3_util = S3Util(profile="enigmatt")
# numstat_object = s3_util.get_numstat(owner, repo_name)
# print(datetime.datetime.now())
# update_repo_files_parquet(owner, repo_name, numstat_object)
# print(datetime.datetime.now())

# numstat_path_list = list()
# with open('numstat-sorted.log', 'r') as f:
#     for line in f.readlines():
#         line = line.strip()
#         tail = line[slice(line.index('\t') + 1, len(line))]
#         numstat_path_list.append(tail)
# update_slice = slice(len(numstat_path_list) - 20000, len(numstat_path_list))
# create_multiple_repo_files_parquet(numstat_path_list[update_slice])

# s3fs = s3_util.pyarrow_fs()
# legacy_dataset = pq.ParquetDataset(f'{bucket}/{repo_file_path}',
#                                    filesystem=s3fs,
#                                    partitioning="hive")
# legacy_table = legacy_dataset.read()#to_table()

# print()
# print("What Was Written:")
# print(legacy_table.to_pandas())
