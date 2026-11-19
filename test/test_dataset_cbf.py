import pytest                             # noqa: F401
import os
import autoed
from autoed.dataset_cbf import CBFDataset


@pytest.fixture(scope='session')
def cbf_dir():
    path = os.path.dirname(autoed.__path__[0])
    return os.path.join(path, 'test/data/ED/cbf_01/')


def test_find_datasets_groups_frames_into_one_dataset(cbf_dir):
    """Unlike Singla's master-file presence check, CBF discovery must
    collapse every numbered frame sharing a prefix onto a single
    dataset, not report one dataset per frame."""

    datasets = CBFDataset.find_datasets(cbf_dir)

    assert len(datasets) == 1
    assert datasets[0].dataset_name == 'Paracetamol_0062'


def test_search_and_update_data_files_finds_all_frames(cbf_dir):

    dataset = CBFDataset(cbf_dir, 'Paracetamol_0062')
    dataset.search_and_update_data_files()

    assert len(dataset.data_files) == 3
    assert dataset.data_files[0].endswith('Paracetamol_0062_0001.cbf')
    assert dataset.data_files[-1].endswith('Paracetamol_0062_0003.cbf')


def test_all_files_present_true_for_a_complete_sweep(cbf_dir):
    """CBF has no master/json/mdoc sidecar to check for - completeness
    comes from the frame count settling instead."""

    dataset = CBFDataset(cbf_dir, 'Paracetamol_0062')
    assert dataset.all_files_present() is True


def test_compute_beam_center_reads_header(cbf_dir):
    """Must not use Singla's h5py-based BeamCenterCalculator, which
    cannot open a '.cbf' file."""

    dataset = CBFDataset(cbf_dir, 'Paracetamol_0062')
    dataset.compute_beam_center()

    assert dataset.beam_center == (296.0, 291.0)


def test_fetch_metadata_reads_header(cbf_dir):

    dataset = CBFDataset(cbf_dir, 'Paracetamol_0062')
    success = dataset.fetch_metadata()

    assert success is True
    assert abs(dataset.metadata.wavelength - 0.02851) < 1.e-5
    assert abs(dataset.metadata.angle_increment - 0.5) < 1.e-5
    assert abs(dataset.metadata.start_angle + 30.0) < 1.e-5
    assert abs(dataset.metadata.detector_distance - 578.3) < 1.e-1


def test_to_nexus_is_a_noop(cbf_dir):
    """DIALS reads geometry straight from the CBF header - there is
    nothing to convert."""

    dataset = CBFDataset(cbf_dir, 'Paracetamol_0062')
    assert dataset.to_nexus() is True
    assert dataset.status == 'CONVERTED'
