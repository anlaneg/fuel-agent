# Copyright 2014 Mirantis, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock
import os
import signal

from oslo.config import cfg
from oslotest import base as test_base

from fuel_agent import errors
from fuel_agent import manager
from fuel_agent import objects
from fuel_agent.objects import partition
from fuel_agent.tests import test_nailgun
from fuel_agent.utils import artifact as au
from fuel_agent.utils import fs as fu
from fuel_agent.utils import hardware as hu
from fuel_agent.utils import lvm as lu
from fuel_agent.utils import md as mu
from fuel_agent.utils import partition as pu
from fuel_agent.utils import utils

CONF = cfg.CONF


class TestManager(test_base.BaseTestCase):

    @mock.patch('yaml.load')
    @mock.patch.object(utils, 'init_http_request')
    @mock.patch.object(hu, 'list_block_devices')
    def setUp(self, mock_lbd, mock_http, mock_yaml):
        super(TestManager, self).setUp()
        mock_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_SAMPLE
        self.mgr = manager.Manager(test_nailgun.PROVISION_SAMPLE_DATA)

    @mock.patch('fuel_agent.manager.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.manager.gu', create=True)
    @mock.patch('fuel_agent.manager.utils', create=True)
    @mock.patch.object(manager.Manager, 'mount_target')
    @mock.patch.object(manager.Manager, 'umount_target')
    def test_do_bootloader_grub1(self, mock_umount, mock_mount, mock_utils,
                                 mock_gu, mock_open):
        # actually covers only grub1 related logic
        mock_utils.execute.return_value = ('fake_UUID\n', None)
        mock_gu.guess_initrd.return_value = 'guessed_initrd'
        mock_gu.guess_kernel.return_value = 'guessed_kernel'
        mock_gu.guess_grub_version.return_value = 1
        self.mgr.do_bootloader()
        mock_gu.guess_grub_version.assert_called_once_with(
            chroot='/tmp/target')
        mock_gu.grub1_cfg.assert_called_once_with(
            kernel_params=' console=ttyS0,9600 console=tty0 rootdelay=90 '
                          'nomodeset root=UUID=fake_UUID ',
            initrd='guessed_initrd',
            chroot='/tmp/target',
            kernel='guessed_kernel')
        mock_gu.grub1_install.assert_called_once_with(
            ['/dev/sda', '/dev/sdb', '/dev/sdc'],
            '/dev/sda3', chroot='/tmp/target')
        self.assertFalse(mock_gu.grub2_cfg.called)
        self.assertFalse(mock_gu.grub2_install.called)

    @mock.patch('fuel_agent.manager.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.manager.gu', create=True)
    @mock.patch('fuel_agent.manager.utils', create=True)
    @mock.patch.object(manager.Manager, 'mount_target')
    @mock.patch.object(manager.Manager, 'umount_target')
    def test_do_bootloader_grub2(self, mock_umount, mock_mount, mock_utils,
                                 mock_gu, mock_open):
        # actually covers only grub2 related logic
        mock_utils.execute.return_value = ('fake_UUID\n', None)
        mock_gu.guess_grub_version.return_value = 2
        self.mgr.do_bootloader()
        mock_gu.guess_grub_version.assert_called_once_with(
            chroot='/tmp/target')
        mock_gu.grub2_cfg.assert_called_once_with(
            kernel_params=' console=ttyS0,9600 console=tty0 rootdelay=90 '
                          'nomodeset root=UUID=fake_UUID ',
            chroot='/tmp/target')
        mock_gu.grub2_install.assert_called_once_with(
            ['/dev/sda', '/dev/sdb', '/dev/sdc'],
            chroot='/tmp/target')
        self.assertFalse(mock_gu.grub1_cfg.called)
        self.assertFalse(mock_gu.grub1_install.called)

    @mock.patch('fuel_agent.manager.gu', create=True)
    @mock.patch('fuel_agent.manager.utils', create=True)
    @mock.patch.object(manager.Manager, 'mount_target')
    @mock.patch.object(manager.Manager, 'umount_target')
    def test_do_bootloader_writes(self, mock_umount, mock_mount, mock_utils,
                                  mock_gu):
        # actually covers only write() calls
        mock_utils.execute.return_value = ('fake_UUID\n', None)
        with mock.patch('fuel_agent.manager.open', create=True) as mock_open:
            file_handle_mock = mock_open.return_value.__enter__.return_value
            self.mgr.do_bootloader()
            expected_open_calls = [
                mock.call('/tmp/target/etc/udev/rules.d/70-persistent-net.'
                          'rules', 'w'),
                mock.call('/tmp/target/etc/udev/rules.d/75-persistent-net-'
                          'generator.rules', 'w'),
                mock.call('/tmp/target/etc/nailgun-agent/nodiscover', 'w'),
                mock.call('/tmp/target/etc/fstab', 'wb')]
            self.assertEqual(expected_open_calls, mock_open.call_args_list)
            expected_write_calls = [
                mock.call('# Generated by fuel-agent during provisioning: '
                          'BEGIN\n'),
                mock.call('SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", '
                          'ATTR{address}=="08:00:27:79:da:80", ATTR{type}=="1"'
                          ', KERNEL=="eth*", NAME="eth0"\n'),
                mock.call('SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", '
                          'ATTR{address}=="08:00:27:46:43:60", ATTR{type}=="1"'
                          ', KERNEL=="eth*", NAME="eth1"\n'),
                mock.call('SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", '
                          'ATTR{address}=="08:00:27:b1:d7:15", ATTR{type}=="1"'
                          ', KERNEL=="eth*", NAME="eth2"\n'),
                mock.call('# Generated by fuel-agent during provisioning: '
                          'END\n'),
                mock.call('# Generated by fuel-agent during provisioning:\n# '
                          'DO NOT DELETE. It is needed to disable '
                          'net-generator\n'),
                mock.call('UUID=fake_UUID /boot ext2 defaults 0 0\n'),
                mock.call('UUID=fake_UUID /tmp ext2 defaults 0 0\n'),
                mock.call('UUID=fake_UUID / ext4 defaults,errors=panic 0 0\n'),
                mock.call('UUID=fake_UUID swap swap defaults 0 0\n'),
                mock.call('UUID=fake_UUID /var/lib/glance xfs defaults 0 0\n')]
            self.assertEqual(expected_write_calls,
                             file_handle_mock.write.call_args_list)
        mock_umount.assert_called_once_with('/tmp/target')
        mock_mount.assert_called_once_with('/tmp/target')
        mock_utils.makedirs_if_not_exists.assert_called_once_with(
            '/tmp/target/etc/nailgun-agent')

    @mock.patch('six.moves.builtins.open')
    @mock.patch.object(os, 'symlink')
    @mock.patch.object(os, 'remove')
    @mock.patch.object(os, 'path')
    @mock.patch.object(os, 'listdir')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(mu, 'mdclean_all')
    @mock.patch.object(lu, 'lvremove_all')
    @mock.patch.object(lu, 'vgremove_all')
    @mock.patch.object(lu, 'pvremove_all')
    @mock.patch.object(fu, 'make_fs')
    @mock.patch.object(lu, 'lvcreate')
    @mock.patch.object(lu, 'vgcreate')
    @mock.patch.object(lu, 'pvcreate')
    @mock.patch.object(mu, 'mdcreate')
    @mock.patch.object(pu, 'set_gpt_type')
    @mock.patch.object(pu, 'set_partition_flag')
    @mock.patch.object(pu, 'make_partition')
    @mock.patch.object(pu, 'make_label')
    @mock.patch.object(hu, 'list_block_devices')
    def test_do_partitioning(self, mock_hu_lbd, mock_pu_ml, mock_pu_mp,
                             mock_pu_spf, mock_pu_sgt, mock_mu_m, mock_lu_p,
                             mock_lu_v, mock_lu_l, mock_fu_mf, mock_pvr,
                             mock_vgr, mock_lvr, mock_mdr, mock_exec,
                             mock_os_ld, mock_os_p, mock_os_r, mock_os_s,
                             mock_open):
        mock_os_ld.return_value = ['not_a_rule', 'fake.rules']
        mock_os_p.exists.return_value = True
        mock_hu_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_SAMPLE
        self.mgr.do_partitioning()
        mock_pu_ml_expected_calls = [mock.call('/dev/sda', 'gpt'),
                                     mock.call('/dev/sdb', 'gpt'),
                                     mock.call('/dev/sdc', 'gpt')]
        self.assertEqual(mock_pu_ml_expected_calls, mock_pu_ml.call_args_list)

        mock_pu_mp_expected_calls = [
            mock.call('/dev/sda', 1, 25, 'primary'),
            mock.call('/dev/sda', 25, 225, 'primary'),
            mock.call('/dev/sda', 225, 425, 'primary'),
            mock.call('/dev/sda', 425, 625, 'primary'),
            mock.call('/dev/sda', 625, 20063, 'primary'),
            mock.call('/dev/sda', 20063, 65660, 'primary'),
            mock.call('/dev/sda', 65660, 65680, 'primary'),
            mock.call('/dev/sdb', 1, 25, 'primary'),
            mock.call('/dev/sdb', 25, 225, 'primary'),
            mock.call('/dev/sdb', 225, 65196, 'primary'),
            mock.call('/dev/sdc', 1, 25, 'primary'),
            mock.call('/dev/sdc', 25, 225, 'primary'),
            mock.call('/dev/sdc', 225, 65196, 'primary')]
        self.assertEqual(mock_pu_mp_expected_calls, mock_pu_mp.call_args_list)

        mock_pu_spf_expected_calls = [mock.call('/dev/sda', 1, 'bios_grub'),
                                      mock.call('/dev/sdb', 1, 'bios_grub'),
                                      mock.call('/dev/sdc', 1, 'bios_grub')]
        self.assertEqual(mock_pu_spf_expected_calls,
                         mock_pu_spf.call_args_list)

        mock_pu_sgt_expected_calls = [mock.call('/dev/sda', 4, 'fake_guid')]
        self.assertEqual(mock_pu_sgt_expected_calls,
                         mock_pu_sgt.call_args_list)

        mock_lu_p_expected_calls = [
            mock.call('/dev/sda5', metadatasize=28, metadatacopies=2),
            mock.call('/dev/sda6', metadatasize=28, metadatacopies=2),
            mock.call('/dev/sdb3', metadatasize=28, metadatacopies=2),
            mock.call('/dev/sdc3', metadatasize=28, metadatacopies=2)]
        self.assertEqual(mock_lu_p_expected_calls, mock_lu_p.call_args_list)

        mock_lu_v_expected_calls = [mock.call('os', '/dev/sda5'),
                                    mock.call('image', '/dev/sda6',
                                              '/dev/sdb3', '/dev/sdc3')]
        self.assertEqual(mock_lu_v_expected_calls, mock_lu_v.call_args_list)

        mock_lu_l_expected_calls = [mock.call('os', 'root', 15360),
                                    mock.call('os', 'swap', 4014),
                                    mock.call('image', 'glance', 175347)]
        self.assertEqual(mock_lu_l_expected_calls, mock_lu_l.call_args_list)

        mock_fu_mf_expected_calls = [
            mock.call('ext2', '', '', '/dev/sda3'),
            mock.call('ext2', '', '', '/dev/sda4'),
            mock.call('swap', '', '', '/dev/mapper/os-swap'),
            mock.call('xfs', '', '', '/dev/mapper/image-glance')]
        self.assertEqual(mock_fu_mf_expected_calls, mock_fu_mf.call_args_list)

    @mock.patch.object(utils, 'calculate_md5')
    @mock.patch('os.path.getsize')
    @mock.patch('yaml.load')
    @mock.patch.object(utils, 'init_http_request')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(utils, 'render_and_save')
    @mock.patch.object(hu, 'list_block_devices')
    def test_do_configdrive(self, mock_lbd, mock_u_ras, mock_u_e,
                            mock_http_req, mock_yaml, mock_get_size, mock_md5):
        mock_get_size.return_value = 123
        mock_md5.return_value = 'fakemd5'
        mock_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_SAMPLE
        self.assertEqual(1, len(self.mgr.driver.image_scheme.images))
        self.mgr.do_configdrive()
        mock_u_ras_expected_calls = [
            mock.call(CONF.nc_template_path,
                      ['cloud_config_pro_fi-le.jinja2',
                       'cloud_config_pro.jinja2',
                       'cloud_config_pro_fi.jinja2',
                       'cloud_config.jinja2'],
                      mock.ANY, '%s/%s' % (CONF.tmp_path, 'cloud_config.txt')),
            mock.call(CONF.nc_template_path,
                      ['boothook_pro_fi-le.jinja2',
                       'boothook_pro.jinja2',
                       'boothook_pro_fi.jinja2',
                       'boothook.jinja2'],
                      mock.ANY, '%s/%s' % (CONF.tmp_path, 'boothook.txt')),
            mock.call(CONF.nc_template_path,
                      ['meta-data_pro_fi-le.jinja2',
                       'meta-data_pro.jinja2',
                       'meta-data_pro_fi.jinja2',
                       'meta-data.jinja2'],
                      mock.ANY, '%s/%s' % (CONF.tmp_path, 'meta-data'))]
        self.assertEqual(mock_u_ras_expected_calls, mock_u_ras.call_args_list)

        mock_u_e_expected_calls = [
            mock.call('write-mime-multipart',
                      '--output=%s' % ('%s/%s' % (CONF.tmp_path, 'user-data')),
                      '%s:text/cloud-boothook' % ('%s/%s' % (CONF.tmp_path,
                                                             'boothook.txt')),
                      '%s:text/cloud-config' % ('%s/%s' % (CONF.tmp_path,
                                                           'cloud_config.txt'))
                      ),
            mock.call('genisoimage', '-output', CONF.config_drive_path,
                      '-volid', 'cidata', '-joliet', '-rock',
                      '%s/%s' % (CONF.tmp_path, 'user-data'),
                      '%s/%s' % (CONF.tmp_path, 'meta-data'))]
        self.assertEqual(mock_u_e_expected_calls, mock_u_e.call_args_list)
        self.assertEqual(2, len(self.mgr.driver.image_scheme.images))
        cf_drv_img = self.mgr.driver.image_scheme.images[-1]
        self.assertEqual('file://%s' % CONF.config_drive_path, cf_drv_img.uri)
        self.assertEqual('/dev/sda7',
                         self.mgr.driver.partition_scheme.configdrive_device())
        self.assertEqual('iso9660', cf_drv_img.format)
        self.assertEqual('raw', cf_drv_img.container)
        self.assertEqual('fakemd5', cf_drv_img.md5)
        self.assertEqual(123, cf_drv_img.size)

    @mock.patch('yaml.load')
    @mock.patch.object(utils, 'init_http_request')
    @mock.patch.object(partition.PartitionScheme, 'configdrive_device')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(utils, 'render_and_save')
    @mock.patch.object(hu, 'list_block_devices')
    def test_do_configdrive_no_configdrive_device(self, mock_lbd, mock_u_ras,
                                                  mock_u_e, mock_p_ps_cd,
                                                  mock_http_req, mock_yaml):
        mock_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_SAMPLE
        mock_p_ps_cd.return_value = None
        self.assertRaises(errors.WrongPartitionSchemeError,
                          self.mgr.do_configdrive)

    @mock.patch.object(utils, 'calculate_md5')
    @mock.patch('os.path.getsize')
    @mock.patch('yaml.load')
    @mock.patch.object(utils, 'init_http_request')
    @mock.patch.object(fu, 'extend_fs')
    @mock.patch.object(au, 'GunzipStream')
    @mock.patch.object(au, 'LocalFile')
    @mock.patch.object(au, 'HttpUrl')
    @mock.patch.object(au, 'Chain')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(utils, 'render_and_save')
    @mock.patch.object(hu, 'list_block_devices')
    def test_do_copyimage(self, mock_lbd, mock_u_ras, mock_u_e, mock_au_c,
                          mock_au_h, mock_au_l, mock_au_g, mock_fu_ef,
                          mock_http_req, mock_yaml, mock_get_size, mock_md5):

        class FakeChain(object):
            processors = []

            def append(self, thing):
                self.processors.append(thing)

            def process(self):
                pass

        mock_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_SAMPLE
        mock_au_c.return_value = FakeChain()
        self.mgr.do_configdrive()
        self.mgr.do_copyimage()
        imgs = self.mgr.driver.image_scheme.images
        self.assertEqual(2, len(imgs))
        expected_processors_list = []
        for img in imgs[:-1]:
            expected_processors_list += [
                img.uri,
                au.HttpUrl,
                au.GunzipStream,
                img.target_device
            ]
        expected_processors_list += [
            imgs[-1].uri,
            au.LocalFile,
            imgs[-1].target_device
        ]
        self.assertEqual(expected_processors_list,
                         mock_au_c.return_value.processors)
        mock_fu_ef_expected_calls = [
            mock.call('ext4', '/dev/mapper/os-root')]
        self.assertEqual(mock_fu_ef_expected_calls, mock_fu_ef.call_args_list)

    @mock.patch.object(utils, 'calculate_md5')
    @mock.patch('os.path.getsize')
    @mock.patch('yaml.load')
    @mock.patch.object(utils, 'init_http_request')
    @mock.patch.object(fu, 'extend_fs')
    @mock.patch.object(au, 'GunzipStream')
    @mock.patch.object(au, 'LocalFile')
    @mock.patch.object(au, 'HttpUrl')
    @mock.patch.object(au, 'Chain')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(utils, 'render_and_save')
    @mock.patch.object(hu, 'list_block_devices')
    def test_do_copyimage_md5_matches(self, mock_lbd, mock_u_ras, mock_u_e,
                                      mock_au_c, mock_au_h, mock_au_l,
                                      mock_au_g, mock_fu_ef, mock_http_req,
                                      mock_yaml, mock_get_size, mock_md5):

        class FakeChain(object):
            processors = []

            def append(self, thing):
                self.processors.append(thing)

            def process(self):
                pass

        mock_get_size.return_value = 123
        mock_md5.side_effect = ['fakemd5', 'really_fakemd5', 'fakemd5']
        mock_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_SAMPLE
        mock_au_c.return_value = FakeChain()
        self.mgr.driver.image_scheme.images[0].size = 1234
        self.mgr.driver.image_scheme.images[0].md5 = 'really_fakemd5'
        self.mgr.do_configdrive()
        self.assertEqual(2, len(self.mgr.driver.image_scheme.images))
        self.mgr.do_copyimage()
        expected_md5_calls = [mock.call('/tmp/config-drive.img', 123),
                              mock.call('/dev/mapper/os-root', 1234),
                              mock.call('/dev/sda7', 123)]
        self.assertEqual(expected_md5_calls, mock_md5.call_args_list)

    @mock.patch.object(utils, 'calculate_md5')
    @mock.patch('os.path.getsize')
    @mock.patch('yaml.load')
    @mock.patch.object(utils, 'init_http_request')
    @mock.patch.object(fu, 'extend_fs')
    @mock.patch.object(au, 'GunzipStream')
    @mock.patch.object(au, 'LocalFile')
    @mock.patch.object(au, 'HttpUrl')
    @mock.patch.object(au, 'Chain')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(utils, 'render_and_save')
    @mock.patch.object(hu, 'list_block_devices')
    def test_do_copyimage_md5_mismatch(self, mock_lbd, mock_u_ras, mock_u_e,
                                       mock_au_c, mock_au_h, mock_au_l,
                                       mock_au_g, mock_fu_ef, mock_http_req,
                                       mock_yaml, mock_get_size, mock_md5):

        class FakeChain(object):
            processors = []

            def append(self, thing):
                self.processors.append(thing)

            def process(self):
                pass

        mock_get_size.return_value = 123
        mock_md5.side_effect = ['fakemd5', 'really_fakemd5', 'fakemd5']
        mock_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_SAMPLE
        mock_au_c.return_value = FakeChain()
        self.mgr.driver.image_scheme.images[0].size = 1234
        self.mgr.driver.image_scheme.images[0].md5 = 'fakemd5'
        self.mgr.do_configdrive()
        self.assertEqual(2, len(self.mgr.driver.image_scheme.images))
        self.assertRaises(errors.ImageChecksumMismatchError,
                          self.mgr.do_copyimage)

    @mock.patch('fuel_agent.manager.fu', create=True)
    @mock.patch('fuel_agent.manager.utils', create=True)
    @mock.patch('fuel_agent.manager.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.manager.os', create=True)
    def test_mount_target_mtab_is_link(self, mock_os, mock_open, mock_utils,
                                       mock_fu):
        mock_os.path.islink.return_value = True
        mock_utils.execute.return_value = (None, None)
        self.mgr.driver.partition_scheme = objects.PartitionScheme()
        self.mgr.mount_target('fake_chroot')
        mock_open.assert_called_once_with('fake_chroot/etc/mtab', 'wb')
        mock_os.path.islink.assert_called_once_with('fake_chroot/etc/mtab')
        mock_os.remove.assert_called_once_with('fake_chroot/etc/mtab')

    @mock.patch('fuel_agent.manager.fu', create=True)
    @mock.patch('fuel_agent.manager.utils', create=True)
    @mock.patch('fuel_agent.manager.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.manager.os', create=True)
    def test_mount_target(self, mock_os, mock_open, mock_utils, mock_fu):
        mock_os.path.islink.return_value = False
        self.mgr.driver.partition_scheme = objects.PartitionScheme()
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='/var/lib', fs_type='xfs')
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='/', fs_type='ext4')
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='/boot', fs_type='ext2')
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='swap', fs_type='swap')
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='/var', fs_type='ext4')
        fake_mtab = """
proc /proc proc rw,noexec,nosuid,nodev 0 0
sysfs /sys sysfs rw,noexec,nosuid,nodev 0 0
none /sys/fs/fuse/connections fusectl rw 0 0
none /sys/kernel/debug debugfs rw 0 0
none /sys/kernel/security securityfs rw 0 0
udev /dev devtmpfs rw,mode=0755 0 0
devpts /dev/pts devpts rw,noexec,nosuid,gid=5,mode=0620 0 0
tmpfs /run tmpfs rw,noexec,nosuid,size=10%,mode=0755 0 0
none /run/lock tmpfs rw,noexec,nosuid,nodev,size=5242880 0 0
none /run/shm tmpfs rw,nosuid,nodev 0 0"""
        mock_utils.execute.return_value = (fake_mtab, None)
        self.mgr.mount_target('fake_chroot')
        self.assertEqual([mock.call('fake_chroot/'),
                          mock.call('fake_chroot/boot'),
                          mock.call('fake_chroot/var'),
                          mock.call('fake_chroot/var/lib'),
                          mock.call('fake_chroot/sys'),
                          mock.call('fake_chroot/dev'),
                          mock.call('fake_chroot/proc')],
                         mock_utils.makedirs_if_not_exists.call_args_list)
        self.assertEqual([mock.call('ext4', 'fake', 'fake_chroot/'),
                          mock.call('ext2', 'fake', 'fake_chroot/boot'),
                          mock.call('ext4', 'fake', 'fake_chroot/var'),
                          mock.call('xfs', 'fake', 'fake_chroot/var/lib')],
                         mock_fu.mount_fs.call_args_list)
        self.assertEqual([mock.call('fake_chroot', '/sys'),
                          mock.call('fake_chroot', '/dev'),
                          mock.call('fake_chroot', '/proc')],
                         mock_fu.mount_bind.call_args_list)
        file_handle = mock_open.return_value.__enter__.return_value
        file_handle.write.assert_called_once_with(fake_mtab)
        mock_open.assert_called_once_with('fake_chroot/etc/mtab', 'wb')
        mock_os.path.islink.assert_called_once_with('fake_chroot/etc/mtab')
        self.assertFalse(mock_os.remove.called)

    @mock.patch('fuel_agent.manager.fu', create=True)
    def test_umount_target(self, mock_fu):
        self.mgr.driver.partition_scheme = objects.PartitionScheme()
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='/var/lib', fs_type='xfs')
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='/', fs_type='ext4')
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='/boot', fs_type='ext2')
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='swap', fs_type='swap')
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='/var', fs_type='ext4')
        self.mgr.umount_target('fake_chroot')
        self.assertEqual([mock.call('fake_chroot/proc'),
                          mock.call('fake_chroot/dev'),
                          mock.call('fake_chroot/sys'),
                          mock.call('fake_chroot/var/lib'),
                          mock.call('fake_chroot/boot'),
                          mock.call('fake_chroot/var'),
                          mock.call('fake_chroot/')],
                         mock_fu.umount_fs.call_args_list)

    @mock.patch('fuel_agent.manager.bu', create=True)
    @mock.patch('fuel_agent.manager.fu', create=True)
    @mock.patch('fuel_agent.manager.utils', create=True)
    @mock.patch('fuel_agent.manager.os', create=True)
    @mock.patch('fuel_agent.manager.shutil.move')
    @mock.patch('fuel_agent.manager.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.manager.tempfile.mkdtemp')
    @mock.patch('fuel_agent.manager.yaml.safe_dump')
    @mock.patch.object(manager.Manager, 'mount_target')
    @mock.patch.object(manager.Manager, 'umount_target')
    def test_do_build_image(self, mock_umount_target, mock_mount_target,
                            mock_yaml_dump, mock_mkdtemp,
                            mock_open, mock_shutil_move, mock_os,
                            mock_utils, mock_fu, mock_bu):

        loops = [objects.Loop(), objects.Loop()]

        self.mgr.driver.image_scheme = objects.ImageScheme([
            objects.Image('file:///fake/img.img.gz', loops[0], 'ext4', 'gzip'),
            objects.Image('file:///fake/img-boot.img.gz',
                          loops[1], 'ext2', 'gzip')])
        self.mgr.driver.partition_scheme = objects.PartitionScheme()
        self.mgr.driver.partition_scheme.add_fs(
            device=loops[0], mount='/', fs_type='ext4')
        self.mgr.driver.partition_scheme.add_fs(
            device=loops[1], mount='/boot', fs_type='ext2')
        self.mgr.driver.metadata_uri = 'file:///fake/img.yaml'
        self.mgr.driver.operating_system = objects.Ubuntu(
            repos=[
                objects.DEBRepo('ubuntu', 'http://fakeubuntu',
                                'trusty', 'fakesection', priority=900),
                objects.DEBRepo('ubuntu_zero', 'http://fakeubuntu_zero',
                                'trusty', 'fakesection', priority=None),
                objects.DEBRepo('mos', 'http://fakemos',
                                'mosX.Y', 'fakesection', priority=1000)],
            packages=['fakepackage1', 'fakepackage2'])

        mock_os.path.exists.return_value = False
        mock_os.path.join.return_value = '/tmp/imgdir/proc'
        mock_os.path.basename.side_effect = ['img.img.gz', 'img-boot.img.gz']
        mock_bu.create_sparse_tmp_file.side_effect = \
            ['/tmp/img', '/tmp/img-boot']
        mock_bu.get_free_loop_device.side_effect = ['/dev/loop0', '/dev/loop1']
        mock_mkdtemp.return_value = '/tmp/imgdir'
        getsize_side = [20, 2, 10, 1]
        mock_os.path.getsize.side_effect = getsize_side
        md5_side = ['fakemd5_raw', 'fakemd5_gzip',
                    'fakemd5_raw_boot', 'fakemd5_gzip_boot']
        mock_utils.calculate_md5.side_effect = md5_side
        mock_bu.containerize.side_effect = ['/tmp/img.gz', '/tmp/img-boot.gz']
        mock_bu.stop_chrooted_processes.side_effect = [
            False, True, False, True]

        self.mgr.do_build_image()
        self.assertEqual(
            [mock.call('/fake/img.img.gz'),
             mock.call('/fake/img-boot.img.gz')],
            mock_os.path.exists.call_args_list)
        self.assertEqual([mock.call(dir=CONF.image_build_dir,
                                    suffix=CONF.image_build_suffix)] * 2,
                         mock_bu.create_sparse_tmp_file.call_args_list)
        self.assertEqual([mock.call()] * 2,
                         mock_bu.get_free_loop_device.call_args_list)
        self.assertEqual([mock.call('/tmp/img', '/dev/loop0'),
                          mock.call('/tmp/img-boot', '/dev/loop1')],
                         mock_bu.attach_file_to_loop.call_args_list)
        self.assertEqual([mock.call(fs_type='ext4', fs_options='',
                                    fs_label='', dev='/dev/loop0'),
                          mock.call(fs_type='ext2', fs_options='',
                                    fs_label='', dev='/dev/loop1')],
                         mock_fu.make_fs.call_args_list)
        mock_mkdtemp.assert_called_once_with(dir=CONF.image_build_dir,
                                             suffix=CONF.image_build_suffix)
        mock_mount_target.assert_called_once_with(
            '/tmp/imgdir', treat_mtab=False, pseudo=False)
        self.assertEqual([mock.call('/tmp/imgdir')] * 2,
                         mock_bu.suppress_services_start.call_args_list)
        mock_bu.run_debootstrap.assert_called_once_with(
            uri='http://fakeubuntu', suite='trusty', chroot='/tmp/imgdir')
        mock_bu.set_apt_get_env.assert_called_once_with()
        mock_bu.pre_apt_get.assert_called_once_with('/tmp/imgdir')
        self.assertEqual([
            mock.call(name='ubuntu',
                      uri='http://fakeubuntu',
                      suite='trusty',
                      section='fakesection',
                      chroot='/tmp/imgdir'),
            mock.call(name='ubuntu_zero',
                      uri='http://fakeubuntu_zero',
                      suite='trusty',
                      section='fakesection',
                      chroot='/tmp/imgdir'),
            mock.call(name='mos',
                      uri='http://fakemos',
                      suite='mosX.Y',
                      section='fakesection',
                      chroot='/tmp/imgdir')],
            mock_bu.add_apt_source.call_args_list)

        # we don't call add_apt_preference for ubuntu_zero
        # because it has priority == None
        self.assertEqual([
            mock.call(name='ubuntu',
                      priority=900,
                      suite='trusty',
                      section='fakesection',
                      chroot='/tmp/imgdir',
                      uri='http://fakeubuntu'),
            mock.call(name='mos',
                      priority=1000,
                      suite='mosX.Y',
                      section='fakesection',
                      chroot='/tmp/imgdir',
                      uri='http://fakemos')],
            mock_bu.add_apt_preference.call_args_list)
        mock_utils.makedirs_if_not_exists.assert_called_once_with(
            '/tmp/imgdir/proc')
        self.assertEqual([
            mock.call('tune2fs', '-O', '^has_journal', '/dev/loop0'),
            mock.call('tune2fs', '-O', 'has_journal', '/dev/loop0')],
            mock_utils.execute.call_args_list)
        mock_fu.mount_bind.assert_called_once_with('/tmp/imgdir', '/proc')
        mock_bu.run_apt_get.assert_called_once_with(
            '/tmp/imgdir', packages=['fakepackage1', 'fakepackage2'])
        mock_bu.do_post_inst.assert_called_once_with('/tmp/imgdir')
        signal_calls = mock_bu.stop_chrooted_processes.call_args_list
        self.assertEqual(2 * [mock.call('/tmp/imgdir', signal=signal.SIGTERM),
                              mock.call('/tmp/imgdir', signal=signal.SIGKILL)],
                         signal_calls)
        self.assertEqual(
            [mock.call('/tmp/imgdir/proc')] * 2,
            mock_fu.umount_fs.call_args_list)
        self.assertEqual(
            [mock.call(
                '/tmp/imgdir', pseudo=False)] * 2,
            mock_umount_target.call_args_list)
        self.assertEqual(
            [mock.call('/dev/loop0'), mock.call('/dev/loop1')] * 2,
            mock_bu.deattach_loop.call_args_list)
        self.assertEqual([mock.call('/tmp/img'), mock.call('/tmp/img-boot')],
                         mock_bu.shrink_sparse_file.call_args_list)
        self.assertEqual([mock.call('/tmp/img'),
                          mock.call('/fake/img.img.gz'),
                          mock.call('/tmp/img-boot'),
                          mock.call('/fake/img-boot.img.gz')],
                         mock_os.path.getsize.call_args_list)
        self.assertEqual([mock.call('/tmp/img', 20),
                          mock.call('/fake/img.img.gz', 2),
                          mock.call('/tmp/img-boot', 10),
                          mock.call('/fake/img-boot.img.gz', 1)],
                         mock_utils.calculate_md5.call_args_list)
        self.assertEqual([mock.call('/tmp/img', 'gzip'),
                          mock.call('/tmp/img-boot', 'gzip')],
                         mock_bu.containerize.call_args_list)
        mock_open.assert_called_once_with('/fake/img.yaml', 'w')
        self.assertEqual(
            [mock.call('/tmp/img.gz', '/fake/img.img.gz'),
             mock.call('/tmp/img-boot.gz', '/fake/img-boot.img.gz')],
            mock_shutil_move.call_args_list)

        metadata = {}
        for repo in self.mgr.driver.operating_system.repos:
            metadata.setdefault('repos', []).append({
                'type': 'deb',
                'name': repo.name,
                'uri': repo.uri,
                'suite': repo.suite,
                'section': repo.section,
                'priority': repo.priority,
                'meta': repo.meta})
        metadata['packages'] = self.mgr.driver.operating_system.packages
        metadata['images'] = [
            {
                'raw_md5': md5_side[0],
                'raw_size': getsize_side[0],
                'raw_name': None,
                'container_name':
                os.path.basename(
                    self.mgr.driver.image_scheme.images[0].uri.split(
                        'file://', 1)[1]),
                'container_md5': md5_side[1],
                'container_size': getsize_side[1],
                'container': self.mgr.driver.image_scheme.images[0].container,
                'format': self.mgr.driver.image_scheme.images[0].format
            },
            {
                'raw_md5': md5_side[2],
                'raw_size': getsize_side[2],
                'raw_name': None,
                'container_name':
                os.path.basename(
                    self.mgr.driver.image_scheme.images[1].uri.split(
                        'file://', 1)[1]),
                'container_md5': md5_side[3],
                'container_size': getsize_side[3],
                'container': self.mgr.driver.image_scheme.images[1].container,
                'format': self.mgr.driver.image_scheme.images[1].format
            }
        ]
        mock_yaml_dump.assert_called_once_with(metadata, stream=mock_open())
