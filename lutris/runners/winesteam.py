# -*- coding:Utf-8 -*-
"""Runner for the Steam platform"""
import os
import time
import subprocess

from gi.repository import Gdk

from lutris import settings
from lutris.gui.dialogs import DirectoryDialog, ErrorDialog
from lutris.runners import wine
from lutris.util.log import logger
from lutris.util.steam import (read_config, get_path_from_config,
                               get_path_from_appmanifest)
from lutris.util import system
from lutris.config import LutrisConfig

# Redefine wine installer tasks
set_regedit = wine.set_regedit
create_prefix = wine.create_prefix
wineexec = wine.wineexec
winetricks = wine.winetricks

# Directly downloading from steam's cdn seems to be buggy with
# current implementation
# STEAM_INSTALLER_URL = "http://cdn.steampowered.com/download/SteamInstall.msi"
STEAM_INSTALLER_URL = "http://lutris.net/files/runners/SteamInstall.msi"


def download_steam(downloader, callback=None, callback_data=None):
    """Downloads steam with `downloader` then calls `callback`"""
    steam_installer_path = os.path.join(settings.TMP_PATH,
                                        "SteamInstall.msi")
    downloader(STEAM_INSTALLER_URL,
               steam_installer_path, callback, callback_data)


def is_running():
    return bool(system.get_pid('Steam.exe$'))


def shutdown():
    """ Shutdown Steam in a clean way.
        TODO: Detect wine binary
    """
    pid = system.get_pid('Steam.exe$')
    if not pid:
        return False
    cwd = system.get_cwd(pid)
    cmdline = system.get_command_line(pid)
    steam_exe = os.path.join(cwd, cmdline)
    logger.debug("Shutting winesteam: %s", steam_exe)
    system.execute(['wine', steam_exe, '-shutdown'])


def kill():
    system.kill_pid(system.get_pid('Steam.exe$'))


# pylint: disable=C0103
class winesteam(wine.wine):
    """ Runs Steam for Windows games """
    platform = "Steam (Windows)"
    is_watchable = False  # Steam games pids are not parent of Lutris
    game_options = [
        {
            'option': 'appid',
            'type': 'string',
            'label': 'appid'
        },
        {
            'option': 'args',
            'type': 'string',
            'label': 'arguments'
        },
        {
            'option': 'prefix',
            'type': 'directory_chooser',
            'label': 'Prefix'
        }
    ]

    def __init__(self, config=None):
        super(winesteam, self).__init__(config)
        self.runner_options.insert(0, {
            'option': 'steam_path',
            'type': 'file',
            'label': 'Path to Steam.exe',
        })

    @property
    def browse_dir(self):
        """Return the path to open with the Browse Files action."""
        if not self.is_installed():
            installed = self.install_dialog()
            if not installed:
                return False
        return self.game_path

    @property
    def game_path(self):
        appid = self.config['game'].get('appid')
        if self.get_game_data_path(appid):
            return self.get_game_data_path(appid)

    @property
    def launch_args(self):
        return ['"%s"' % self.get_executable(),
                '"%s"' % self.steam_path, '-no-dwrite']

    @property
    def steam_path(self):
        """Return Steam exe's path"""
        path = self.runner_config.get('steam_path')
        if path and os.path.exists(path):
            return path
        return os.path.join(self.get_default_steam_dir(), "Steam.exe")

    def get_default_steam_dir(self, prefix=None):
        """Returns default location of Steam"""
        if not prefix:
            prefix = os.path.expanduser("~/.wine")
        return os.path.join(prefix, "drive_c/Program Files/Steam")

    def install(self, installer_path=None):
        if installer_path:
            self.msi_exec(installer_path, quiet=True)
            steam_dir = self.get_default_steam_dir()
        else:
            Gdk.threads_enter()
            dlg = DirectoryDialog('Where is Steam.exe installed?')
            steam_dir = dlg.folder
            Gdk.threads_leave()
        steam_path = os.path.join(steam_dir, "Steam.exe")
        if os.path.exists(steam_path):
            config = LutrisConfig(runner='winesteam')
            config.runner_config = {'winesteam': {'steam_path': steam_path}}
            config.save()
        else:
            ErrorDialog("Can't find Steam.exe in the selected folder")

    def is_installed(self):
        """ Checks if wine is installed and if the steam executable is on the
            harddrive.
        """
        if not self.check_depends() or not self.steam_path:
            return False
        return os.path.exists(self.steam_path)

    def get_steam_config(self):
        if not self.steam_path:
            return
        steam_path = os.path.dirname(self.steam_path)
        return read_config(steam_path)

    def get_appid_list(self):
        """Return the list of appids of all user's games"""
        config = self.get_steam_config()
        if config:
            apps = config['apps']
            return apps.keys()

    def get_steamapps_path(self):
        candidates = (
            "SteamApps/common",
            "steamapps/common",
        )
        for candidate in candidates:
            steam_path = os.path.dirname(self.steam_path)
            path = os.path.join(steam_path, candidate)
            if os.path.exists(path):
                return path
        raise IOError("Unable to locate SteamApps path")

    def get_game_data_path(self, appid):
        steam_path = os.path.dirname(self.steam_path)
        data_path = get_path_from_appmanifest(steam_path, appid)
        if not data_path:
            steam_config = self.get_steam_config()
            data_path = get_path_from_config(steam_config, appid)
        if not data_path:
            logger.warning("Data path for SteamApp %s not found.", appid)
        return data_path

    def install_game(self, appid):
        command = self.launch_args + ["steam://install/%s" % appid]
        string = ' '.join(command)
        logger.debug("Thread running: %s", string)
        subprocess.Popen(string, shell=True)

    def validate_game(self, appid):
        command = self.launch_args + ["steam://validate/%s" % appid]
        string = ' '.join(command)
        subprocess.Popen(string, shell=True)

    def prelaunch(self):
        from lutris.runners import steam
        if steam.is_running():
            steam.shutdown()
            logger.info("Waiting for Steam to shutdown...")
            time.sleep(2)
            if steam.is_running():
                logger.info("Steam does not shutdown, killing it...")
                steam.kill()
                time.sleep(2)
                if steam.is_running():
                    logger.error("Failed to shutdown Steam for Windows :(")
                    return False
        return True

    def play(self):
        if not self.check_depends():
            return {'error': 'RUNNER_NOT_INSTALLED',
                    'runner': self.depends}
        if not self.is_installed():
            return {'error': 'RUNNER_NOT_INSTALLED',
                    'runner': self.__class__.__name__}

        appid = self.config['game'].get('appid') or ''
        args = self.config['game'].get('args') or ''
        logger.debug("Checking Steam installation")
        self.prepare_launch()
        command = ["WINEDEBUG=fixme-all"]
        prefix = self.config['game'].get('prefix') or ''
        if prefix:
            # TODO: Verify if a prefix exists that it's created with the
            # correct architecture
            command.append('WINEPREFIX="%s" ' % prefix)
        command += self.launch_args
        if appid:
            command += ['-applaunch', appid]
        if args:
            command += [args]
        return {'command': command}

    def stop(self):
        shutdown()
        time.sleep(2)
        super(winesteam, self).stop()
