"""Manage the job queue for running jobs on a cluster. Interface with different linux resource managers (e.g. slurm)
The general workflow is
    (take job commands)
    1) compile the submission script 
    2) submit and monitor the job 
    3) record the completion of the job.
    (give files containing the stdout/stderr)
In a dataflow point of view it should be analogous to subprocess.run() that job_manager runs the command on
computational nodes in a new shell session.

Feature:
    - Allow users to add support for their own clusters. (By making new ClusterInterface classes)
    
Author: Qianzhen (QZ) Shao <qianzhen.shao@vanderbilt.edu>
Date: 2022-04-13
"""
import time
from typing import Union
from plum import dispatch
from copy import deepcopy
import os

from core.clusters._interface import ClusterInterface
from helper import get_localtime, line_feed
from Class_Conf import Config


class ClusterJob():
    '''
    This class handle jobs for cluster calculation
    API:
    constructor:
        ClusterJob.config_job()
    property:
        cluster:    cluster used for running the job (pick from list in /core/cluster/)
        sub_script_str: submission script content
        sub_script_path: submission script path
        sub_dir
        job_cluster_log
        job_id
        state: ((general_state, detailed_state), time_stamp)
    method:
        submit()
        kill()
        hold()
        release()
        get_state()
        ifcomplete()
        wait_to_end()
        wait_to_array_end()
    '''

    def __init__(self, cluster: ClusterInterface, sub_script_str: str, sub_dir=None, sub_script_path=None) -> None:
        self.cluster = cluster
        self.sub_script_str = sub_script_str
        self.sub_script_path = sub_script_path
        self.sub_dir = sub_dir

        self.job_cluster_log: str = None
        self.job_id: str = None
        self.state: tuple = None # state and the update time in s

    ### config (construct object) ###
    @classmethod
    def config_job( cls, 
                commands: Union[list[str], str],
                cluster: ClusterInterface,
                env_settings: Union[list[str], str],
                res_keywords: dict[str, str],
                sub_dir: Union[str, None] = None,
                sub_script_path: Union[str, None] = None
                ) -> 'ClusterJob':
        '''
        config job and generate a ClusterJob instance (cluster, sub_script_str)

        Args:
        commands: 
            commands to run. Can be a str of commands or a list containing strings of commands.
        cluster: 
            cluster for running the job. Should be a ClusterInterface object. 
            Available clusters can be found under core/clusters as python class defination.
            To define a new cluster class for support, reference the ClusterInterface requirement.
        env_settings: 
            environment settings in the submission script. Can be a string or list of strings
            for cmds in each line or a dict of strings for settings before and after the commands.
            In this case the key of the dict can only be 'head' and 'tail'
            Since environment settings are attached to job types. It is more conserved than the command.
            **Use presets in ClusterInterface classes to save effort**
        res_keywords: 
            resource settings. Can be a dictionary indicating each keywords or the string of the whole section.
            The name and value should be exactly the same as required by the cluster.
            **Use presets in ClusterInterface classes to save effort**
        
        Return:
        A ClusterJob object

        Example:
        >>> cluster = accre.Accre()
        >>> job = ClusterJob.config_job(
                        commands = 'g16 < xxx.gjf > xxx.out',
                        cluster = cluster,
                        env_settings = [cluster.AMBER_GPU_ENV, cluster.G16_CPU_ENV],
                        res_keywords = cluster.CPU_RES
                    )
        >>> print(job.sub_script_str)    
        #!/bin/bash
        #SBATCH --core_type=cpu
        #SBATCH --node_cores=24
        #SBATCH --job_name=job_name
        #SBATCH --partition=production
        #SBATCH --mem_per_core=4G
        #SBATCH --walltime=24:00:00
        #SBATCH --account=xxx

        #Script generated by EnzyHTP in 2022-04-21 14:09:18

        export AMBERHOME=/dors/csb/apps/amber19/
        export CUDA_HOME=$AMBERHOME/cuda/10.0.130
        export LD_LIBRARY_PATH=$AMBERHOME/cuda/10.0.130/lib64:$AMBERHOME/cuda/RHEL7/10.0.130/lib:$LD_LIBRARY_PATH
        module load Gaussian/16.B.01
        mkdir $TMPDIR/$SLURM_JOB_ID
        export GAUSS_SCRDIR=$TMPDIR/$SLURM_JOB_ID

        g16 < xxx.gjf > xxx.out
        '''
        command_str = cls._get_command_str(commands)
        env_str = cls._get_env_str(env_settings)
        res_str = cls._get_res_str(res_keywords, cluster)
        sub_script_str = cls._get_sub_script_str(
                            command_str, 
                            env_str, 
                            res_str, 
                            f'# {Config.WATERMARK}{line_feed}'
                            )

        return cls(cluster, sub_script_str, sub_dir, sub_script_path)

    # region (_get_command_str)
    @staticmethod
    @dispatch
    def _get_command_str(cmd: list) -> str:
        return line_feed.join(cmd) + line_feed

    @staticmethod
    @dispatch
    def _get_command_str(cmd: str) -> str:
        return cmd + line_feed
    # endregion

    # region (_get_env_str)
    @staticmethod
    @dispatch
    def _get_env_str(env: list) -> str:
        return line_feed.join(env) + line_feed

    @staticmethod
    @dispatch
    def _get_env_str(env: dict) -> dict:
        '''
        this means env setting is presented in a way that 
        there's cmd at the beginning and the end
        '''
        if list(env.keys()) == ['head', 'tail'] or list(env.keys()) == ['tail', 'head']:
            env = deepcopy(env)
            for i in env:
                env[i] += line_feed
            return env
        raise KeyError("Can only have 'head' or 'tail' as key in env_settings")

    @staticmethod
    @dispatch
    def _get_env_str(env: str) -> str:
        return env + line_feed
    # endregion

    # region (_get_res_str)
    @staticmethod
    @dispatch
    def _get_res_str(res: dict, cluster: ClusterInterface) -> str:
        return cluster.parser_resource_str(res)

    @staticmethod
    @dispatch
    def _get_res_str(res: str, cluster: ClusterInterface) -> str:
        return res
    # endregion

    # region (_get_sub_script_str)
    @staticmethod
    @dispatch
    def _get_sub_script_str(command_str: str, env_str: str, res_str: str, watermark: str) -> str:
        '''
        combine command_str, env_str, res_str to sub_script_str
        '''
        sub_script_str = line_feed.join((res_str, watermark, env_str, command_str))
        return sub_script_str
    
    @staticmethod
    @dispatch
    def _get_sub_script_str(command_str: str, env_str: dict, res_str: str, watermark: str) -> str:
        '''
        combine command_str, env_str, res_str to sub_script_str
        '''
        sub_script_str = line_feed.join((res_str, watermark, env_str['head'], command_str, env_str['tail']))
        return sub_script_str
    # endregion

    ### submit ###
    def submit(self, sub_dir: Union[str, None] = None, script_path: Union[str, None] = None, debug: int=0):
        '''
        submit the job to the cluster queue. Make the submission script. Submit.
        Arg:
            sub_dir: 
                dir for submission. commands in the sub script usually run under this dir.
                * will use self.sub_dir if not provided
            script_path: 
                path for submission script generation.
                (default: sub_dir/submit.cmd; 
                will be sub_dir/submit_#.cmd if the file exists
                # is a growing index)
                * will use self.sub_script_path if sub_dir is not provided
            debug:
                debug behavior that does not submit the job but print out the submission command.
                         
        Return:
            self.job_id

        Attribute added:
            sub_script_path
            job_id
            sub_dir
        
        Example:
            >>> sub_dir = '/EnzyHTP-test/test_job_manager/'
            >>> job.submit( sub_dir= sub_dir,
                            script_path= sub_dir + 'test.cmd')
        '''
        # use self attr if nothing is provided
        if sub_dir is None:
            sub_dir = self.sub_dir
            script_path = self.sub_script_path
        else:
        # make default value for filename
            if script_path is None:
                script_path = sub_dir + '/submit.cmd'
                i = 0
                while os.path.isfile(script_path):
                    i += 1
                    script_path = sub_dir + f'/submit_{i}.cmd'  # TODO(shaoqz): move to helper

        # san check
        if self.job_id is not None:
            if self.state[0][0] in ['run', 'pend']:
                raise Exception(f'attempt to submit a non-finished (pend, run) job.{line_feed} id: {self.job_id} state: {self.state[0][0]}::{self.state[0][1]} @{get_localtime(self.state[1])}')
            else: #finished job
                if Config.debug > 0:
                    print(f'WARNING: re-submitting a ended job. The job id will be renewed and the old job id will be lose tracked{line_feed} id: {self.job_id} state: {self.state[0][0]}::{self.state[0][1]} @{get_localtime(self.state[1])}')

        self.sub_script_path = self._deploy_sub_script(script_path)
        if Config.debug > 1:
            print(f'submitting {script_path} in {sub_dir}')
        self.job_id, self.job_cluster_log = self.cluster.submit_job(sub_dir, script_path, debug=debug)
        self.sub_dir = sub_dir
        if Config.debug > 0:
            self._record_job_id_to_file()

        return self.job_id

    def _deploy_sub_script(self, out_path: str) -> None:
        '''
        deploy the submission scirpt for current job
        store the out_path to self.sub_script_path
        '''
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(self.sub_script_str)
        return out_path

    def _record_job_id_to_file(self):
        '''
        record submitted job id to a file to help removing and tracking all jobs upon aborting
        '''
        # get file path
        if Config.JOB_ID_LOG_PATH == '':
            job_id_log_path = f'{self.sub_dir}/submitted_job_ids.log'
        else:
            job_id_log_path = Config.JOB_ID_LOG_PATH
        # write to
        with open(job_id_log_path, 'a') as of:
            of.write(f'{self.job_id} {self.sub_script_path}{line_feed}')

    ### control ###
    def kill(self):
        '''
        kill the job with the job_id
        '''
        self.require_job_id()

        if Config.debug >= 1:
            print(f'killing: {self.job_id}')
        self.cluster.kill_job(self.job_id)

    def hold(self):
        '''
        hold the job from running
        '''
        self.require_job_id()

        if Config.debug >= 1:
            print(f'holding: {self.job_id}')
        self.cluster.hold_job(self.job_id)

    def release(self):
        '''
        release the job to run
        '''
        self.require_job_id()

        if Config.debug >= 1:
            print(f'releasing: {self.job_id}')
        self.cluster.release_job(self.job_id)

    ### monitor ###
    def get_state(self) -> tuple[str, str]:
        '''
        determine if the job is:
        pend, 
        run, 
        complete, 
        canel,
        error

        Return: 
            a tuple of
            (a str of pend or run or complete or canel or error,
                the real keyword form the cluster)
        '''
        self.require_job_id()

        result = self.cluster.get_job_state(self.job_id)
        self.state = (result, time.time())
        return result

    def ifcomplete(self) -> bool:
        '''
        determine if the job is complete.
        '''
        return self.get_state()[0] == 'complete'

    def wait_to_end(self, period: int) -> None:
        '''
        monitor the job in a specified frequency
        until it ends with 
        complete, error, or cancel
        NOTE: this wont treat it as an end if hold or requeue your job
              you should do that if other users in the cluster complain 
        Args:
            period: the time cycle for detect job state (Unit: s)
        '''
        # san check
        self.require_job_id()
        # monitor job
        while True:
            # exit if job ended
            if self.get_state()[0] in ('complete', 'error', 'cancel'):
                return type(self)._action_end_with(self)
            # check every {period} second 
            if Config.debug >= 2:
                local_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.state[1]))
                print(f'Job {self.job_id} state: {self.state[0][0]} (at {local_time})')
            time.sleep(period)

    @staticmethod
    def _action_end_with(ended_job: 'ClusterJob') -> None:
        '''
        the action when job ends with the {end_state}
        the end_state can only be one of ('complete', 'error', 'cancel')
        '''
        end_state = ended_job.state[0]
        general_state = end_state[0]
        detailed_state = end_state[1]

        if general_state not in ('complete', 'error', 'cancel'):
            raise TypeError("_action_end_with: only take state in ('complete', 'error', 'cancel')")
        # general action
        if Config.debug > 0:
            local_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ended_job.state[1]))
            print(f'Job {ended_job.job_id} end with {general_state}::{detailed_state} at {local_time} !')
        # state related action
        if general_state == 'complete':
            pass
        if general_state == 'error':
            pass
        if general_state == 'cancel':
            pass # may be support pass in callable to do like resubmit

    @classmethod
    def wait_to_array_end(
            cls, 
            jobs: list['ClusterJob'], 
            period: int, 
            array_size: int = 0, 
            sub_dir = None, 
            sub_scirpt_path = None
        ) -> None:
        '''
        submit an array of jobs in a way that only {array_size} number of jobs is submitted simultaneously.
        Wait until all job ends.
        
        Args:
        jobs:
            a list of ClusterJob object to be execute
        period:
            the time cycle for update job state change (Unit: s)
        array_size:
            how many jobs are allowed to submit simultaneously. (default: 0 means all -> len(inp))
            (e.g. 5 for 100 jobs means run 20 groups. All groups will be submitted and 
            in each group, submit the next job only after the previous one finishes.)
        sub_dir: (default: self.sub_dir)
            submission directory for all jobs in the array. Overwrite existing self.sub_dir in the job obj
            * you can set the self value during config_job to make each job different
        sub_scirpt_path: (default: self.sub_script_path)
            path of the submission script. Overwrite existing self.sub_script_path in the job obj
            * you can set the self value during config_job to make each job different
        
        Return:
        return a list of not completed job. (error + canceled)
        '''
        # san check
        for job in jobs:
            if job.cluster.NAME != jobs[0].cluster.NAME:
                raise TypeError(f'array job need to use the same cluster! while {job.cluster.NAME} and {jobs[0].cluster.NAME} are found.')
        # default value
        if array_size == 0:
            array_size = len(jobs)
        # set up array job
        current_active_job = []
        total_job_num = len(jobs)
        finished_job = []
        i = 0 # submitted job number
        while len(finished_job) < total_job_num:
            # before every job finishes, run
            # 1. make up the running chunk to the array size
            while len(current_active_job) < array_size and i < len(jobs):
                jobs[i].submit(sub_dir, sub_scirpt_path)
                current_active_job.append(jobs[i])
                i += 1
            # 2. check every job in the array to detect completion of jobs and deal with some error
            for j in range(len(current_active_job)-1,-1,-1):
                job = current_active_job[j]
                if job.get_state()[0] not in ['pend', 'run']:
                    if Config.debug > 1:
                        cls._action_end_with(job)
                    finished_job.append(job)
                    del current_active_job[j]
            # 3. wait a period before next check TODO: add behavior that the more checking the longer time till a limit
            time.sleep(period)
        
        # summarize
        n_complete = list(filter(lambda x: x.state[0][0] == 'complete', finished_job))
        n_error = list(filter(lambda x: x.state[0][0] == 'error', finished_job))
        n_cancel = list(filter(lambda x: x.state[0][0] == 'cancel', finished_job))
        if Config.debug > 0:
            print(f'Job array finished: {len(n_complete)} complete {len(n_error)} error {len(n_cancel)} cancel')
        
        return n_error + n_cancel

    ### misc ###
    def require_job_id(self) -> None:
        '''
        require job to be submitted and have an id
        '''
        if self.job_id is None:
            raise AttributeError('Need to submit the job and get an job id!')
    
    @dispatch
    def _(self):
        '''
        dummy method for dispatch
        '''
        pass