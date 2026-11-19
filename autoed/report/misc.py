"""Module with helper function for report generation and xia2 multiplex"""
import os
import shutil
import argparse

import autoed
from autoed.report.json_database import JsonDatabase
from autoed.report.parser import Xia2OutputParser
from autoed.constants import report_data_dir


def add_to_database():
    """
    A function that checks if processing finished and adds the result to
    AutoED database.
    """

    from autoed.dataset_singla import SinglaDataset
    import time
    from autoed.constants import PROCESS_DONE_TRIGGER
    import sys
    from autoed.global_config import global_config
    from autoed.process.multiplex import MultiplexDataset

    msg = 'Wait until the trigger file (.done) '
    msg += 'and then add dataset/pipeline to AutoED database.'
    msg += 'Additionally, can run xia2 multiplex using the new result.'

    parser = argparse.ArgumentParser(description=msg)
    parser.add_argument('master_file', type=str,
                        help='The name of the pipeline to add to database')
    parser.add_argument('pipeline_name', type=str,
                        help='The name of the pipeline to add to database')

    parser.add_argument('--multiplex', action='store_true',
                        default=False,
                        help='Run multiplex.')
    parser.add_argument('--local', action='store_true',
                        default=False,
                        help='Run multiplex locally, or using SLURM.')

    args = parser.parse_args()

    args.master_file = os.path.abspath(args.master_file)

    dataset = SinglaDataset.from_master_file(args.master_file,
                                             make_out_path=False)

    start_time = time.time()
    trigger_path = os.path.join(dataset.output_path, args.pipeline_name)
    trigger_file = os.path.join(trigger_path, PROCESS_DONE_TRIGGER)

    while (time.time() - start_time) < global_config['report_wait_time_sec']:

        time.sleep(10)
        if os.path.exists(trigger_file):
            update_database(dataset, args.pipeline_name)

            cond = args.pipeline_name == global_config['multiplex_pipeline']
            if (args.multiplex and cond):
                multiplex_dataset = MultiplexDataset(
                                        master_file=args.master_file,
                                        local=args.local)

                success = multiplex_dataset.copy_files()
                if success and multiplex_dataset.run_condition():
                    multiplex_dataset.run()

            sys.exit()


def generate_report_files(report_path, verbose=True):

    os.makedirs(report_path, exist_ok=True)
    if verbose:
        print("Generating report in")
        print(f" {report_path} ")

    data_path = os.path.join(report_path, report_data_dir)
    os.makedirs(data_path, exist_ok=True)

    autoed_path = autoed.__path__[0]
    template_path = os.path.join(autoed_path, 'report/template')
    template_files = ['report.html', 'scripts.js', 'styles.css',
                      'server', 'misc.js', 'favicon.png']

    for file in template_files:
        source_path = os.path.join(template_path, file)

        if file == 'report.html' or file == 'server':
            destination_path = os.path.join(report_path, file)
        else:
            destination_path = os.path.join(data_path, file)

        shutil.copy(source_path, destination_path)

        if file == 'server':
            os.chmod(destination_path,
                     os.stat(destination_path).st_mode | 0o111)


def update_database(dataset, pipeline_name):

    from autoed.global_config import global_config
    from autoed.report.misc import (generate_report_files,
                                    update_database_for_dataset)
    from autoed.report.txt_report import generate_txt_report
    from autoed.constants import (report_dir,
                                  report_data_dir,
                                  database_json_file)

    ed_root_dir = global_config.ed_root_dir
    path = dataset.path
    report_path = r''

    # The report path is the same directory where
    # the data root is (e.g. ED directory). This assumes there is just one
    # data root directory in the path
    temp_list = path.split('/')
    for dir_name in temp_list:
        if dir_name != ed_root_dir:
            report_path += r'/' + dir_name
        else:
            break

    report_path = os.path.join(report_path, report_dir)
    report_data_path = os.path.join(report_path, report_data_dir)

    generate_report_files(report_path, verbose=False)
    update_database_for_dataset(dataset, report_data_path, pipeline_name)

    # Generate TXT output from JSON
    json_data_path = os.path.join(report_data_path, database_json_file)
    generate_txt_report(json_data_path, report_path)


def update_database_for_dataset(dataset, report_path, pipeline_name):
    """ Add dataset to database """

    database = JsonDatabase(report_path)
    database.load_data()

    parser = Xia2OutputParser(dataset, database)
    parser.add_to_database(pipeline_name)
