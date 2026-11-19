import sys
import os
import argparse
from autoed.dataset_singla import SinglaDataset
from autoed.utility.filesystem import gather_master_files
from autoed.global_config import global_config

global_config.overwrite_from_local_config()

def main():

    msg = 'Script for automatic processing of existing Singla data'
    parser = argparse.ArgumentParser(description=msg)
    parser.add_argument('dirname', nargs='?', default=None,
                        help='Name of the directory to process')
    hmsg = 'Do processing even when nexgen file already exists'
    parser.add_argument('-f', '--force',  action='store_true',
                        default=False,
                        help=hmsg)

    args = parser.parse_args()

    if args.dirname:
        process_dir(args.dirname, args.force)
    else:
        parser.print_help()
        sys.exit(1)


def process_dir(dir_name, force=False):
    """The function to search a directory recursively,
    convert all unprocessed files to nexgen and process
    them with xia2
    """

    dir_path = os.path.abspath(dir_name)

    if not os.path.exists(dir_path):
        print("Directory %s does not exist" % dir_path)
        return
    if not os.path.isdir(dir_path):
        print('%s is not a directory' % dir_path)

    # Search for any master files
    master_files = gather_master_files(dir_path)
    for master_file in master_files:
        basename = master_file[:-10]
        dataset = SinglaDataset.from_basename(basename)

        dataset.search_and_update_data_files()

        if dataset.all_files_present():

            if force:
                dataset.set_logger()
                print('Processing ', dataset.base)
                dataset.process(global_config)
            else:
                if not os.path.exists(dataset.nexgen_file):
                    dataset.set_logger()
                    print('Processing ', dataset.base)
                    dataset.process(global_config)
                else:
                    print('Ignoring. Nexgen file exist in ',
                          dataset.base)


if __name__ == '__main__':
    main()
