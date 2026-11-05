"""Define the abstract base class for datasets"""
import os
import logging
import time
from abc import ABC, abstractmethod
from autoed.constants import slurm_file
from autoed.global_config import global_config
from autoed.convert import generate_nexus_file
from autoed.process.pipeline import run_processing_pipelines
from autoed.utility.misc_functions import replace_dir
from autoed.process.plot_spots import plot_spots_from_dataset


class DatasetBase(ABC):
    """Abstract base class for datasets. Subclasses implement the
    detector-specific pieces: how data files are found, which files
    must be present, how the beam center is computed, and how
    metadata is fetched.
    """

    def __init__(self, path, dataset_name, make_out_path=True):
        """
        path : Path
            Path of the dataset.
        dataset_name : str
            Name of the dataset. Usually, if given a master file
            'abc_master.h5', the dataset will have the name 'abc'.
        make_out_path: boolean
            If True, the AutoED will create a path in the processed
            directory, and the log file in the data directory.
        """

        self.path = path
        self.dataset_name = dataset_name
        self.base = os.path.join(path, dataset_name)
        self.log_file = self.base + '.log'
        self.autoed_log_file = self.base + '.autoed.log'
        self.mdoc_file = self.base + '.mrc.mdoc'
        self.patch_file = os.path.join(self.path, 'PatchMaster.sh')
        self.beam_figure = os.path.join(self.path, 'beam_position.png')
        self.spots_figure = os.path.join(self.path, 'spots.png')

        in_path = os.path.dirname(self.base)
        out_path = replace_dir(in_path, global_config.ed_root_dir,
                               global_config.processed_dir)

        # We use dataset object in report generator. We do not want
        # to create output paths or write logs when generating reports.
        # Also, the report generation would fail if used by someone without
        # write permissions in out_path.
        if make_out_path:
            os.makedirs(out_path, exist_ok=True)
            self.set_logger()

        self.output_path = out_path
        self.slurm_file = os.path.join(out_path, slurm_file)
        self.status = 'NEW'
        self.beam_center = None  # this needs tweaking
        self.present_lock = False
        self.processed = False
        self.last_processed_time = 0
        self.dummy = None
        self.data_files = []
        self.metadata = None

    @classmethod
    def from_basename(cls, basename, make_out_path=True):
        path = os.path.dirname(basename)
        dataset_name = os.path.basename(basename)
        return cls(path, dataset_name, make_out_path=make_out_path)

    def set_logger(self, clear=True):

        self.logger = logging.getLogger(self.base)
        self.logger.setLevel(logging.DEBUG)

        if clear:          # Clear the log file if it exists
            with open(self.autoed_log_file, 'w'):
                pass

        file_handler = logging.FileHandler(self.autoed_log_file)

        fmt = '%(asctime)s.%(msecs)03d %(levelname)s - %(message)s'
        formatter = logging.Formatter(fmt, datefmt='%d-%m-%Y %H:%M:%S')
        file_handler.setFormatter(formatter)

        file_handler.setLevel(logging.DEBUG)

        self.logger.addHandler(file_handler)

    def update_processed(self):
        """
        AutoED can process a dataset again if we want. If data is sitting
        for say 5 min after being processed, it should be possible to
        reprocess it again.
        """
        time_diff = time.time() - self.last_processed_time
        if time_diff > 300:
            self.processed = False
        else:
            msg = 'Detected trigger file, but dataset processed recently.'
            msg = 'You have to wait 5 min to process again.'
            self.logger.info(msg)

    @abstractmethod
    def search_and_update_data_files(self):
        """Populate self.data_files with this sweep's raw data files."""

    @abstractmethod
    def all_files_present(self):
        """Return True once every file required to process this dataset
        exists and is fully written."""

    @abstractmethod
    def compute_beam_center(self):
        """Compute and set self.beam_center for this dataset."""

    @abstractmethod
    def fetch_metadata(self):
        """Populate self.metadata. Return True on success, False
        otherwise."""

    def process(self, global_config):

        if not self.processed:
            self.processed = True
            if global_config.plot_spots:
                # added to reflect change to global_config
                plot_spots_from_dataset(self)

            if global_config.determine_beam and not self.beam_center:
                msg = f"Computing the beam center for {self.dataset_name}"
                self.logger.info(msg)

                # Will write the default if it fails to compute
                self.compute_beam_center()

                msg = f"Beam center for {self.dataset_name}"
                msg += ' = (%.2f, %.2f) ' % self.beam_center
                self.logger.info(msg)

            success_metadata = self.fetch_metadata()
            if not success_metadata:
                msg = 'Failed to fetch metadata from JSON and TXT.\n'
                msg += 'No conversion/processing'
                self.logger.error(msg)
                return False
            else:
                success = generate_nexus_file(self)
                if success:
                    os.makedirs(self.output_path, exist_ok=True)
                    run_processing_pipelines(self, global_config.local)
                    self.last_processed_time = time.time()

                    return True
                else:
                    msg = 'Failed to generate nexus file'
                    self.logger.error(msg)
                    self.last_processed_time = time.time()
                    return False
        return False
