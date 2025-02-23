import dateutil.parser
import pyarrow as pa

import w3hn.hadoop.parquet_util as pq_util
from w3hn.datapipe.ingest.ingester import Ingester

from w3hn.log.log_init import logger
log = logger('w3hn.datapipe.ingest.file_hacker_commit')

class FileHackerCommitIngester(Ingester):
    
    # ----------------------------------------------------
    # Constants
    # ----------------------------------------------------
    
    # Unique for each ingester.
    COLUMN_NAMES = [
        "owner", "repo_name", "owner_repo",
        "file_path", "author", "commit", "commit_date",
        "total_inserts", "total_deletes", "binary",
        "partition_key"
    ]

    # Unique for each ingester.
    EXPLICIT_SCHEMA = pa.schema([
        pa.field("owner", pa.string()),
        pa.field("repo_name", pa.string()),
        pa.field("owner_repo", pa.string()),
        pa.field("file_path", pa.string()),
        pa.field("author", pa.string()),
        pa.field("commit", pa.string()),
        pa.field("commit_date", pa.timestamp('us', tz='UTC')),
        pa.field("total_inserts", pa.int64()),
        pa.field("total_deletes", pa.int64()),
        pa.field("binary", pa.int8()),
        Ingester.PARTITION_KEY_FIELD,
    ])
    
    # ----------------------------------------------------
    # Static API
    # ----------------------------------------------------

    # repo_tuple_array = [repo_tuple]
    # repo_tuple = (owner, repo_name, blame_object, deps_object, numstat_object)
    # example: [('apache', 'ant', json.loads(blame_json),
    #            json.loads(deps_json), json.loads(numstat_json))]
    def update_repos(repo_tuple_array):
        ingester = FileHackerCommitIngester()
        Ingester.update_repos_using_ingester(ingester, repo_tuple_array)

    # ----------------------------------------------------
    # Instance Initialization
    # ----------------------------------------------------
    def __init__(self,
                 aws_profile='w3hn-admin',
                 bucket='deadmandao',
                 raw_path='web3hackernetwork/data_pipeline/raw'):
        super().__init__(aws_profile, bucket, raw_path, 'file_hacker')

    # ----------------------------------------------------
    # Instance API
    # ----------------------------------------------------

    def extract_data(self, owner, repo_name,
                     blame_map=None, dependency_map=None, numstat=None):
        code_suffixes = ['.js', '.py', '.c', '.java', '.go', '.ts',
                         '.cpp', '.php', '.rb', '.cs', '.cc', '.rs',
                         '.tsx', '.scala', '.jsx']

        raw_dataset = dict()
        synthetic_key = pq_util.repo_partition_key(owner, repo_name)
        for commit in numstat:
            commit_str = commit['commit']
            commit_date_str = commit['Date']
            author = commit['Author']
            num_files = len(commit['file_list'])
            if num_files > 1000:
                self.log.error(f'{num_files} in one commit in {owner} {repo_name}')
                continue
            for file_path in commit['file_list']:
                if '.' not in file_path: continue
                extension_length = file_path[::-1].index('.') + 1
                start_of_the_ending = len(file_path) - extension_length
                extension = file_path[start_of_the_ending:]
                if extension not in code_suffixes: continue
                file_entry = commit['file_list'][file_path]
                dict_key = (file_path, author, commit_str, commit_date_str)
                if dict_key in raw_dataset:
                    meta = raw_dataset[dict_key]
                    meta['total_inserts'] += file_entry['inserts']
                    meta['total_deletes'] += file_entry['deletes']
                else:
                    meta = dict()
                    meta['total_inserts'] = file_entry['inserts']
                    meta['total_deletes'] = file_entry['deletes']
                    meta['binary'] = file_entry['binary']
                    raw_dataset[dict_key] = meta
        return raw_dataset

    def create_table(self, raw_dataset, owner, repo_name):
        unique_keys = list(raw_dataset.keys())
        unique_keys.sort()
        count = len(unique_keys)
        synthetic_key = pq_util.repo_partition_key(owner, repo_name)
        owners = [owner for i in range(count)]
        repo_names = [repo_name for i in range(count)]
        owner_repos = [f'{owner}\t{repo_name}' for i in range(count)]
        partition_keys = [f'{synthetic_key}' for i in range(count)]
        
        file_paths = list()
        authors = list()
        commits = list()
        commit_dates = list()
        total_insertss = list()
        total_deletess = list()
        binarys = list()
        for dict_key, meta in raw_dataset.items():
            file_paths.append(dict_key[0])
            authors.append(dict_key[1])
            commits.append(dict_key[2])
            commit_dates.append(dateutil.parser.isoparse(dict_key[3]))
            total_insertss.append(meta['total_inserts'])
            total_deletess.append(meta['total_deletes'])
            binarys.append(meta['binary'])

        data = [
            pa.array(owners), pa.array(repo_names), pa.array(owner_repos),
            pa.array(file_paths), pa.array(authors),
            pa.array(commits), pa.array(commit_dates),
            pa.array(total_insertss), pa.array(total_deletess),
            pa.array(binarys), pa.array(partition_keys)
        ]
        batch = pa.RecordBatch.from_arrays(data, FileHackerCommitIngester.COLUMN_NAMES)
        inferred_table = pa.Table.from_batches([batch])
        explicit_table = inferred_table.cast(FileHackerCommitIngester.EXPLICIT_SCHEMA)
        return explicit_table

    # def load_existing_for_batch(self, partition_key, owner_repos):
    #     partition_path = f'{self.dataset_path}/partition_key={partition_key}'
    #     if self.s3_util.path_exists(partition_path):
    #         print(f'file/hacker found existing dataset at {partition_path}')
    #         bucket_path = f'{self.bucket}/{partition_path}'
    #         s3fs = self.s3_util.pyarrow_fs()
    #         owner_repo_filter = ('owner_repo', 'not in', owner_repos)
    #         filters = [owner_repo_filter]
    #         legacy_dataset = pq.ParquetDataset(bucket_path,
    #                                            filesystem=s3fs,
    #                                            partitioning="hive",
    #                                            filters=filters)
    #         print(str(datetime.datetime.now()))
    #         print(f'file/hacker about to read parquet')
    #         table = legacy_dataset.read()
    #         numrows = table.num_rows
    #         print(f'file/hacker old table has {numrows} rows after filter')
    #         if numrows == 0: return None
    #         column = [partition_key for i in range(numrows)]
    #         key_field = FileHackerCommitIngester.PARTITION_KEY_FIELD
    #         table = table.add_column(table.num_columns, key_field, [column])
    #         return table
    #     else:
    #         return None
    
    # def merge_batch(self, partition_key, new_table_tuples):
    #     # tuple shape = (owner, repo_name, new_table)
    #     owner_repos = list()
    #     tables = list()
    #     for new_table_tuple in new_table_tuples:
    #         owner_repo = f'{new_table_tuple[0]}\t{new_table_tuple[1]}'
    #         owner_repos.append(owner_repo)
    #         tables.append(new_table_tuple[2])
    #     live_table = self.load_existing_for_batch(partition_key, owner_repos)
    #     if live_table != None:
    #         tables.append(live_table)
    #         print(f'file_hacker_commit old table rows: {live_table.num_rows}')
    #     merged_table = pa.concat_tables(tables, promote=False)
    #     print(f'file_hacker_commit merged table rows: {merged_table.num_rows}')
    #     return merged_table

    # def write_parquet(self, owner, repo_name, table):
    #     # print(table.to_pandas())
    #     # return
    #     s3fs = self.s3_util.pyarrow_fs()
    #     bucket_path = f'{self.bucket}/{self.dataset_path}'
    #     partition_key = pq_util.repo_partition_key(owner, repo_name)
    #     partition_path = f'{self.dataset_path}/partition_key={partition_key}'
    #     if self.s3_util.path_exists(partition_path):
    #         print(f'file/hacker deleting {self.bucket}/{partition_path}')
    #         s3fs.delete_dir(f'{self.bucket}/{partition_path}')
    #     else:
    #         print(f'file/hacker no delete at {self.bucket}/{partition_path}')
    #     print(f'file/hacker writing {self.bucket}/{partition_path}')
    #     # print(str(table.to_pandas()))
    #     # print(str(table.schema))
    #     table.sort_by([('owner', 'ascending'),
    #                    ('repo_name', 'ascending'),
    #                    ('file_path', 'ascending'),
    #                    ('author', 'ascending'),
    #                    ('commit_date','ascending')])
    #     pq.write_to_dataset(table,
    #                         root_path=bucket_path,
    #                         partition_cols=['partition_key'],
    #                         filesystem=s3fs)
    #     print('file/hacker write complete')
