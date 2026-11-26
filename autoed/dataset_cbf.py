"""Define CBF dataset class"""
import os
import re
import time

from autoed.dataset_abc import DatasetBase
from autoed.utility.misc_functions import is_file_fully_written
from autoed.metadata import Metadata


FRAME_PATTERN = re.compile(r'^(.+)_(\d+)\.cbf$')

# Header-key aliases and unit conversion for the fields CBF headers can
# supply. Canonical units match autoed.metadata.Metadata: wavelength in
# Angstrom, distances in mm, angles in degrees.
_HEADER_KEYS = {
    'wavelength': 'Wavelength',
    'detector_distance': 'Detector_distance',
    'start_angle': 'Start_angle',
    'angle_increment': 'Angle_increment',
}

_UNIT_FACTORS = {
    'wavelength': {'a': 1.0, 'angstrom': 1.0},
    'detector_distance': {'m': 1000.0, 'mm': 1.0},
    'start_angle': {'deg': 1.0, 'deg.': 1.0},
    'angle_increment': {'deg': 1.0, 'deg.': 1.0},
}


class CBFDataset(DatasetBase):           # pylint: disable=R0902
    """A class to keep all data relevant to a single CBF detector dataset:
    sequentially numbered '.cbf' frames sharing a filename prefix, with no
    master file and no JSON/txt sidecars. DIALS reads geometry straight
    from the CBF header, so unlike Singla there is no Nexus conversion
    step and no separate beam-center algorithm to run.
    """

    @classmethod
    def find_datasets(cls, folder, make_out_path=True):
        """Recursively find CBF datasets under folder.

        Unlike Singla's master-file presence check (one sentinel file =
        one dataset), a CBF dataset has no single sentinel file: it IS a
        cluster of numbered frames sharing a filename prefix, so discovery
        is a grouping problem - every frame matching '{base}_{number}.cbf'
        is collapsed onto its base name. Returns ready-to-use dataset
        objects, one per discovered base name.
        """
        basenames = []
        seen = set()
        for root, dirs, files in os.walk(folder):
            for filename in files:
                match = FRAME_PATTERN.match(filename)
                if not match:
                    continue
                base = os.path.join(root, match.group(1))
                if base not in seen:
                    seen.add(base)
                    basenames.append(base)
        return [cls.from_basename(b, make_out_path=make_out_path)
               for b in sorted(basenames)]

    def search_and_update_data_files(self):
        """Collect the frames belonging to this dataset (sorted)"""

        pattern = re.compile(r'^' + re.escape(self.dataset_name)
                             + r'_(\d+)\.cbf$')
        data_files = []
        for root, dirs, files in os.walk(self.path):
            for filename in files:
                if pattern.match(filename):
                    data_files.append(os.path.join(root, filename))
        self.data_files = sorted(data_files)

    def all_files_present(self):
        """Checks if the frame sequence has finished being written.

        CBF datasets carry no manifest declaring how many frames to
        expect, so completeness (unlike Singla's fixed set of named
        sidecar files) is judged by the frame count settling, plus a
        size-stability check on the newest frame.
        """

        self.search_and_update_data_files()

        if not self.data_files:
            self.logger.info('Dataset not complete %s' % self.base)
            return False

        if not self._frame_count_stable():
            self.logger.info('Frame count still changing: %s' % self.base)
            return False

        newest_frame = self.data_files[-1]
        self.logger.info('Waiting for last frame to be written: %s'
                         % newest_frame)
        written, size, _ = is_file_fully_written(newest_frame)
        if written:
            self.logger.info('Last frame size stable: %d %s'
                             % (size, newest_frame))
            self.logger.info('Detected %d frames for dataset %s'
                             % (len(self.data_files), self.base))
            self.present_lock = True
            return True

        self.logger.info('Last frame size test failed: %s' % newest_frame)
        return False

    def _frame_count_stable(self, polling_interval=0.5, stable_checks=3,
                            timeout=120):
        """True once the number of frames stops growing"""

        previous_count = len(self.data_files)
        stable = 0
        start_time = time.time()

        while time.time() - start_time < timeout:
            time.sleep(polling_interval)
            self.search_and_update_data_files()
            count = len(self.data_files)
            if count == previous_count:
                stable += 1
                if stable >= stable_checks:
                    return True
            else:
                stable = 0
                previous_count = count
        return False

    def compute_beam_center(self):
        """Read the beam center straight from the first frame's CBF
        header. Singla's h5py-based peak-finding algorithm
        (BeamCenterCalculator) cannot open a '.cbf' file, so this is a
        format-specific implementation, not a reuse of that one."""

        x, y = 514, 531
        header = self._read_header()
        if header is not None:
            beam_xy = header.get('Beam_xy')
            parsed = _parse_beam_xy(beam_xy) if beam_xy else None
            if parsed:
                x, y = parsed
            else:
                msg = "No usable 'Beam_xy' in CBF header for "
                msg += f"{self.data_files[0]}. Setting default (514, 531)."
                self.logger.warning(msg)
        self.beam_center = (x, y)

    def fetch_metadata(self):
        """Read geometry metadata straight from the first frame's CBF
        header - there is no JSON/txt sidecar for this format."""

        header = self._read_header()
        if header is None:
            return False

        metadata = Metadata()
        for field, header_key in _HEADER_KEYS.items():
            raw_value = header.get(header_key)
            if raw_value is None:
                msg = f"Header key '{header_key}' not found in "
                msg += f"{self.data_files[0]}"
                self.logger.warning(msg)
                continue
            value = _convert_to_canonical(field, raw_value)
            if value is None:
                msg = f"Could not parse header value for '{field}': "
                msg += f"'{raw_value}'"
                self.logger.warning(msg)
                continue
            metadata[field] = value
            self.logger.info(f"  {field}: {value} (from '{raw_value}')")

        if metadata.wavelength is None:
            self.logger.error('Failed to read wavelength from CBF header')
            return False

        self.metadata = metadata
        return True

    def to_nexus(self):
        """DIALS reads geometry straight from the CBF header - no
        conversion step is needed."""
        self.status = 'CONVERTED'
        return True

    def _read_header(self):
        """Return the parsed header of the first frame, or None on
        failure"""

        import fabio

        if not self.data_files:
            self.search_and_update_data_files()

        if not self.data_files:
            self.logger.error('No CBF frames to read metadata from')
            return None

        first_frame = self.data_files[0]
        try:
            fabio_header = fabio.open(first_frame).header
        except Exception as err:
            self.logger.error(f"fabio failed to read '{first_frame}': {err}")
            return None

        return _parse_pilatus_header(fabio_header)


def _parse_pilatus_header(fabio_header):
    """Flatten a PILATUS-convention CBF header's '# Key value unit' lines
    (held in '_array_data.header_contents') into a flat dict"""

    header = {}
    contents = fabio_header.get('_array_data.header_contents', '')
    for line in contents.splitlines():
        line = line.strip().lstrip('#').strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            header[parts[0].rstrip(':')] = parts[1].strip()
        else:
            header[parts[0]] = ''
    return header


def _convert_to_canonical(field, raw_value):
    """Parse a 'value [unit]' header string into the field's canonical
    unit. Returns None if the value (or a required unit token) cannot be
    parsed."""

    tokens = str(raw_value).split()
    if not tokens:
        return None

    try:
        value = float(tokens[0])
    except ValueError:
        return None

    factors = _UNIT_FACTORS.get(field, {})
    if len(tokens) > 1:
        unit = tokens[1].lower()
        if unit not in factors:
            return None
        return value * factors[unit]

    return value


def _parse_beam_xy(raw_value):
    """Parse a Beam_xy header entry like '(296.00, 291.00) pixels'"""

    numbers = re.findall(r'[-+]?\d+\.?\d*', str(raw_value))
    if len(numbers) >= 2:
        return (float(numbers[0]), float(numbers[1]))
    return None
