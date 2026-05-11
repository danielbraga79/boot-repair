import unittest
from pathlib import Path
from unittest.mock import patch

from core.analysis.utils import _device_name, _infer_disk_name, _normalize_mountpoints, _parse_mounts, _to_bool, _to_int


class TestUtils(unittest.TestCase):

    def test_device_name_with_dev_prefix(self):
        self.assertEqual(_device_name('/dev/sda'), '/dev/sda')
        self.assertEqual(_device_name('/dev/nvme0n1'), '/dev/nvme0n1')

    def test_device_name_without_dev_prefix(self):
        self.assertEqual(_device_name('sda'), '/dev/sda')
        self.assertEqual(_device_name('nvme0n1'), '/dev/nvme0n1')

    def test_device_name_stripped(self):
        self.assertEqual(_device_name('  /dev/sda  '), '/dev/sda')
        self.assertEqual(_device_name('  sda  '), '/dev/sda')

    def test_to_int_string_with_suffixes(self):
        self.assertEqual(_to_int('1G'), 1_000_000_000)
        self.assertEqual(_to_int('500M'), 500_000_000)
        self.assertEqual(_to_int('2K'), 2_000)
        self.assertEqual(_to_int('1.5G'), 1_500_000_000)

    def test_to_int_string_with_comma(self):
        self.assertEqual(_to_int('223,6G'), 223_600_000_000)

    def test_to_int_plain_number(self):
        self.assertEqual(_to_int('123'), 123)
        self.assertEqual(_to_int('0'), 0)

    def test_to_int_invalid(self):
        self.assertEqual(_to_int('invalid'), 0)
        self.assertEqual(_to_int(''), 0)
        self.assertEqual(_to_int(None), 0)
        self.assertEqual(_to_int([]), 0)

    def test_to_int_custom_default(self):
        self.assertEqual(_to_int('invalid', 42), 42)

    def test_to_bool_true_values(self):
        self.assertTrue(_to_bool(True))
        self.assertTrue(_to_bool(1))
        self.assertTrue(_to_bool(1.0))
        self.assertTrue(_to_bool('1'))
        self.assertTrue(_to_bool('true'))
        self.assertTrue(_to_bool('yes'))
        self.assertTrue(_to_bool('y'))
        self.assertTrue(_to_bool('on'))

    def test_to_bool_false_values(self):
        self.assertFalse(_to_bool(False))
        self.assertFalse(_to_bool(0))
        self.assertFalse(_to_bool(0.0))
        self.assertFalse(_to_bool('0'))
        self.assertFalse(_to_bool('false'))
        self.assertFalse(_to_bool('no'))
        self.assertFalse(_to_bool(''))
        self.assertFalse(_to_bool(None))
        self.assertFalse(_to_bool([]))

    def test_normalize_mountpoints_list(self):
        self.assertEqual(_normalize_mountpoints(['/mnt', '/boot']), '/mnt')
        self.assertEqual(_normalize_mountpoints(['', '/boot']), '/boot')
        self.assertEqual(_normalize_mountpoints(['', None, '/boot']), '/boot')
        self.assertEqual(_normalize_mountpoints([]), '')

    def test_normalize_mountpoints_string(self):
        self.assertEqual(_normalize_mountpoints('/mnt'), '/mnt')
        self.assertEqual(_normalize_mountpoints('  /mnt  '), '/mnt')
        self.assertEqual(_normalize_mountpoints(''), '')

    def test_normalize_mountpoints_other(self):
        self.assertEqual(_normalize_mountpoints(None), '')
        self.assertEqual(_normalize_mountpoints(123), '')

    def test_infer_disk_name_sata(self):
        self.assertEqual(_infer_disk_name('/dev/sda1'), '/dev/sda')
        self.assertEqual(_infer_disk_name('/dev/sdb2'), '/dev/sdb')

    def test_infer_disk_name_nvme(self):
        self.assertEqual(_infer_disk_name('/dev/nvme0n1p1'), '/dev/nvme0n1')
        self.assertEqual(_infer_disk_name('/dev/nvme1n2p3'), '/dev/nvme1n2')

    def test_infer_disk_name_no_partition(self):
        self.assertEqual(_infer_disk_name('/dev/sda'), '/dev/sda')
        self.assertEqual(_infer_disk_name('/dev/nvme0n1'), '/dev/nvme0n1')

    def test_infer_disk_name_no_dev_prefix(self):
        self.assertEqual(_infer_disk_name('sda1'), '')
        self.assertEqual(_infer_disk_name(''), '')

    @patch('core.analysis.utils.Path.read_text')
    def test_parse_mounts_success(self, mock_read):
        mock_read.return_value = '''/dev/sda1 / ext4 rw,relatime 0 0
/dev/sda2 /boot vfat ro,relatime 0 0
proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0
'''
        result = _parse_mounts()
        expected = (
            ('/dev/sda1', '/', False),
            ('/dev/sda2', '/boot', True),
            ('proc', '/proc', False),
        )
        self.assertEqual(result, expected)

    @patch('core.analysis.utils.Path.read_text')
    def test_parse_mounts_empty(self, mock_read):
        mock_read.return_value = ''
        self.assertEqual(_parse_mounts(), ())

    @patch('core.analysis.utils.Path.read_text')
    def test_parse_mounts_invalid_lines(self, mock_read):
        mock_read.return_value = '''invalid line
short line
/dev/sda1 / ext4
'''
        result = _parse_mounts()
        self.assertEqual(result, ())

    @patch('core.analysis.utils.Path.read_text')
    def test_parse_mounts_oserror(self, mock_read):
        mock_read.side_effect = OSError('No such file')
        self.assertEqual(_parse_mounts(), ())


if __name__ == '__main__':
    unittest.main()