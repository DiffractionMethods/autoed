import time
import autoed
import os
import re
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler
from autoed.dataset_singla import SinglaDataset
from autoed.global_config import global_config
import logging
import argparse
from autoed import __version__


"""
A watchdog script that watches a directory for file changes.
The script checks, converts and processes the electron diffraction
data if present.

Run with:
autoed_watch directory_name
"""


def main():

    # By default, all the arguments are set to None, so we can test which
    # argument was provided. If an argument was not provided, its value is set
    # from the default configuration file, or from a user configuration file.
    # If an argument is provided, it overwrites the one in the configuration
    # file.

    msg = 'Watchdog script for monitoring filesystem changes'
    parser = argparse.ArgumentParser(description=msg)
    parser.add_argument('--inotify', '-i', action='store_true', default=None,
                        help='Run watchdog with inotify.')

    hmsg = "Sleep time between filesystem checks (in seconds).\n"
    parser.add_argument('--sleep_time', '-t', type=float, default=None,
                        help=hmsg)

    msg = 'Run the watchdog script without running xia2 / DIALS (for testing).'
    parser.add_argument('--dummy', action='store_true', default=None,
                        help=msg)

    msg = 'Same as dummy, but do not overwrite default config params.'
    parser.add_argument('--test', action='store_true', default=None,
                        help=msg)

    msg = 'If used, it runs xia2 and DIALS processing locally with bash, '
    msg += 'instead of submitting the job request to cluster using SLURM.'
    parser.add_argument('--local', action='store_true', default=None,
                        help=msg)

    msg = 'A directory to store the AutoED log file.'
    parser.add_argument('--log-dir', type=str, default=None,
                        help=msg)

    parser.add_argument('dirname', nargs='?', default=None,
                        help='Name of the directory to watch')

    args = parser.parse_args()

    if not args.dirname:
        msg = 'autoed_watch requires a single argument'
        msg += ' (watch directory)'
        raise IOError(msg)

    input_dir = args.dirname

    watch_path = os.path.abspath(input_dir)
    if not os.path.exists(watch_path):
        msg = f'Path {watch_path} does not exist.'
        raise FileNotFoundError(msg)

    log_str1 = global_config.overwrite_from_local_config()
    log_str2 = global_config.overwrite_from_commandline(args)

    if not global_config.log_dir:
        global_config.log_dir = watch_path

    if not os.path.exists(global_config.log_dir):
        msg = "Error! Global log directory "
        msg += f"'{global_config.log_dir}' does not exist."
        raise FileNotFoundError(msg)

    processing_script = os.path.join(autoed.__path__[0], 'process.py')

    watch_logger = set_watch_logger(global_config.log_dir)

    if log_str1 != '':
        watch_logger.info(log_str1)

    if log_str2 != '':
        watch_logger.info(log_str2)

    global_config.print_to_log(watch_logger)

    event_handler = DirectoryHandler(watch_path,
                                     processing_script,
                                     watch_logger,
                                     global_config)

    if args.inotify:
        observer = Observer()
    else:
        observer = PollingObserver(timeout=global_config.sleep_time)

    observer.schedule(event_handler, watch_path, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(global_config.sleep_time)

    except KeyboardInterrupt as e:
        watch_logger.exception(str(e))
        observer.stop()
    except Exception as e:
        watch_logger.exception(str(e))
        observer.stop()
    observer.join()


class DirectoryHandler(FileSystemEventHandler):

    def __init__(self, watch_path, script, logger, global_config):

        """
        Parameters
        ----------
        watch_path : Path
            The path of the directory to be watched.
        script : Path
            The path to the processing script used to convert and process data.
        logger : logger object
        global_config: extended dict object
            Keeps the values of all global variables.
        """

        self.watch_path = watch_path
        self.status_file = os.path.join(watch_path, '.autoed_status.txt')
        self.dataset_names = set()
        self.datasets = dict()
        self.queue = dict()
        self.logger = logger
        self.global_config = global_config

        self.script = script
        self.last_triggered = 0
        self.last_detected = dict()

    def on_created(self, event):

        try:
            info = self.logger.info

            if not event.is_directory:

                trigger_file = self.global_config.trigger_file
                if re.match(rf".*\{trigger_file}$", event.src_path):

                    info('Detected trigger file: %s' % event.src_path)

                    dataset = None
                    basename = None

                    # Process only events that happened in ED directory
                    ed_root = global_config['ed_root_dir']
                    if ed_root in event.src_path.split(os.path.sep):

                        dir_name = os.path.dirname(event.src_path)

                        discovered = SinglaDataset.find_datasets(
                            dir_name, make_out_path=False)

                        for discovered_dataset in discovered:
                            basename = discovered_dataset.base

                            if (basename not in self.dataset_names):
                                self.dataset_names.add(basename)
                                dataset = SinglaDataset.from_basename(basename)
                                msg = 'AutoED global log file at '
                                msg += f"'{global_config.log_dir}'."
                                dataset.logger.info(msg)
                                dataset.search_and_update_data_files()

                                # We do not want to run processing scripts
                                # if either this is a test, or a dummy run
                                run_dummy = (self.global_config.test or
                                             self.global_config.dummy)
                                dataset.dummy = run_dummy
                                self.datasets[dataset.base] = dataset
                            else:
                                dataset = self.datasets[basename]

                            dataset.update_processed()
                            msg = 'Found dataset: %s'
                            info(msg % dataset.base)

                            if not dataset.processed:
                                if dataset.all_files_present():
                                    msg = 'All files present: %s'
                                    info(msg % dataset.base)
                                    info('Processing: %s' % dataset.base)
                                    gc = self.global_config
                                    success = dataset.process(gc)
                                    base = dataset.base
                                    if success:
                                        ms = f"Processed: {base}"
                                        info(ms)
                                    else:
                                        ms = f"Failed to process: {base}"
                                        info(ms)
                                else:
                                    msg = 'Not all files present, ignoring: %s'
                                    info(msg % dataset.base)
                            else:
                                msg = 'Ignoring trigger. '
                                msg += 'Data processed recently: %s %s '
                                t1 = dataset.last_processed_time
                                st = time.strftime('%Y-%m-%d %H:%M:%S',
                                                   time.localtime(t1))
                                info(msg % (st, dataset.base))
                    else:
                        msg = 'Ignoring trigger, no ED directory: %s'
                        self.logger.info(msg % event.src_path)
        except Exception as e:
            self.logger.exception(str(e))

    def on_modified(self, event):
        self.on_created(event)


def set_watch_logger(watch_path):

    auto_logger = logging.getLogger(__name__)
    auto_logger.setLevel(logging.DEBUG)

    autoed_log_path = os.path.join(watch_path, 'autoed_watch.log')
    file_handler = logging.FileHandler(autoed_log_path, mode='a')
    file_handler.setLevel(logging.DEBUG)
    fmt = '%(asctime)s.%(msecs)03d %(levelname)s - %(message)s'
    formatter = logging.Formatter(fmt, datefmt='%d-%m-%Y %H:%M:%S')

    file_handler.setFormatter(formatter)
    file_handler.auto_flush = True

    auto_logger.addHandler(file_handler)

    auto_logger.info(40*'=')
    auto_logger.info('  AutoED')
    auto_logger.info(f'  version: v{__version__} ')
    auto_logger.info(40*'=')

    return auto_logger


if __name__ == "__main__":
    main()
