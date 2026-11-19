import os
import sys
from autoed.constants import report_dir, report_data_dir, database_json_file
from autoed.report.json_database import JsonDatabase
from autoed.report.parser import Xia2OutputParser
from autoed.report.misc import generate_report_files
from autoed.report.txt_report import generate_txt_report
from autoed.global_config import global_config
import argparse


def run():
    """Generates the HTML report"""
    msg = 'Generates an HTML report for the given directory'
    parser = argparse.ArgumentParser(description=msg)
    parser.add_argument('watch_dir', type=str,
                        help='A directory from where to scrap the data.')
    parser.add_argument('report_path', type=str,
                        help='A path where to save the report.')
    args = parser.parse_args()

    watch_dir = os.path.abspath(args.watch_dir)
    report_path = os.path.abspath(args.report_path)
    report_full_path = os.path.join(report_path, report_dir)

    if not os.path.exists(watch_dir):
        print("Error: FileNotFound {watch_dir}.")
        print(" Can not generate HTML report.")
        print(" The directory from which to scrap the data does not exist")
        sys.exit()

    generate_report_files(report_full_path)
    generate_json_database(watch_dir, report_full_path)

    # Generate TXT output from JSON
    print("TXT report generated")
    json_data_path = os.path.join(report_full_path, report_data_dir)
    json_data_path = os.path.join(json_data_path, database_json_file)
    generate_txt_report(json_data_path, report_full_path)


def generate_json_database(path_to_watched_dir, report_path):
    """
    Goes through the watched directory recursively gathering all the datasets
    and then parses them into a single json file
    """

    datasets = gather_datasets(path_to_watched_dir)
    report_data_path = os.path.join(report_path, report_data_dir)
    database = JsonDatabase(report_data_path)

    database.load_data()

    defined_pipelines = global_config['defined_pipelines']

    n = len(datasets)
    for i, dataset in enumerate(datasets):
        print(f' Adding dataset [{i+1}/{n}]\r', end="")
        parser = Xia2OutputParser(dataset, database)
        for defined_pipeline in defined_pipelines:
            pipeline_name = defined_pipeline['pipeline_name']
            pipeline_type = defined_pipeline['type']
            if pipeline_type == 'xia2':
                parser.add_to_database(pipeline_name)
    print(f' Adding dataset [{i+1}/{n}]      ')
    print('HTML report generated')


def gather_datasets(dir_path):
    """ Given a directory path return all the Singla datasets in that path """
    from autoed.utility.filesystem import gather_master_files
    from autoed.dataset_singla import SinglaDataset

    datasets = []
    master_files = gather_master_files(dir_path)
    for master_file in master_files:
        basename = master_file[:-10]
        dataset = SinglaDataset.from_basename(basename, make_out_path=False)

        dataset.search_and_update_data_files()

        datasets.append(dataset)

    return datasets
