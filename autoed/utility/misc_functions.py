""" Miscellaneous function used in other parts of the code """
from __future__ import annotations
from typing import Union
import re
import h5py
import os
import numpy as np
import time


import autoed


basic_type = Union[float, int, str]


def scrap(input_file: str,
          variable_name: str,
          default_type: basic_type = None,
          default_value: basic_type = None,
          ) -> basic_type:
    """
    Read the `input_file` and return a value of the first line that matches a
    pattern `var_name = value`

    Parameters
    ----------
    input_file : str
        Full path of the textual file from which to scrap data.
    variable_name : str
        The name of the variable we want to scrap from the text file.
    default_type : Union[float, int, str]
        If the function finds the matching line, the resulting value will be
        converted to this type.
    default_value : Union[float, int, str]
        Return this value if the function fails to scrap the value from the
        input file (or the conversion to default_type fails.

    Returns
    -------
    success : boolean
        True if value was successfully read from the `input_file`, False if
        scrapping failed and `default_value` was returned.
    value : Union[float, int, str]
        The value of the variable `variable_name` from the `input_file` (or the
        `default_value`.
    """

    pattern = variable_name + r'\s*=\s*(.*)'
    match_line = None

    success = True

    try:

        if default_type not in (str, float, int):
            raise TypeError

        with open(input_file, 'r') as file:
            for line in file:
                if re.match(pattern, line):
                    match_line = line.strip()
                    break
        pattern = r'.*\s*=\s*(.*)$'
        value = re.search(pattern, match_line).group(1)
        value = default_type(value)

    except (FileNotFoundError, ValueError, TypeError):

        success = False
        value = default_value

    return success, value


def get_detector_distance(path):
    """Read detector distance from PatchMaster.sh"""

    pattern = r'detector.starts=(\d+(\.\d*)?)'
    distance = None
    with open(path, 'r') as file:
        for line in file:
            ln_match = re.search(pattern, line.strip())
            if ln_match:
                distance = float(ln_match.group(1))
                break
    return distance


def overwrite_mask(filename):

    """Given a HDF5 file, overwrite the pixel mask"""

    while True:
        try:
            with h5py.File(filename, 'r+') as file:

                src = '/entry/instrument/detector/detectorSpecific/'
                src += 'pixel_mask'
                pixel_mask = file[src]

                mask_path = 'data/singla_mask.npz'
                mask_path = os.path.join(autoed.__path__[0], mask_path)
                data = np.load(mask_path)
                mask = data['mask']
                pixel_mask[...] = mask
                break

        except OSError:
            time.sleep(1)

        except KeyError:
            break


def electron_wavelength(energy_kev):
    """Converts electron energy in keV into wavelength in Angstroms"""

    from math import sqrt
    mass_e = 510998.9461  # in eV
    h = 4.135667696e-15   # Planck's constant eV*s
    c = 299792458         # Speed of light m/s

    energy = energy_kev * 1000
    wavelength_m = h*c/sqrt(energy**2 + 2*mass_e*energy)
    wavelength_angs = wavelength_m * 1e10

    return wavelength_angs


def replace_dir(path, old_name, new_name):
    """Replace a directory name in a path """
    components = path.split(os.path.sep)

    for i, component in enumerate(components):

        if component == old_name:
            components[i] = new_name
            break

    new_path = os.path.join('/', *components)
    return new_path


def is_file_fully_written(filename,
                          polling_interval=0.05,
                          timeout=60):
    """
    Check if textual file is fully written by monitoring its size.

    Parameters:
    - filename: The name of the file to check.
    - polling_interval: Time interval (in seconds) between size checks.
    - timeout: Maximum time (in seconds) to wait for the file to stabilize.

    Returns:
    - True if the file size remains constant for the specified duration,
      False otherwise.
    """

    start_time = time.time()
    previous_size = None
    size = None
    wait_time = time.time() - start_time

    while time.time() - start_time < timeout:

        try:
            size = os.path.getsize(filename)
            wait_time = time.time() - start_time

            c1 = previous_size is not None
            c3 = size == previous_size
            if c1 and c3:
                if not size == 0:
                    return True, size, wait_time  # Size remains constant

            previous_size = size

        except FileNotFoundError:
            pass  # File might not exist yet, continue checking

        time.sleep(polling_interval)

    return False, size, time.time() - start_time
