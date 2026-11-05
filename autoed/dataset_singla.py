"""Define Singla dataset class"""
import os
import re
import traceback
from autoed.dataset_abc import DatasetBase
from autoed.global_config import global_config
from autoed.beam_position.beam_center import BeamCenterCalculator
from autoed.utility.misc_functions import is_file_fully_written
from autoed.metadata import Metadata


class SinglaDataset(DatasetBase):           # pylint: disable=R0902
    """A class to keep all data relevant to a single Singla detector
    dataset"""

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
        super().__init__(path, dataset_name, make_out_path=make_out_path)
        self.master_file = self.base + '_master.h5'
        self.nexgen_file = self.base + '.nxs'
        self.json_file = self.base + '.json'

    @classmethod
    def from_master_file(cls, master_file, make_out_path=True):
        path = os.path.dirname(master_file)
        dataset_name = os.path.basename(master_file)
        dataset_name = dataset_name.replace('_master.h5', '')
        return cls(path, dataset_name, make_out_path=make_out_path)

    def search_and_update_data_files(self):

        data_files = []
        pattern = self.base + r'\_data_\d{6}\.h5'
        for root, dirs, files in os.walk(self.path):
            for file in files:
                file_path = os.path.join(root, file)
                if re.match(pattern, file_path):
                    data_files.append(file_path)
        self.data_files = data_files

    def all_files_present(self):
        """Checks if all files for the current dataset are present"""

        data_exists = len(self.data_files) > 0
        files_exist = (os.path.exists(self.master_file) and
                       os.path.exists(self.log_file) and
                       os.path.exists(self.mdoc_file) and
                       os.path.exists(self.patch_file))

        new_files_exist = (os.path.exists(self.master_file) and
                           os.path.exists(self.json_file))

        if (new_files_exist and data_exists):
            self.logger.info("Detected data and JSON metadata")
            return True
        elif (files_exist and data_exists):
            self.logger.info("Detected data and TXT metadata")

            con_data = True
            for data_file in self.data_files:

                self.logger.info('Waiting for data to be written: %s'
                                 % data_file)
                con_temp, sd, td = is_file_fully_written(data_file,
                                                         timeout=1200)
                if con_temp:
                    self.logger.info('Data file size stable: %d %s'
                                     % (sd, data_file))
                else:
                    self.logger.info('Data file size test failed %d %s'
                                     % (sd, data_file))
                con_data = con_data and con_temp

            self.logger.info('Waiting for master file: %s'
                             % self.master_file)
            con1, s1, t1 = is_file_fully_written(self.master_file,
                                                 timeout=180)
            if con1:
                self.logger.info('Master file size stable: %d %s'
                                 % (s1, self.master_file))
            else:
                self.logger.info('Master file size test failed: %d %s'
                                 % (s1, self.master_file))

            self.logger.info('Waiting for log file: %s'
                             % self.log_file)
            con2, s2, t2 = is_file_fully_written(self.log_file)
            if con2:
                self.logger.info('Log file size stable: %d %s'
                                 % (s2, self.log_file))
            else:
                self.logger.info('Log file size test failed: %d %s'
                                 % (s2, self.log_file))

            self.logger.info('Waiting for mdoc file: %s'
                             % self.mdoc_file)
            con3, s3, t3 = is_file_fully_written(self.mdoc_file)
            if con3:
                self.logger.info('Mdoc file size stable: %d %s'
                                 % (s3, self.mdoc_file))
            else:
                self.logger.info('Mdoc file size test failed: %d %s'
                                 % (s3, self.mdoc_file))

            self.logger.info('Waiting for Patch file: %s'
                             % self.patch_file)
            con4, s4, t4 = is_file_fully_written(self.patch_file)
            if con4:
                self.logger.info('PatchMaster.sh file size stable: %d %s'
                                 % (s4, self.patch_file))
            else:
                self.logger.info('PatchMaster.sh file size test failed: %d %s'
                                 % (s4, self.patch_file))
            if con1 and con2 and con3 and con4 and con_data:
                self.present_lock = True
            return con1 and con2 and con3 and con4 and con_data
        else:
            self.logger.info('Dataset not complete %s' % self.base)
            return False

    def compute_beam_center(self):

        if len(self.data_files) > 0:

            calc = BeamCenterCalculator(self.data_files[0])

            if calc.problem_reading:
                x = 514
                y = 531
                msg = f"Problem reading data file {self.data_files[0]}.\n"
                msg += "Setting the beam position to default (514, 531)."
                self.logger.warning(msg)
                self.beam_center = (x, y)
                return

            ed_root = global_config.ed_root_dir
            try:
                x, y = calc.center_from_mixed(every=50,
                                              plot_file=self.beam_figure,
                                              title=self.beam_figure,
                                              ed_root_dir=ed_root)
            except Exception:
                full_traceback = traceback.format_exc()
                msg = "Failed to compute the beam center.\n"
                msg += f"{full_traceback}\n"
                msg += "Setting the beam position to default (514, 531)."
                self.logger.warning(msg)
                x = 514
                y = 531

            if not x:
                msg = 'Beam position along x is None. Setting it to 514 px'
                self.logger.warning(msg)
                x = 514
            if not y:
                msg = 'Beam position along y is None. Setting it to 531 px'
                self.logger.error(msg)
                y = 531
            self.beam_center = (x, y)
            calc.file.close()

        return

    def fetch_metadata(self):

        metadata = Metadata()
        new_files_exist = (os.path.exists(self.master_file) and
                           os.path.exists(self.json_file))

        # First try to fetch metadata from JSON format
        success_json = False
        if new_files_exist:
            success_json = metadata.from_json(self)

        # If fetching from JSON fails, try with the old (textual) format
        if not success_json:
            self.logger.error('Failed to fetch metadata from JSON')
            self.logger.info('Trying to fetch metadata from txt')
            success_txt = metadata.from_txt(self)
            if not success_txt:
                self.logger.error('Failed to fetch metadata from txt files')
                return False

        self.metadata = metadata
        return True
