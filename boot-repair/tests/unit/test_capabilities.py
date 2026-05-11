import unittest
from unittest.mock import patch

from core.capabilities import get_capabilities, pyudev_available, lsblk_available, lsblk_json_available


class TestCapabilities(unittest.TestCase):

    def test_pyudev_available(self):
        # This depends on environment
        result = pyudev_available()
        self.assertIsInstance(result, bool)

    def test_lsblk_available(self):
        # Just check it returns bool
        result = lsblk_available()
        self.assertIsInstance(result, bool)

    def test_lsblk_json_available(self):
        # Just check it returns bool
        result = lsblk_json_available()
        self.assertIsInstance(result, bool)

    def test_get_capabilities(self):
        caps = get_capabilities()
        self.assertIsInstance(caps, dict)
        expected_keys = {
            'pyudev', 'lsblk', 'lsblk_json', 'parted', 'efibootmgr', 'grub_install',
            'mkinitcpio', 'dracut', 'update_initramfs', 'blkid', 'findmnt',
            'fsck_ext4', 'xfs_repair', 'btrfs_check', 'fsck_fat'
        }
        self.assertEqual(set(caps.keys()), expected_keys)
        for value in caps.values():
            self.assertIsInstance(value, bool)


if __name__ == '__main__':
    unittest.main()