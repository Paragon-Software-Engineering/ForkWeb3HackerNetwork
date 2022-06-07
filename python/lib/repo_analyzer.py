import os

from monitor import timeit
from db_driven_task import DBDrivenTaskProcessor, DBTask
from child_process import ChildProcessContainer
from shutil import rmtree


class RepoAnalyzer(DBDrivenTaskProcessor):
    def __init__(self):
        super().__init__()
        self.get_next = self.GetNextRepoForAnalysis(self)
        self.all_done = self.ReleaseRepo(self)
        self.repo_owner = None
        self.repo_name = None

        self.repo_id = None
        self.repo_owner = None
        self.repo_name = None
        self.repo_dir = None
        self.numstat_dir = None

    class GetNextRepoForAnalysis(DBTask):
        def __init__(self, mom):
            self.mom = mom

        def get_proc_name(self):
            return 'ReserveNextRepoForAnalysis'

        def get_proc_parameters(self):
            return [self.mom.machine_name]

        def process_db_results(self, result_args):
            for goodness in self.mom.cursor.stored_results():
                result = goodness.fetchone()
                if result:
                    self.mom.repo_id = int(result[0])
                    self.mom.repo_owner = result[1]
                    self.mom.repo_name = result[2]
                    self.mom.repo_dir = result[3]
                    self.mom.numstat_dir = result[4]
            return result

    class ReleaseRepo(DBTask):
        def __init__(self, mom):
            self.mom = mom

        def get_proc_name(self):
            return 'ReleaseRepoFromAnalysis'

        def get_proc_parameters(self):
            return [self.mom.repo_id]

        def process_db_results(self, result_args):
            print(result_args)

    def get_job_fetching_task(self):
        return self.get_next

    def get_job_completion_task(self):
        return self.all_done

    @timeit
    def process_task(self):
        print('Removing repo dir '+self.repo_owner+'/'+self.repo_name)
        rmtree('./repos/'+self.repo_owner+'/'+self.repo_name, ignore_errors=True)
        if len(os.listdir('./repos/'+self.repo_owner)) < 1:
            print('Removing empty parent repo dir '+self.repo_owner)
            os.rmdir('./repos/'+self.repo_owner)


if __name__ == "__main__":
    ChildProcessContainer(RepoAnalyzer(), 'repo_analyzer').join()