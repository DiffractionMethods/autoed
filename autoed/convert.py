"""A wrapper for the nexgen package"""
import subprocess
import os

from autoed.utility.misc_functions import is_file_fully_written, overwrite_mask


def generate_nexus_file(dataset):
    """Generates Nexus file from the dataset files using nexgen"""

    dataset.logger.info(f"Overwriting mask in : {dataset.master_file}")
    overwrite_mask(dataset.master_file)
    dataset.logger.info(f"Mask overwritten in : {dataset.master_file}")

    phil_file = os.path.join(dataset.path, 'ED_Singla.phil')

    if not os.path.exists(phil_file):
        dataset.logger.info('Copying ED_Singl.phil')
        cmd = ['nexgen_phil get ED_Singla.phil -o ' + phil_file]
        subprocess.run(cmd, shell=True, text=True, capture_output=True)
    else:
        dataset.logger.info('ED_Singl.phil detected')

    if os.path.exists(dataset.nexgen_file):
        dataset.logger.info('Found existing nexus file')
        cmd = ['rm ' + dataset.nexgen_file]
        subprocess.run(cmd, shell=True, text=True, capture_output=True)
        dataset.logger.info('Old Nexus file removed')

    phil_written, _, _ = is_file_fully_written(phil_file, polling_interval=0.5)
    if not phil_written:
        dataset.logger.info('Conversion failed. Phil file not written')
        return 0

    data_file_pattern = dataset.base + r'_data_*.h5'
    metadata = dataset.metadata

    nex_cmd = 'ED_nexus singla-phil '
    nex_cmd += '%s ' % phil_file
    nex_cmd += r'input.datafiles=%s ' % data_file_pattern
    nex_cmd += 'goniometer.starts=%.0f,0,0,0 ' % metadata.start_angle
    nex_cmd += 'goniometer.increments=%.5f,0,0,0 ' % metadata.angle_increment
    nex_cmd += 'goniometer.vectors=0,-1,0,0,0,1,0,1,0,1,0,0 '
    nex_cmd += 'detector.starts=%f ' % metadata.detector_distance
    nex_cmd += 'beam.wavelength=%.10f ' % metadata.wavelength
    if dataset.beam_center:
        nex_cmd += 'detector.beam_center=%.2f,%.2f ' % dataset.beam_center
    nex_cmd += '-m %s ' % dataset.master_file

    # Remove EDnxs.log if it exists
    EDnxs_file = os.path.join(dataset.path, 'EDnxs.log')
    if os.path.exists(EDnxs_file):
        os.remove(EDnxs_file)

    dataset.logger.info('Running nexgen with: ' + nex_cmd)
    p = subprocess.run(nex_cmd, shell=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, cwd=dataset.path)

    if p.returncode != 0:
        dataset.logger.error('Failed to process data with nexgen')
        dataset.logger.error(p.stderr.decode(errors='replace'))
        dataset.status = 'CONVERSION_FAILED'
        return 0

    if p.stderr:
        dataset.logger.warning(p.stderr.decode(errors='replace'))

    dataset.logger.info('Created Nexus file ' + dataset.nexgen_file)
    dataset.status = 'CONVERTED'
    return 1
