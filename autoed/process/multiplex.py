"""AutoED multiplex processing"""
import argparse
import json
import glob
import os
from collections import namedtuple
import subprocess
import shutil
from datetime import datetime

from autoed.constants import (multiplex_dir, multiplex_output_dir,
                              report_dir, report_data_dir,
                              database_json_file, multiplex_default_sample)
from autoed.dataset_singla import SinglaDataset
from autoed.global_config import global_config
from autoed.utility.filesystem import clear_dir
from autoed.process.slurm import run_slurm_job
import autoed

# The assumption of the file structure is the following
# /../../ED/SAMPLE_DIRS/CRYSTAL_DIR/SWEEP_DIR/DATA_master.h5
# SAMPLE_DIRS can be absent (i.e. SAMPLE_DIRS='')
# For more info, see AutoED documentation on multiplex.

MultiplexInfo = namedtuple(
    'MultiplexInfo',
    ['root_path',            # Full path to where ED directory is located
     'json_report_path',     # Full path to autoed_database.json
     'multiplex_dir_path',   # root_path + multiplex
     'master_file',          # Master file full path
     'sample_dirs',          # SAMPLE_DIRS
     'expt_original',        # Full path to the original expt files
     'refl_original',        # Full path to the original refl files
     'expt_copy',            # Full path to the copied expt files
     'refl_copy'             # Full path to the copied refl files
     ])


def main():
    """Find all integration results and process them with multiplex"""

    msg = 'Command to process AutoED results with multiplex'
    parser = argparse.ArgumentParser(description=msg)

    parser.add_argument('master_file', type=str,
                        help='Master file to process with multiplex.')

    parser.add_argument('--local', action='store_true',
                        default=False,
                        help='Run multiplex locally')

    args = parser.parse_args()

    dataset = MultiplexDataset(master_file=args.master_file,
                               local=args.local)

    success = dataset.copy_files()
    if success and dataset.run_condition():
        dataset.run()


class MultiplexDataset:
    """Object used to process datasets with xia2 multiplex command"""

    def __init__(self, master_file, local=True):

        self.master_file = os.path.abspath(master_file)
        self.info = info_from_master_file(self.master_file)
        self.local = local

    def copy_files(self):
        """Copies expt and refl files if the dataset indexed above threshold"""

        if not self.info:
            return False
        if not os.path.exists(self.info.json_report_path):
            return False

        with open(self.info.json_report_path, encoding='utf-8') as file:
            data = json.load(file)

        pipeline = global_config['multiplex_pipeline']
        threshold = global_config['multiplex_indexing_percent_threshold']
        dataset = SinglaDataset.from_master_file(self.master_file)

        for base_name, result in data.items():
            if base_name == dataset.base and pipeline in result:
                indexed = result[pipeline]['indexed']
                total_spots = result[pipeline]['total_spots']

                if indexed and total_spots:
                    index_percentage = 100.0 * indexed / total_spots
                    if index_percentage >= threshold:

                        spath = os.path.join(self.info.multiplex_dir_path,
                                             self.info.sample_dirs)
                        xia2_output_path = os.path.join(spath,
                                                        multiplex_output_dir)

                        os.makedirs(spath, exist_ok=True)
                        os.makedirs(xia2_output_path, exist_ok=True)

                        shutil.copy(self.info.expt_original,
                                    self.info.expt_copy)
                        shutil.copy(self.info.refl_original,
                                    self.info.refl_copy)

                        return True

        return False

    def run(self):
        """Run multiplex for the given sample"""

        path = os.path.join(self.info.multiplex_dir_path,
                            self.info.sample_dirs, multiplex_output_dir)

        data_path = os.path.join(self.info.multiplex_dir_path,
                                 self.info.sample_dirs)
        write_to_log(self.info, "Cleaning directory")
        clear_dir(path, skip_list=['multiplex.log'])
        write_to_log(self.info, "Running multiplex")
        write_to_log(self.info, f"Local set to {self.local}")

        cmd = f'xia2.multiplex $(find {data_path} -name *expt | sort -V) '
        cmd += f'$(find {data_path} -name *refl | sort -V)'

        if self.local:
            subprocess.run(cmd, shell=True, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, cwd=path, env=os.environ,
                           check=False)
        else:
            multiplex_with_slurm(self.info)

    def run_condition(self):
        """
        Counts the number of expt files in the sample directory and
        checks if it is a multiple of 'multiplex_run_on_every_nth'
        """

        out_path = os.path.join(self.info.multiplex_dir_path,
                                self.info.sample_dirs)

        n = sum(1 for f in os.listdir(out_path) if f.endswith('.expt'))

        condition = n % global_config['multiplex_run_on_every_nth'] == 0

        msg = f"There are N = {n} files. Run condition: {condition}"
        write_to_log(self.info, msg)

        return condition


def print_info(info: MultiplexInfo) -> None:
    """Prints the MultiplexInfo data"""

    print('root_path:', info.root_path)
    print('JSON path:', info.json_report_path)
    print('multiplex dir:', info.multiplex_dir_path)
    print('master file', info.master_file)
    print('sample dirs', info.sample_dirs)
    print('expt original', info.expt_original)
    print('refl original', info.refl_original)
    print('expt copy', info.expt_copy)
    print('refl copy', info.refl_copy)


def info_from_master_file(master_file):
    """Extract information about dataset necessary for multiplex run"""

    dataset = SinglaDataset.from_master_file(master_file)

    # This assumes there is just one ed_root_dir in the path, and picks the
    # first one.
    ed_root_path = '/'
    for dir_name in dataset.path.split('/'):
        if dir_name != global_config['ed_root_dir']:
            ed_root_path = os.path.join(ed_root_path, dir_name)
        else:
            break

    multiplex_dir_path = os.path.join(ed_root_path, multiplex_dir)
    sample_dirs = os.path.relpath(dataset.path, ed_root_path).split('/')
    json_report_path = os.path.join(ed_root_path, report_dir, report_data_dir,
                                    database_json_file)
    sample_path = ''

    if ed_root_path != dataset.path and len(sample_dirs) >= 3:

        for i in range(1, len(sample_dirs) - 2):
            sample_path += f"{sample_dirs[i]}/"

        if sample_path == '':
            sample_path = multiplex_default_sample

        sweep_dir = sample_dirs[-1]
        expt_copy = os.path.basename(
                        dataset.master_file).replace('_master.h5',
                                                     f"_{sweep_dir}.expt")
        refl_copy = expt_copy.replace('.expt', '.refl')

        expt_copy = os.path.join(multiplex_dir_path, sample_path,
                                 expt_copy)
        refl_copy = os.path.join(multiplex_dir_path, sample_path,
                                 refl_copy)

        expt_original, refl_original = get_original_data(dataset)

        result = MultiplexInfo(root_path=ed_root_path,
                               json_report_path=json_report_path,
                               multiplex_dir_path=multiplex_dir_path,
                               master_file=master_file,
                               sample_dirs=sample_path,
                               expt_original=expt_original,
                               refl_original=refl_original,
                               expt_copy=expt_copy,
                               refl_copy=refl_copy)

        print_info(result)
        return result

    result = None
    return result


def get_original_data(dataset):
    """
    Returns the names of the original expt and refl files (if they exist)
    obtained through integration.
    """

    pipeline = global_config['multiplex_pipeline']

    xia2_output_path = f'{pipeline}/DEFAULT/NATIVE/SWEEP1/integrate'
    xia2_output_path = os.path.join(dataset.output_path,
                                    xia2_output_path)

    # Search for all *integrate.expt files
    files = glob.glob(xia2_output_path + "/[0-9]*_integrated.expt")

    basename = os.path.basename

    if files:
        # Sort files with respect to prefix index in an ascending order
        files.sort(key=lambda f: int(basename(f).split("_")[0]))
        expt_file = files[-1]
        refl_file = os.path.splitext(expt_file)[0] + '.refl'

        if os.path.exists(refl_file):
            return expt_file, refl_file

    return None, None


def write_to_log(info: MultiplexInfo, message):
    """A bit primitive way to write a log file"""

    log_file = os.path.join(info.multiplex_dir_path, info.sample_dirs,
                            multiplex_output_dir, 'multiplex.log')

    now = datetime.now()
    date_and_time = now.strftime("%Y-%m-%d %H:%M:%S")

    with open(log_file, "a", encoding="utf-8") as file:

        file.write(f"{date_and_time} - {message}\n")


def multiplex_with_slurm(info):
    """Creates a template slurm submission script to run multiplex"""

    slurm_template = 'data/relion_slurm_cpu.json'
    slurm_template = os.path.join(autoed.__path__[0], slurm_template)

    with open(slurm_template, 'r', encoding='utf-8') as file:
        data = json.load(file)

    path = os.path.join(info.multiplex_dir_path,
                        info.sample_dirs, multiplex_output_dir)

    data_path = os.path.join(info.multiplex_dir_path,
                             info.sample_dirs)

    cmd = f'xia2.multiplex $(find {data_path} -name *expt | sort -V) '
    cmd += f'$(find {data_path} -name *refl | sort -V)\n'

    data['job']['current_working_directory'] = path
    # data['job']['environment']['USER'] = os.getenv('USER')
    data['job']['environment'].append(f"USER={global_config['slurm_user']}")
    data['job']['environment'].append(f"HOME={os.getenv('HOME')}")

    script = "#!/bin/bash\n"
    script += "echo \"$(date '+%Y-%m-%d %H:%M:%S.%3N'): \"\n"
    script += "echo \"Running on host $(hostname -s) \""
    script += "\"with job ID ${SLURM_JOB_ID:-(SLURM_JOB_ID not set)}\"\n"
    script += "source /etc/profile.d/modules.sh\n"
    script += "module load ccp4\n"
    script += "module load dials\n"
    script += cmd
    script += "echo \"$(date '+%Y-%m-%d %H:%M:%S.%3N'):\" job finished;\n"

    data['script'] = script

    slurm_file = os.path.join(path, 'slurm_script.json')
    with open(slurm_file, 'w', encoding='utf-8') as file:
        json.dump(data, file, indent=2)

    run_slurm_job(slurm_file)


if __name__ == '__main__':
    main()
