#!/usr/bin/env python
#
# Glances is a simple textual monitoring tool
#
# Pre-requisites: Python 2.6+ and PsUtil 0.4.0+ (for full functions)
#
# Copyright (C) Nicolargo 2012 <nicolas@nicolargo.com>
#
# under the terms of the GNU Lesser General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Glances is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.";
#

from __future__ import generators

__appname__ = 'glances'
__version__ = "1.4b19"
__author__ = "Nicolas Hennion <nicolas@nicolargo.com>"
__licence__ = "LGPL"

# Libraries
#==========

import sys

try:
    import os
    import platform
    import getopt
    import signal
    import time
    import datetime
    import multiprocessing
    import gettext
except ImportError:
    print("Error during Python libraries import: " + str(sys.exc_info()[1]))
    sys.exit(1)


# International
#==============

gettext.install(__appname__)

# Test methods
#=============

try:
    import curses
    import curses.panel
except ImportError:
    print _('Textmode GUI initialization failed, Glances cannot start.')
    print _('Use Python 2.6 or higher')
    print
    sys.exit(1)

try:
    import psutil
except ImportError:
    print _('PsUtil library initialization failed, Glances cannot start.')
    print
    print _('On Ubuntu 12.04+, you can try (as root):')
    print _('# apt-get install python-psutil')
    print
    print _('On Debian/Ubuntu(< 12.04), you can try (as root):')
    print _('# apt-get install python-dev python-pip')
    print _('# pip install psutil')
    print
    sys.exit(1)

try:
    # get_cpu_percent method only available with PsUtil 0.2.0 or +
    psutil.Process(os.getpid()).get_cpu_percent(interval=0)
except:
    psutil_get_cpu_percent_tag = False
else:
    psutil_get_cpu_percent_tag = True

try:
    # (phy|virt)mem_usage methods only available with PsUtil 0.3.0 or +
    psutil.phymem_usage()
    psutil.virtmem_usage()
except:
    psutil_mem_usage_tag = False
else:
    psutil_mem_usage_tag = True

try:
    # disk_(partitions|usage) methods only available with PsUtil 0.3.0 or +
    psutil.disk_partitions()
    psutil.disk_usage('/')
except:
    psutil_fs_usage_tag = False
else:
    psutil_fs_usage_tag = True

try:
    # disk_io_counters method only available with PsUtil 0.4.0 or +
    psutil.disk_io_counters()
except:
    psutil_disk_io_tag = False
else:
    psutil_disk_io_tag = True

try:
    # network_io_counters method only available with PsUtil 0.4.0 or +
    psutil.network_io_counters()
except:
    psutil_network_io_tag = False
else:
    psutil_network_io_tag = True

try:
    # HTML output
    import jinja2
except ImportError:
    jinja_tag = False
else:
    jinja_tag = True

try:
    # CSV output
    import csv
except ImportError:
    csvlib_tag = False
else:
    csvlib_tag = True


# Classes
#========

class Timer:
    """
    The timer class
    """

    def __init__(self, duration):
        self.started(duration)

    def started(self, duration):
        self.target = time.time() + duration

    def finished(self):
        return time.time() > self.target


class glancesLimits:
    """
    Manage the limit OK,CAREFUL,WARNING,CRITICAL for each stats
    """

    # The limit list is stored in an hash table:
    #  limits_list[STAT] = [ CAREFUL , WARNING , CRITICAL ]
    # Exemple:
    #  limits_list['STD'] = [ 50, 70 , 90 ]

    #_______________________________CAREFUL WARNING CRITICAL
    __limits_list = {
                        'STD':     [50,     70,     90],
                        'LOAD':    [0.7,    1.0,    5.0]
                    }

    def __init__(self, careful=50, warning=70, critical=90):
        self.__limits_list['STD'] = [careful, warning, critical]

    def getSTDCareful(self):
        return self.__limits_list['STD'][0]

    def getSTDWarning(self):
        return self.__limits_list['STD'][1]

    def getSTDCritical(self):
        return self.__limits_list['STD'][2]

    def getLOADCareful(self, core=1):
        return self.__limits_list['LOAD'][0] * core

    def getLOADWarning(self, core=1):
        return self.__limits_list['LOAD'][1] * core

    def getLOADCritical(self, core=1):
        return self.__limits_list['LOAD'][2] * core


class glancesLogs:
    """
    The main class to manage logs inside the Glances software
    Logs is a list of list:
    [["begin", "end", "WARNING|CRITICAL", "CPU|LOAD|MEM",
      MAX, AVG, MIN, SUM, COUNT],...]
    """

    def __init__(self):
        """
        Init the logs classe
        """
        # Maximum size of the logs list
        self.logs_max = 10

        # Init the logs list
        self.logs_list = []

    def get(self):
        """
        Return the logs list (RAW)
        """
        return self.logs_list

    def len(self):
        """
        Return the number of item in the log list
        """
        return self.logs_list.__len__()

    def __itemexist__(self, item_type):
        """
        An item exist in the list if:
        * end is < 0
        * item_type is matching
        """
        for i in range(self.len()):
            if ((self.logs_list[i][1] < 0) and
                (self.logs_list[i][3] == item_type)):
                return i
        return -1

    def add(self, item_state, item_type, item_value):
        """
        item_state = "OK|CAREFUL|WARNING|CRITICAL"
        item_type = "CPU|LOAD|MEM"
        item_value = value
        Item is defined by:
          ["begin", "end", "WARNING|CRITICAL", "CPU|LOAD|MEM",
           MAX, AVG, MIN, SUM, COUNT]
        If item is a 'new one':
          Add the new item at the beginning of the logs list
        Else:
          Update the existing item
        """
        item_index = self.__itemexist__(item_type)
        if (item_index < 0):
            # Item did not exist, add if WARNING or CRITICAL
            if ((item_state == "WARNING") or
                (item_state == "CRITICAL")):
                # Time is stored in Epoch format
                # Epoch -> DMYHMS = datetime.datetime.fromtimestamp(epoch)
                item = []
                item.append(time.mktime(datetime.datetime.now().timetuple()))
                item.append(-1)
                item.append(item_state)     # STATE: WARNING|CRITICAL
                item.append(item_type)      # TYPE: CPU, LOAD, MEM...
                item.append(item_value)     # MAX
                item.append(item_value)     # AVG
                item.append(item_value)     # MIN
                item.append(item_value)     # SUM
                item.append(1)              # COUNT
                self.logs_list.insert(0, item)
                if (self.len() > self.logs_max):
                    self.logs_list.pop()
        else:
            # Item exist, update
            if ((item_state == "OK") or
                (item_state == "CAREFUL")):
                # Close the item
                self.logs_list[item_index][1] = time.mktime(
                datetime.datetime.now().timetuple())
            else:
                # Update the item
                # State
                if (item_state == "CRITICAL"):
                    self.logs_list[item_index][2] = item_state
                # Value
                if (item_value > self.logs_list[item_index][4]):
                    # MAX
                    self.logs_list[item_index][4] = item_value
                elif (item_value < self.logs_list[item_index][6]):
                    # MIN
                    self.logs_list[item_index][6] = item_value
                # AVG
                self.logs_list[item_index][7] += item_value
                self.logs_list[item_index][8] += 1
                self.logs_list[item_index][5] = self.logs_list[item_index][7] \
                                                / self.logs_list[item_index][8]
        return self.len()


class glancesGrabFs:
    """
    Get FS stats
    """

    def __init__(self):
        """
        Init FS stats
        """

        # Ignore the following FS name
        self.ignore_fsname = ('', 'none', 'gvfs-fuse-daemon', 'fusectl', \
                              'cgroup')

        # Ignore the following FS type
        self.ignore_fstype = ('binfmt_misc', 'devpts', 'iso9660', 'none', \
                              'proc', 'sysfs', 'usbfs', 'rootfs', 'autofs', \
                              'devtmpfs')

    def __update__(self):
        """
        Update the stats
        """

        # Reset the list
        self.fs_list = []

        # Open the current mounted FS
        fs_stat = psutil.disk_partitions(True)
        for fs in range(len(fs_stat)):
            fs_current = {}
            fs_current['device_name'] = fs_stat[fs].device
            if fs_current['device_name'] in self.ignore_fsname:
                continue
            fs_current['fs_type'] = fs_stat[fs].fstype
            if fs_current['fs_type'] in self.ignore_fstype:
                continue
            fs_current['mnt_point'] = fs_stat[fs].mountpoint
            try:
                fs_usage = psutil.disk_usage(fs_current['mnt_point'])
            except:
                continue
            fs_current['size'] = fs_usage.total
            fs_current['used'] = fs_usage.used
            fs_current['avail'] = fs_usage.free
            self.fs_list.append(fs_current)

    def get(self):
        self.__update__()
        return self.fs_list


class glancesStats:
    """
    This class store, update and give stats
    """

    def __init__(self):
        """
        Init the stats
        """

        # Init the fs stats
        try:
            self.glancesgrabfs = glancesGrabFs()
        except:
            self.glancesgrabfs = {}

        # Process list refresh
        self.process_list_refresh = True

    def __update__(self):
        """
        Update the stats
        """

        # Host and OS informations
        self.host = {}
        self.host['hostname'] = platform.node()
        self.host['platform'] = platform.architecture()[0]
        self.host['processor'] = platform.processor()
        self.host['os_name'] = platform.system()
        try:
            if (self.host['os_name'] == "Linux"
                or self.host['os_name'] == "FreeBSD"):
                os_version = platform.linux_distribution()
                self.host['os_version'] = os_version[0] + " " + os_version[2] \
                                          + " " + os_version[1]
            elif (self.host['os_name'] == "Windows"):
                os_version = platform.win32_ver()
                self.host['os_version'] = os_version[0] + " " + os_version[2]
            elif (self.host['os_name'] == "Darwin"):
                os_version = platform.mac_ver()
                self.host['os_version'] = os_version[0]
            else:
                self.host['os_version'] = ""
        except:
            self.host['os_version'] = ""

        # CPU
        percent = 0
        try:
            self.cputime_old
        except:
            self.cputime_old = psutil.cpu_times()
            self.cputime_total_old = self.cputime_old.user + \
                                     self.cputime_old.system + \
                                     self.cputime_old.idle
            # Only available on some OS
            try:
                self.cputime_total_old += self.cputime_old.nice
            except:
                pass
            try:
                self.cputime_total_old += self.cputime_old.iowait
            except:
                pass
            try:
                self.cputime_total_old += self.cputime_old.irq
            except:
                pass
            try:
                self.cputime_total_old += self.cputime_old.softirq
            except:
                pass
            self.cpu = {}
        else:
            try:
                self.cputime_new = psutil.cpu_times()
                self.cputime_total_new = self.cputime_new.user + \
                                         self.cputime_new.system + \
                                         self.cputime_new.idle
                # Only available on some OS
                try:
                    self.cputime_total_new += self.cputime_new.nice
                except:
                    pass
                try:
                    self.cputime_total_new += self.cputime_new.iowait
                except:
                    pass
                try:
                    self.cputime_total_new += self.cputime_new.irq
                except:
                    pass
                try:
                    self.cputime_total_new += self.cputime_new.softirq
                except:
                    pass
                percent = 100 / (self.cputime_total_new - \
                                 self.cputime_total_old)
                self.cpu = {'kernel':
                                 (self.cputime_new.system -
                                 self.cputime_old.system)
                                 * percent,
                            'user':
                                 (self.cputime_new.user -
                                 self.cputime_old.user)
                                 * percent,
                            'idle':
                                 (self.cputime_new.idle -
                                 self.cputime_old.idle)
                                 * percent,
                            'nice':
                                 (self.cputime_new.nice -
                                 self.cputime_old.nice)
                                 * percent}
                self.cputime_old = self.cputime_new
                self.cputime_total_old = self.cputime_total_new
            except:
                self.cpu = {}

        # LOAD
        try:
            getload = os.getloadavg()
            self.load = {'min1': getload[0],
                         'min5': getload[1],
                         'min15': getload[2]}
        except:
            self.load = {}

        # MEM
        try:
            # Only for Linux
            cachemem = psutil.cached_phymem() + psutil.phymem_buffers()
        except:
            cachemem = 0
        try:
            phymem = psutil.phymem_usage()
            self.mem = {'cache': cachemem,
                        'total': phymem.total,
                        'free': phymem.free,
                        'used': phymem.used}
        except:
            self.mem = {}
        try:
            virtmem = psutil.virtmem_usage()
            self.memswap = {'total': virtmem.total,
                            'free': virtmem.free,
                            'used': virtmem.used}
        except:
            self.memswap = {}

        # NET
        if psutil_network_io_tag:
            self.network = []
            try:
                self.network_old
            except:
                if (psutil_network_io_tag):
                    self.network_old = psutil.network_io_counters(True)
            else:
                try:
                    self.network_new = psutil.network_io_counters(True)
                except:
                    pass
                else:
                    for net in self.network_new:
                        try:
                            netstat = {}
                            netstat['interface_name'] = net
                            netstat['rx'] = self.network_new[net].bytes_recv - \
                                            self.network_old[net].bytes_recv
                            netstat['tx'] = self.network_new[net].bytes_sent - \
                                            self.network_old[net].bytes_sent
                        except:
                            continue
                        else:
                            self.network.append(netstat)
                    self.network_old = self.network_new

        # DISK I/O
        if psutil_disk_io_tag:
            self.diskio = []
            try:
                self.diskio_old
            except:
                if (psutil_disk_io_tag):
                    self.diskio_old = psutil.disk_io_counters(True)
            else:
                try:
                    self.diskio_new = psutil.disk_io_counters(True)
                except:
                    pass
                else:
                    for disk in self.diskio_new:
                        try:
                            diskstat = {}
                            diskstat['disk_name'] = disk
                            diskstat['read_bytes'] = \
                                self.diskio_new[disk].read_bytes - \
                                self.diskio_old[disk].read_bytes
                            diskstat['write_bytes'] = \
                                self.diskio_new[disk].write_bytes - \
                                self.diskio_old[disk].write_bytes
                        except:
                            continue
                        else:
                            self.diskio.append(diskstat)
                    self.diskio_old = self.diskio_new

        # FILE SYSTEM
        if psutil_fs_usage_tag:
            try:
                self.fs = self.glancesgrabfs.get()
            except:
                self.fs = {}

        # PROCESS
        # Initialiation of the running processes list
        # Data are refreshed every two cycle (refresh_time * 2)
        if (self.process_list_refresh):
            self.process_first_grab = False
            try:
                self.process_all
            except:
                self.process_all = [proc for proc in psutil.process_iter()]
                self.process_first_grab = True
            self.process = []
            self.processcount = {'total': 0, 'running': 0, 'sleeping': 0}
            # Manage new processes
            process_new = [proc.pid for proc in self.process_all]
            for proc in psutil.process_iter():
                if proc.pid not in process_new:
                    self.process_all.append(proc)
            # Grab stats from process list
            for proc in self.process_all[:]:
                try:
                    if (not proc.is_running()):
                        try:
                            self.process_all.remove(proc)
                        except:
                            pass
                except psutil.error.NoSuchProcess:
                    try:
                        self.process_all.remove(proc)
                    except:
                        pass
                else:
                    # Global stats
                    try:
                        self.processcount[str(proc.status)] += 1
                    except psutil.error.NoSuchProcess:
                        # Process non longer exist
                        pass
                    except KeyError:
                        # Key did not exist, create it
                        self.processcount[str(proc.status)] = 1
                    finally:
                        self.processcount['total'] += 1
                    # Per process stats
                    try:
                        procstat = {}
                        procstat['process_name'] = proc.name
                        procstat['proctitle'] = \
                            " " . join(str(i) for i in proc.cmdline)
                        procstat['proc_size'] = proc.get_memory_info().vms
                        procstat['proc_resident'] = proc.get_memory_info().rss
                        if (psutil_get_cpu_percent_tag):
                            procstat['cpu_percent'] = \
                                proc.get_cpu_percent(interval=0)
                        procstat['pid'] = proc.pid
                        procstat['uid'] = proc.username
                        self.process.append(procstat)
                    except:
                        pass
            # If it is the first grab then empty process list
            if (self.process_first_grab):
                self.process = []

        self.process_list_refresh = not self.process_list_refresh

        # Get the current date/time
        self.now = datetime.datetime.now()

        # Get the number of core (CPU) (Used to display load alerts)
        self.core_number = psutil.NUM_CPUS

    def update(self):
        # Update the stats
        self.__update__()

    def getHost(self):
        return self.host

    def getSystem(self):
        return self.host

    def getCpu(self):
        return self.cpu

    def getCore(self):
        return self.core_number

    def getLoad(self):
        return self.load

    def getMem(self):
        return self.mem

    def getMemSwap(self):
        return self.memswap

    def getNetwork(self):
        if psutil_network_io_tag:
            return sorted(self.network, \
                          key=lambda network: network['interface_name'])
        else:
            return 0

    def getDiskIO(self):
        if psutil_disk_io_tag:
            return sorted(self.diskio, key=lambda diskio: diskio['disk_name'])
        else:
            return 0

    def getFs(self):
        if psutil_fs_usage_tag:
            return sorted(self.fs, key=lambda fs: fs['mnt_point'])
        else:
            return 0

    def getProcessCount(self):
        return self.processcount

    def getProcessList(self, sortedby='auto'):
        """
        Return the sorted process list
        """

        sortedReverse = True
        if sortedby == 'auto':
            if (psutil_get_cpu_percent_tag):
                sortedby = 'cpu_percent'
            else:
                sortedby = 'proc_size'
            # Auto selection
            # If global Mem > 70% sort by process size
            # Else sort by CPU comsoption
            try:
                memtotal = (self.mem['used'] - self.mem['cache']) * \
                           100 / self.mem['total']
            except:
                pass
            else:
                if (memtotal > limits.getSTDWarning()):
                    sortedby = 'proc_size'
        elif sortedby == 'process_name':
            sortedReverse = False

        return sorted(self.process, key=lambda process: process[sortedby], \
                      reverse=sortedReverse)

    def getNow(self):
        return self.now


class glancesScreen:
    """
    This class manage the screen (display and key pressed)
    """

    # By default the process list is automatically sorted
    # If global CPU > WANRING => Sorted by process CPU consomption
    # If global used MEM > WARINING => Sorted by process size
    __process_sortedby = 'auto'

    def __init__(self, refresh_time=1):
        # Global information to display
        self.__version = __version__

        # Init windows positions
        self.term_w = 80
        self.term_h = 24
        self.system_x = 0
        self.system_y = 0
        self.cpu_x = 0
        self.cpu_y = 2
        self.load_x = 20
        self.load_y = 2
        self.mem_x = 41
        self.mem_y = 2
        self.network_x = 0
        self.network_y = 7
        self.diskio_x = 0
        self.diskio_y = -1
        self.fs_x = 0
        self.fs_y = -1
        self.process_x = 30
        self.process_y = 7
        self.log_x = 0
        self.log_y = -1
        self.help_x = 0
        self.help_y = 0
        self.now_x = 79
        self.now_y = 3
        self.caption_x = 0
        self.caption_y = 3

        # Init the curses screen
        self.screen = curses.initscr()
        if not self.screen:
            print _("Error: Can not init the curses library.\n")

        curses.start_color()
        if hasattr(curses, 'use_default_colors'):
            try:
                curses.use_default_colors()
            except:
                pass
        if hasattr(curses, 'noecho'):
            try:
                curses.noecho()
            except:
                pass
        if hasattr(curses, 'cbreak'):
            try:
                curses.cbreak()
            except:
                pass
        if hasattr(curses, 'curs_set'):
            try:
                curses.curs_set(0)
            except:
                pass

        # Init colors
        self.hascolors = False
        if (curses.has_colors() and curses.COLOR_PAIRS > 8):
            self.hascolors = True
            # FG color, BG color
            curses.init_pair(1, curses.COLOR_WHITE, -1)
            curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_RED)
            curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_GREEN)
            curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLUE)
            curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_MAGENTA)
            curses.init_pair(6, curses.COLOR_RED, -1)
            curses.init_pair(7, curses.COLOR_GREEN, -1)
            curses.init_pair(8, curses.COLOR_BLUE, -1)
            curses.init_pair(9, curses.COLOR_MAGENTA, -1)
        else:
            self.hascolors = False

        self.title_color = curses.A_BOLD | curses.A_UNDERLINE
        self.help_color = curses.A_BOLD
        if self.hascolors:
            # Colors text styles
            self.no_color = curses.color_pair(1)
            self.default_color = curses.color_pair(3) | curses.A_BOLD
            self.ifCAREFUL_color = curses.color_pair(4) | curses.A_BOLD
            self.ifWARNING_color = curses.color_pair(5) | curses.A_BOLD
            self.ifCRITICAL_color = curses.color_pair(2) | curses.A_BOLD
            self.default_color2 = curses.color_pair(7) | curses.A_BOLD
            self.ifCAREFUL_color2 = curses.color_pair(8) | curses.A_BOLD
            self.ifWARNING_color2 = curses.color_pair(9) | curses.A_BOLD
            self.ifCRITICAL_color2 = curses.color_pair(6) | curses.A_BOLD
        else:
            # B&W text styles
            self.no_color = curses.A_NORMAL
            self.default_color = curses.A_NORMAL
            self.ifCAREFUL_color = curses.A_UNDERLINE
            self.ifWARNING_color = curses.A_BOLD
            self.ifCRITICAL_color = curses.A_REVERSE
            self.default_color2 = curses.A_NORMAL
            self.ifCAREFUL_color2 = curses.A_UNDERLINE
            self.ifWARNING_color2 = curses.A_BOLD
            self.ifCRITICAL_color2 = curses.A_REVERSE

        # Define the colors list (hash table) for logged stats
        self.__colors_list = {
            #         CAREFUL WARNING CRITICAL
            'DEFAULT':    self.no_color,
            'OK':        self.default_color,
            'CAREFUL':    self.ifCAREFUL_color,
            'WARNING':    self.ifWARNING_color,
            'CRITICAL':    self.ifCRITICAL_color
        }

        # Define the colors list (hash table) for non logged stats
        self.__colors_list2 = {
            #         CAREFUL WARNING CRITICAL
            'DEFAULT':    self.no_color,
            'OK':        self.default_color2,
            'CAREFUL':    self.ifCAREFUL_color2,
            'WARNING':    self.ifWARNING_color2,
            'CRITICAL':    self.ifCRITICAL_color2
        }

        # What are we going to display
        self.network_tag = psutil_network_io_tag
        self.diskio_tag = psutil_disk_io_tag
        self.fs_tag = psutil_fs_usage_tag
        self.log_tag = True
        self.help_tag = False

        # Init main window
        self.term_window = self.screen.subwin(0, 0)

        # Init refresh time
        self.__refresh_time = refresh_time

        # Catch key pressed with non blocking mode
        self.term_window.keypad(1)
        self.term_window.nodelay(1)
        self.pressedkey = -1

    def setProcessSortedBy(self, sorted):
        self.__process_sortedautoflag = False
        self.__process_sortedby = sorted

    def getProcessSortedBy(self):
        return self.__process_sortedby

    def __autoUnit(self, val):
        """
        Convert val to string and concatenate the good unit
        Exemples:
            960 -> 960
            142948 -> 143K
            560745673 -> 561M
            ...
        """
        symbols = ('K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y')
        prefix = {
                    'Y': 1208925819614629174706176L,
                    'Z': 1180591620717411303424L,
                    'E': 1152921504606846976L,
                    'P': 1125899906842624L,
                    'T': 1099511627776L,
                    'G': 1073741824,
                    'M': 1048576,
                    'K': 1024
                    }
        for key in reversed(symbols):
            if val >= prefix[key]:
                value = float(val) / prefix[key]
                return '%.1f%s' % (value, key)
        return "%s" % val

    def __getAlert(self, current=0, max=100):
        # If current < CAREFUL of max then alert = OK
        # If current > CAREFUL of max then alert = CAREFUL
        # If current > WARNING of max then alert = WARNING
        # If current > CRITICAL of max then alert = CRITICAL
        try:
            (current * 100) / max
        except ZeroDivisionError:
            return 'DEFAULT'

        variable = (current * 100) / max

        if variable > limits.getSTDCritical():
            return 'CRITICAL'
        elif variable > limits.getSTDWarning():
            return 'WARNING'
        elif variable > limits.getSTDCareful():
            return 'CAREFUL'

        return 'OK'

    def __getColor(self, current=0, max=100):
        """
        Return colors for logged stats
        """
        return self.__colors_list[self.__getAlert(current, max)]

    def __getColor2(self, current=0, max=100):
        """
        Return colors for non logged stats
        """
        return self.__colors_list2[self.__getAlert(current, max)]

    def __getCpuAlert(self, current=0, max=100):
        return self.__getAlert(current, max)

    def __getCpuColor(self, current=0, max=100):
        return self.__getColor(current, max)

    def __getLoadAlert(self, current=0, core=1):
        # If current < CAREFUL*core of max then alert = OK
        # If current > CAREFUL*core of max then alert = CAREFUL
        # If current > WARNING*core of max then alert = WARNING
        # If current > CRITICAL*core of max then alert = CRITICAL

        if current > limits.getLOADCritical(core):
            return 'CRITICAL'
        elif current > limits.getLOADWarning(core):
            return 'WARNING'
        elif current > limits.getLOADCareful(core):
            return 'CAREFUL'

        return 'OK'

    def __getLoadColor(self, current=0, core=1):
        return self.__colors_list[self.__getLoadAlert(current, core)]

    def __getMemAlert(self, current=0, max=100):
        return self.__getAlert(current, max)

    def __getMemColor(self, current=0, max=100):
        return self.__getColor(current, max)

    def __getNetColor(self, current=0, max=100):
        return self.__getColor2(current, max)

    def __getFsColor(self, current=0, max=100):
        return self.__getColor2(current, max)

    def __getProcessColor(self, current=0, max=100):
        return self.__getColor2(current, max)

    def __catchKey(self):
        # Get key
        self.pressedkey = self.term_window.getch()

        # Actions...
        if (self.pressedkey == 27) or (self.pressedkey == 113):
            # 'ESC'|'q' > Exit
            end()
        elif (self.pressedkey == 97):
            # 'a' > Sort process list automatically
            self.setProcessSortedBy('auto')
        elif ((self.pressedkey == 99) and psutil_get_cpu_percent_tag):
            # 'c' > Sort process list by CPU usage
            self.setProcessSortedBy('cpu_percent')
        elif ((self.pressedkey == 100) and psutil_disk_io_tag):
            # 'n' > Enable/Disable disk I/O stats
            self.diskio_tag = not self.diskio_tag
        elif ((self.pressedkey == 102) and psutil_fs_usage_tag):
            # 'n' > Enable/Disable fs stats
            self.fs_tag = not self.fs_tag
        elif (self.pressedkey == 104):
            # 'h' > Enable/Disable help
            self.help_tag = not self.help_tag
        elif (self.pressedkey == 108):
            # 'l' > Enable/Disable logs list
            self.log_tag = not self.log_tag
        elif (self.pressedkey == 109):
            # 'm' > Sort process list by Mem usage
            self.setProcessSortedBy('proc_size')
        elif ((self.pressedkey == 110) and psutil_network_io_tag):
            # 'n' > Enable/Disable network stats
            self.network_tag = not self.network_tag
        elif (self.pressedkey == 112):
            # 'p' > Sort process list by Process name
            self.setProcessSortedBy('process_name')

        # Return the key code
        return self.pressedkey

    def end(self):
        # Shutdown the curses window
        curses.echo()
        curses.nocbreak()
        curses.curs_set(1)
        curses.endwin()

    def display(self, stats):
        # Display stats
        self.displaySystem(stats.getHost(), stats.getSystem())
        self.displayCpu(stats.getCpu())
        self.displayLoad(stats.getLoad(), stats.getCore())
        self.displayMem(stats.getMem(), stats.getMemSwap())
        network_count = self.displayNetwork(stats.getNetwork())
        diskio_count = self.displayDiskIO(stats.getDiskIO(), \
                                          self.network_y + network_count)
        fs_count = self.displayFs(stats.getFs(), \
                                  self.network_y + network_count + \
                                  diskio_count)
        log_count = self.displayLog(self.network_y + network_count + \
                                    diskio_count + fs_count)
        self.displayProcess(stats.getProcessCount(), \
                            stats.getProcessList( \
                                screen.getProcessSortedBy()), log_count)
        self.displayCaption()
        self.displayNow(stats.getNow())
        self.displayHelp()

    def erase(self):
        # Erase the content of the screen
        self.term_window.erase()

    def flush(self, stats):
        # Flush display
        self.erase()
        self.display(stats)

    def update(self, stats):
        # flush display
        self.flush(stats)

        # Wait
        countdown = Timer(self.__refresh_time)
        while (not countdown.finished()):
            # Getkey
            if (self.__catchKey() > -1):
                # flush display
                self.flush(stats)
            # Wait 100ms...
            curses.napms(100)

    def displaySystem(self, host, system):
        # System information
        if (not host or not system):
            return 0
        screen_x = self.screen.getmaxyx()[1]
        screen_y = self.screen.getmaxyx()[0]
        if ((screen_y > self.system_y)
            and (screen_x > self.system_x + 79)):
            system_msg = host['hostname'] + " (" + \
                         system['os_name'] + " " + \
                         system['platform'] + " " + \
                         system['os_version'] + ")"
            self.term_window.addnstr(self.system_y, \
                                     self.system_x + int(screen_x / 2) - \
                                        len(system_msg) / 2, \
                                     system_msg, \
                                     80)

    def displayCpu(self, cpu):
        # CPU %
        screen_x = self.screen.getmaxyx()[1]
        screen_y = self.screen.getmaxyx()[0]
        if ((screen_y > self.cpu_y + 5)
            and (screen_x > self.cpu_x + 18)):
            self.term_window.addnstr(self.cpu_y, self.cpu_x, _("CPU"), 8, \
                    self.title_color if self.hascolors else curses.A_UNDERLINE)

            if (not cpu):
                self.term_window.addnstr(self.cpu_y + 1, self.cpu_x, \
                                         _("Compute data..."), 15)
                return 0

            self.term_window.addnstr(self.cpu_y, self.cpu_x + 10, \
                                     "%.1f%%" % (100 - cpu['idle']), 8)
            self.term_window.addnstr(self.cpu_y + 1, self.cpu_x, _("User:"), 8)
            self.term_window.addnstr(self.cpu_y + 2, self.cpu_x, \
                                     _("Kernel:"), 8)
            self.term_window.addnstr(self.cpu_y + 3, self.cpu_x, _("Nice:"), 8)

            alert = self.__getCpuAlert(cpu['user'])
            logs.add(alert, "CPU user", cpu['user'])
            self.term_window.addnstr(self.cpu_y + 1, self.cpu_x + 10, \
                            "%.1f" % cpu['user'], 8, self.__colors_list[alert])

            alert = self.__getCpuAlert(cpu['kernel'])
            logs.add(alert, "CPU kernel", cpu['kernel'])
            self.term_window.addnstr(self.cpu_y + 2, self.cpu_x + 10, \
                        "%.1f" % cpu['kernel'], 8, self.__colors_list[alert])

            alert = self.__getCpuAlert(cpu['nice'])
            logs.add(alert, "CPU nice", cpu['nice'])
            self.term_window.addnstr(self.cpu_y + 3, self.cpu_x + 10, \
                            "%.1f" % cpu['nice'], 8, self.__colors_list[alert])

    def displayLoad(self, load, core):
        # Load %
        if (not load):
            return 0
        screen_x = self.screen.getmaxyx()[1]
        screen_y = self.screen.getmaxyx()[0]
        if ((screen_y > self.load_y + 5)
            and (screen_x > self.load_x + 18)):
            self.term_window.addnstr(self.load_y, self.load_x, \
                                    _("Load"), 8, \
                                    self.title_color if self.hascolors \
                                                     else curses.A_UNDERLINE)
            self.term_window.addnstr(self.load_y, self.load_x + 10, \
                                     str(core) + _("-Core"), 8)
            self.term_window.addnstr(self.load_y + 1, self.load_x, \
                                     _("1 min:"), 8)
            self.term_window.addnstr(self.load_y + 2, self.load_x, \
                                     _("5 mins:"), 8)
            self.term_window.addnstr(self.load_y + 3, self.load_x, \
                                     _("15 mins:"), 8)

            self.term_window.addnstr(self.load_y + 1, self.load_x + 10, \
                                     str(load['min1']), 8)

            alert = self.__getLoadAlert(load['min5'], core)
            logs.add(alert, "LOAD 5-mins", load['min5'])
            self.term_window.addnstr(self.load_y + 2, self.load_x + 10, \
                            str(load['min5']), 8, self.__colors_list[alert])

            alert = self.__getLoadAlert(load['min15'], core)
            logs.add(alert, "LOAD 15-mins", load['min15'])
            self.term_window.addnstr(self.load_y + 3, self.load_x + 10, \
                            str(load['min15']), 8, self.__colors_list[alert])

    def displayMem(self, mem, memswap):
        # MEM
        if (not mem or not memswap):
            return 0
        screen_x = self.screen.getmaxyx()[1]
        screen_y = self.screen.getmaxyx()[0]
        if ((screen_y > self.mem_y + 5)
            and (screen_x > self.mem_x + 38)):
            self.term_window.addnstr(self.mem_y, self.mem_x, _("Mem B"), \
                8, self.title_color if self.hascolors else curses.A_UNDERLINE)
            self.term_window.addnstr(self.mem_y, self.mem_x + 10, _("Mem"), 8)
            self.term_window.addnstr(self.mem_y, self.mem_x + 20, _("Swap"), 8)
            self.term_window.addnstr(self.mem_y, self.mem_x + 30, _("Real"), 8)
            self.term_window.addnstr(self.mem_y + 1, self.mem_x, \
                                     _("Total:"), 8)
            self.term_window.addnstr(self.mem_y + 2, self.mem_x, _("Used:"), 8)
            self.term_window.addnstr(self.mem_y + 3, self.mem_x, _("Free:"), 8)

            self.term_window.addnstr(self.mem_y + 1, self.mem_x + 10, \
                                     self.__autoUnit(mem['total']), 8)
            self.term_window.addnstr(self.mem_y + 2, self.mem_x + 10, \
                                     self.__autoUnit(mem['used']), 8)
            self.term_window.addnstr(self.mem_y + 3, self.mem_x + 10, \
                                     self.__autoUnit(mem['free']), 8)

            alert = self.__getMemAlert(memswap['used'], memswap['total'])
            logs.add(alert, "MEM swap", memswap['used'] / 1048576)
            self.term_window.addnstr(self.mem_y + 1, self.mem_x + 20, \
                                     self.__autoUnit(memswap['total']), 8)
            self.term_window.addnstr(self.mem_y + 2, self.mem_x + 20, \
                self.__autoUnit(memswap['used']), 8, self.__colors_list[alert])
            self.term_window.addnstr(self.mem_y + 3, self.mem_x + 20, \
                                     self.__autoUnit(memswap['free']), 8)

            alert = self.__getMemAlert(mem['used'] - mem['cache'], \
                                       mem['total'])
            logs.add(alert, "MEM real", (mem['used'] - mem['cache']) / 1048576)
            self.term_window.addnstr(self.mem_y + 1, self.mem_x + 30, "-", 8)
            self.term_window.addnstr(self.mem_y + 2, self.mem_x + 30, \
                                self.__autoUnit((mem['used'] - \
                                                 mem['cache'])), \
                                8, self.__colors_list[alert])
            self.term_window.addnstr(self.mem_y + 3, self.mem_x + 30, \
                                self.__autoUnit((mem['free'] + \
                                                 mem['cache'])), \
                                8)

    def displayNetwork(self, network):
        """
        Display the network interface bitrate
        Return the number of interfaces
        """
        # Network interfaces bitrate
        if (not self.network_tag):
            return 0
        screen_x = self.screen.getmaxyx()[1]
        screen_y = self.screen.getmaxyx()[0]
        if ((screen_y > self.network_y + 3)
            and (screen_x > self.network_x + 28)):
            # Network interfaces bitrate
            self.term_window.addnstr(self.network_y, self.network_x, \
                    _("Net rate"), 8, \
                    self.title_color if self.hascolors else curses.A_UNDERLINE)
            self.term_window.addnstr(self.network_y, self.network_x + 10, \
                    _("Rx/ps"), 8)
            self.term_window.addnstr(self.network_y, self.network_x + 20, \
                    _("Tx/ps"), 8)

            # If there is no data to display...
            if (not network):
                self.term_window.addnstr(self.network_y + 1, self.network_x, \
                                         _("Compute data..."), 15)
                return 3

            # Adapt the maximum interface to the screen
            ret = 2
            for i in range(0, min(screen_y - self.network_y - 3, \
                                  len(network))):
                elapsed_time = max(1, self.__refresh_time)
                self.term_window.addnstr(self.network_y + 1 + i, \
                                         self.network_x, \
                                         network[i]['interface_name'] + ':', 8)
                self.term_window.addnstr(self.network_y + 1 + i, \
                                         self.network_x + 10, \
                                         self.__autoUnit(network[i]['rx'] / \
                                            elapsed_time * 8) + "b", 8)
                self.term_window.addnstr(self.network_y + 1 + i, \
                                         self.network_x + 20, \
                                         self.__autoUnit(network[i]['tx'] / \
                                            elapsed_time * 8) + "b", 8)
                ret = ret + 1
            return ret
        return 0

    def displayDiskIO(self, diskio, offset_y=0):
        # Disk input/output rate
        if (not self.diskio_tag):
            return 0
        screen_x = self.screen.getmaxyx()[1]
        screen_y = self.screen.getmaxyx()[0]
        self.diskio_y = offset_y
        if ((screen_y > self.diskio_y + 3)
            and (screen_x > self.diskio_x + 28)):
            self.term_window.addnstr(self.diskio_y, \
                self.diskio_x, \
                _("Disk I/O"), 8, \
                self.title_color if self.hascolors else curses.A_UNDERLINE)
            self.term_window.addnstr(self.diskio_y, self.diskio_x + 10, \
                _("In/ps"), 8)
            self.term_window.addnstr(self.diskio_y, self.diskio_x + 20, \
                _("Out/ps"), 8)

            # If there is no data to display...
            if (not diskio):
                self.term_window.addnstr(self.diskio_y + 1, self.diskio_x, \
                    _("Compute data..."), 15)
                return 3

            # Adapt the maximum disk to the screen
            disk = 0
            for disk in range(0, min(screen_y - self.diskio_y - 3, \
                                     len(diskio))):
                elapsed_time = max(1, self.__refresh_time)
                self.term_window.addnstr(self.diskio_y + 1 + disk, \
                    self.diskio_x, diskio[disk]['disk_name'] + ':', 8)
                self.term_window.addnstr(self.diskio_y + 1 + disk, \
                    self.diskio_x + 10, \
                    self.__autoUnit(diskio[disk]['write_bytes'] / \
                                    elapsed_time) + "B", \
                    8)
                self.term_window.addnstr(self.diskio_y + 1 + disk, \
                    self.diskio_x + 20, \
                    self.__autoUnit(diskio[disk]['read_bytes'] / \
                                    elapsed_time) + "B", \
                    8)
            return disk + 3
        return 0

    def displayFs(self, fs, offset_y=0):
        # Filesystem stats
        if (not fs or not self.fs_tag):
            return 0
        screen_x = self.screen.getmaxyx()[1]
        screen_y = self.screen.getmaxyx()[0]
        self.fs_y = offset_y
        if ((screen_y > self.fs_y + 3)
            and (screen_x > self.fs_x + 28)):
            self.term_window.addnstr(self.fs_y, self.fs_x, \
                _("Mount B"), 8, \
                self.title_color if self.hascolors else curses.A_UNDERLINE)
            self.term_window.addnstr(self.fs_y, self.fs_x + 10, _("Total"), 8)
            self.term_window.addnstr(self.fs_y, self.fs_x + 20, _("Used"), 8)
            # Adapt the maximum disk to the screen
            mounted = 0
            for mounted in range(0, min(screen_y - self.fs_y - 3, len(fs))):
                self.term_window.addnstr(self.fs_y + 1 + mounted, \
                    self.fs_x, fs[mounted]['mnt_point'], 8)
                self.term_window.addnstr(self.fs_y + 1 + mounted, \
                    self.fs_x + 10, self.__autoUnit(fs[mounted]['size']), 8)
                self.term_window.addnstr(self.fs_y + 1 + mounted, \
                    self.fs_x + 20, self.__autoUnit(fs[mounted]['used']), 8, \
                    self.__getFsColor(fs[mounted]['used'], \
                                      fs[mounted]['size']))
            return mounted + 3
        return 0

    def displayLog(self, offset_y=0):
        # Logs
        if ((logs.len() == 0) or not self.log_tag):
            return 0
        screen_x = self.screen.getmaxyx()[1]
        screen_y = self.screen.getmaxyx()[0]
        self.log_y = offset_y
        if ((screen_y > self.log_y + 3)
            and (screen_x > self.log_x + 79)):
            self.log_y = max(offset_y, \
                             screen_y - 3 - min(offset_y - 3, \
                                                screen_y - self.log_y, \
                                                logs.len()))
            logtodisplay_count = min(screen_y - self.log_y - 3, logs.len())
            logmsg = _("Warning and Critical logs for CPU|LOAD|MEM")
            if (logtodisplay_count > 1):
                logmsg += _(" (lasts ") + str(logtodisplay_count) + \
                          _(" entries)")
            else:
                logmsg += _(" (one entry)")
            self.term_window.addnstr(self.log_y, self.log_x, logmsg, 79, \
                    self.title_color if self.hascolors else curses.A_UNDERLINE)
            # Adapt the maximum log to the screen
            logcount = 0
            log = logs.get()
            for logcount in range(0, logtodisplay_count):
                logmsg = "  " + \
                         str(datetime.datetime.fromtimestamp(log[logcount][0]))
                if (log[logcount][1] > 0):
                    logmark = ' '
                    logmsg += " > " + \
                        str(datetime.datetime.fromtimestamp(log[logcount][1]))
                else:
                    logmark = '~'
                    logmsg += " > " + "%19s" % "___________________"
                logmsg += " " + log[logcount][3] + \
                    " (%.1f/" % log[logcount][6] + \
                    "%.1f/" % log[logcount][5] + "%.1f)" % log[logcount][4]
                self.term_window.addnstr(self.log_y + 1 + logcount, \
                                         self.log_x, logmsg, 79)
                self.term_window.addnstr(self.log_y + 1 + logcount, \
                                         self.log_x, logmark, 1, \
                                        self.__colors_list[log[logcount][2]])
            return logcount + 3
        return 0

    def displayProcess(self, processcount, processlist, log_count=0):
        # Process
        if (not processcount):
            return 0
        screen_x = self.screen.getmaxyx()[1]
        screen_y = self.screen.getmaxyx()[0]
        # If there is no (network&diskio&fs) stats
        # then increase process window
        if (not self.network_tag and not self.diskio_tag and not self.fs_tag):
            process_x = 0
        else:
            process_x = self.process_x
        # Display the process summary
        if ((screen_y > self.process_y + 3)
            and (screen_x > process_x + 48)):
            # Processes sumary
            self.term_window.addnstr(self.process_y, process_x, \
                _("Process"), 8, \
                self.title_color if self.hascolors else curses.A_UNDERLINE)
            self.term_window.addnstr(self.process_y, process_x + 10, \
                _("Total"), 8)
            self.term_window.addnstr(self.process_y, process_x + 20, \
                _("Running"), 8)
            self.term_window.addnstr(self.process_y, process_x + 30, \
                _("Sleeping"), 8)
            self.term_window.addnstr(self.process_y, process_x + 40, \
                _("Other"), 8)
            self.term_window.addnstr(self.process_y + 1, process_x, \
                _("Number:"), 8)
            self.term_window.addnstr(self.process_y + 1, process_x + 10, \
                str(processcount['total']), 8)
            self.term_window.addnstr(self.process_y + 1, process_x + 20, \
                str(processcount['running']), 8)
            self.term_window.addnstr(self.process_y + 1, process_x + 30, \
                str(processcount['sleeping']), 8)
            self.term_window.addnstr(self.process_y + 1, process_x + 40, \
                str(processcount['total'] - \
                    stats.getProcessCount()['running'] - \
                    stats.getProcessCount()['sleeping']), \
                8)
        # Display the process detail
        tag_pid = tag_uid = False
        if (screen_x > process_x + 55):
            tag_pid = True
        if (screen_x > process_x + 64):
            tag_uid = True
        if ((screen_y > self.process_y + 8)
            and (screen_x > process_x + 49)):
            # Processes detail
            self.term_window.addnstr(self.process_y + 3, process_x, \
                _("CPU %"), 5, \
                curses.A_UNDERLINE \
                    if (self.getProcessSortedBy() == 'cpu_percent') else 0)
            self.term_window.addnstr(self.process_y + 3, process_x + 7,  \
                _("Mem virt."), 9, \
                curses.A_UNDERLINE \
                    if (self.getProcessSortedBy() == 'proc_size') else 0)
            self.term_window.addnstr(self.process_y + 3, process_x + 18, \
                _("Mem resi."), 9)
            process_name_x = 30
            # If screen space (X) is available then:
            # 1) Add PID
            if (tag_pid):
                self.term_window.addnstr(self.process_y + 3, process_x + process_name_x, \
                    _("PID"), 6 )
                process_name_x = process_name_x + 8
            # 2) Add UID
            if (tag_uid):
                self.term_window.addnstr(self.process_y + 3, process_x + process_name_x, \
                    _("UID"), 8 )
                process_name_x = process_name_x + 10
            # 3) Process name
            self.term_window.addnstr(self.process_y + 3, process_x + process_name_x, \
                _("Process name"), 12, \
                curses.A_UNDERLINE \
                    if (self.getProcessSortedBy() == 'process_name') else 0)

            # If there is no data to display...
            if (not processlist):
                self.term_window.addnstr(self.process_y + 4, self.process_x, \
                    _("Compute data..."), 15)
                return 6

            for processes in range(0, min(screen_y - self.term_h + \
                            self.process_y - log_count + 4, len(processlist))):
                if (psutil_get_cpu_percent_tag):
                    self.term_window.addnstr(self.process_y + 4 + processes, \
                        process_x, \
                        "%.1f" % processlist[processes]['cpu_percent'], \
                        8, \
                        self.__getProcessColor( \
                            processlist[processes]['cpu_percent']))
                else:
                    self.term_window.addnstr(self.process_y + 4 + processes, \
                        process_x, "N/A", 8)
                self.term_window.addnstr(self.process_y + 4 + processes, \
                    process_x + 7, \
                    self.__autoUnit(processlist[processes]['proc_size']), 9)
                self.term_window.addnstr(self.process_y + 4 + processes, \
                    process_x + 18, \
                    self.__autoUnit(\
                        processlist[processes]['proc_resident']), 9)
                # If screen space (X) is available then:
                # 1) Add PID
                if (tag_pid):
                    self.term_window.addnstr(self.process_y + 4 + processes, \
                        process_x + 30, \
                        str(processlist[processes]['pid']), 6)                    
                # 2) Add UID
                if (tag_uid):
                    self.term_window.addnstr(self.process_y + 4 + processes, \
                        process_x + 38, \
                        str(processlist[processes]['uid']), 8)                    
                # 3) Display long process command line
                maxprocessname = screen_x - process_x - process_name_x
                if ((len(processlist[processes]['proctitle']) > maxprocessname)
                   or (len(processlist[processes]['proctitle']) == 0)):
                    processname = processlist[processes]['process_name']
                else:
                    processname = processlist[processes]['proctitle']
                self.term_window.addnstr(self.process_y + 4 + processes, \
                    process_x + process_name_x, processname, maxprocessname)

    def displayCaption(self):
        # Caption
        screen_x = self.screen.getmaxyx()[1]
        screen_y = self.screen.getmaxyx()[0]
        msg = _("Glances ") + __version__
        if ((screen_x > 79) and (screen_y > 23)):
            # Help can only be displayed on a 80x24 console
            msg = msg + " - " + _("Press 'h' for help")
        if ((screen_y > self.caption_y)
            and (screen_x > self.caption_x + 32)):
            self.term_window.addnstr(max(self.caption_y, screen_y - 1), \
                self.caption_x, msg, self.default_color)

    def displayHelp(self):
        """
        Show the help panel
        """
        if (not self.help_tag):
            return 0
        screen_x = self.screen.getmaxyx()[1]
        screen_y = self.screen.getmaxyx()[0]
        if ((screen_y > self.help_y + 23)
            and (screen_x > self.help_x + 79)):
            # Console 80x24 is mandatory to display the help message
            self.erase()

            self.term_window.addnstr(self.help_y, self.help_x, \
                _("Glances v") + self.__version + _(" user guide"), \
                79, self.title_color if self.hascolors else 0)

            self.term_window.addnstr(self.help_y + 2, self.help_x, \
                _("PsUtil version: ") + psutil.__version__, 79)

            self.term_window.addnstr(self.help_y + 4, self.help_x, \
                _("Captions: "), 79)
            self.term_window.addnstr(self.help_y + 4, self.help_x + 10, \
                _("   OK   "), 8, self.default_color)
            self.term_window.addnstr(self.help_y + 4, self.help_x + 18, \
                _("CAREFUL "), 8, self.ifCAREFUL_color)
            self.term_window.addnstr(self.help_y + 4, self.help_x + 26, \
                _("WARNING "), 8, self.ifWARNING_color)
            self.term_window.addnstr(self.help_y + 4, self.help_x + 34, \
                _("CRITICAL"), 8, self.ifCRITICAL_color)

            self.term_window.addnstr(self.help_y + 6, self.help_x, \
                _("Key") + "\t" + _("Function"), 79, \
                self.title_color if self.hascolors else 0)
            self.term_window.addnstr(self.help_y + 7, self.help_x, \
                _("a") + "\t" + _("Sort process list automatically " \
                                  "(need PsUtil v0.2.0 or higher)"), \
                79, self.ifCRITICAL_color2 \
                    if not psutil_get_cpu_percent_tag else 0)
            self.term_window.addnstr(self.help_y + 8, self.help_x, \
                _("c") + "\t" + _("Sort process list by CPU usage " \
                                  "(need PsUtil v0.2.0 or higher)"), \
                79, self.ifCRITICAL_color2 \
                    if not psutil_get_cpu_percent_tag else 0)
            self.term_window.addnstr(self.help_y + 9, self.help_x, \
                _("m") + "\t" + \
                    _("Sort process list by virtual memory usage"), 79)
            self.term_window.addnstr(self.help_y + 10, self.help_x, \
                _("p") + "\t" + _("Sort process list by name"), 79)
            self.term_window.addnstr(self.help_y + 11, self.help_x, \
                _("d") + "\t" + _("Enable/Disable disk I/O stats " \
                                  "(need PsUtil v0.4.0 or higher)"), \
                79, self.ifCRITICAL_color2 if not psutil_disk_io_tag else 0)
            self.term_window.addnstr(self.help_y + 12, self.help_x, \
                _("f") + "\t" + _("Enable/Disable file system stats " \
                                  "(need PsUtil v0.3.0 or higher)"), \
                79, self.ifCRITICAL_color2 if not psutil_fs_usage_tag else 0)
            self.term_window.addnstr(self.help_y + 13, self.help_x, \
                _("n") + "\t" + _("Enable/Disable network stats " \
                                  "(need PsUtil v0.3.0 or higher)"), \
                79, self.ifCRITICAL_color2 if not psutil_network_io_tag else 0)
            self.term_window.addnstr(self.help_y + 14, self.help_x, \
                _("l") + "\t" + _("Enable/Disable log list " \
                                  "(only available if display > 24 lines)"), 79)
            self.term_window.addnstr(self.help_y + 15, self.help_x, \
                _("h") + "\t" + _("Display/Hide help message"), 79)
            self.term_window.addnstr(self.help_y + 16, self.help_x, \
                _("q") + "\t" + \
                    _("Exit from Glances (ESC key and CRTL-C also work)"), 79)

    def displayNow(self, now):
        # Display the current date and time (now...) - Center
        if (not now):
            return 0
        screen_x = self.screen.getmaxyx()[1]
        screen_y = self.screen.getmaxyx()[0]
        if ((screen_y > self.now_y)
            and (screen_x > self.now_x)):
            now_msg = now.strftime(_("%Y-%m-%d %H:%M:%S"))
            self.term_window.addnstr(max(self.now_y, screen_y - 1), \
                max(self.now_x, screen_x - 1) - len(now_msg), now_msg, \
                len(now_msg))


class glancesHtml:
    """
    This class manages the HTML output
    """

    def __init__(self, htmlfolder="/usr/share", refresh_time=1):
        # Global information to display

        # Init refresh time
        self.__refresh_time = refresh_time

        # Set the templates path
        environment = jinja2.Environment( \
            loader=jinja2.FileSystemLoader(htmlfolder + '/html'), \
            extensions=['jinja2.ext.loopcontrols'])

        # Open the template
        self.template = environment.get_template('default.html')

        # Define the colors list (hash table) for logged stats
        self.__colors_list = {
            #         CAREFUL WARNING CRITICAL
            'DEFAULT':    "bgcdefault fgdefault",
            'OK':        "bgcok fgok",
            'CAREFUL':    "bgccareful fgcareful",
            'WARNING':    "bgcwarning fgcwarning",
            'CRITICAL':    "bgcritical fgcritical"
        }

    def __getAlert(self, current=0, max=100):
        # If current < CAREFUL of max then alert = OK
        # If current > CAREFUL of max then alert = CAREFUL
        # If current > WARNING of max then alert = WARNING
        # If current > CRITICAL of max then alert = CRITICAL
        try:
            (current * 100) / max
        except ZeroDivisionError:
            return 'DEFAULT'

        variable = (current * 100) / max

        if variable > limits.getSTDCritical():
            return 'CRITICAL'
        elif variable > limits.getSTDWarning():
            return 'WARNING'
        elif variable > limits.getSTDCareful():
            return 'CAREFUL'

        return 'OK'

    def __getColor(self, current=0, max=100):
        """
        Return colors for logged stats
        """
        return self.__colors_list[self.__getAlert(current, max)]

    def __getCpuColor(self, cpu, max=100):
        cpu['user_color'] = self.__getColor(cpu['user'], max)
        cpu['kernel_color'] = self.__getColor(cpu['kernel'], max)
        cpu['nice_color'] = self.__getColor(cpu['nice'], max)
        return cpu

    def __getLoadAlert(self, current=0, core=1):
        # If current < CAREFUL*core of max then alert = OK
        # If current > CAREFUL*core of max then alert = CAREFUL
        # If current > WARNING*core of max then alert = WARNING
        # If current > CRITICAL*core of max then alert = CRITICAL
        if current > limits.getLOADCritical(core):
            return 'CRITICAL'
        elif current > limits.getLOADWarning(core):
            return 'WARNING'
        elif current > limits.getLOADCareful(core):
            return 'CAREFUL'
        return 'OK'

    def __getLoadColor(self, load, core=1):
        load['min1_color'] = \
            self.__colors_list[self.__getLoadAlert(load['min1'], core)]
        load['min5_color'] = \
            self.__colors_list[self.__getLoadAlert(load['min5'], core)]
        load['min15_color'] = \
            self.__colors_list[self.__getLoadAlert(load['min15'], core)]
        return load

    def __getMemColor(self, mem):
        mem['used_color'] = self.__getColor(mem['used'] - mem['cache'], \
                                            mem['total'])
        return mem

    def __getMemSwapColor(self, memswap):
        memswap['used_color'] = self.__getColor(memswap['used'], \
                                                memswap['total'])
        return memswap

    def __getFsColor(self, fs):
        mounted = 0
        for mounted in range(0, len(fs)):
            fs[mounted]['used_color'] = self.__getColor(fs[mounted]['used'], \
                                                        fs[mounted]['size'])
        return fs

    def update(self, stats):
        if (stats.getCpu()):
            # Open the output file
            f = open('glances.html', 'w')

            # Process color

            # Render it
            # HTML Refresh is set to 1.5 * refresh_time
            # ... to avoid display while page rendering
            data = self.template.render(\
                refresh=int(self.__refresh_time * 1.5), \
                host=stats.getHost(), \
                system=stats.getSystem(), \
                cpu=self.__getCpuColor(stats.getCpu()), \
                load=self.__getLoadColor(stats.getLoad(), stats.getCore()), \
                core=stats.getCore(), \
                mem=self.__getMemColor(stats.getMem()), \
                memswap=self.__getMemSwapColor(stats.getMemSwap()), \
                net=stats.getNetwork(), \
                diskio=stats.getDiskIO(), \
                fs=self.__getFsColor(stats.getFs()), \
                proccount=stats.getProcessCount(), \
                proclist=stats.getProcessList())

            # Write data into the file
            f.write(data)

            # Close the file
            f.close()


class glancesCsv:
    """
    This class manages the Csv output
    """
    
    def __init__(self, cvsfile="./glances.csv", refresh_time=1):
        # Global information to display

        # Init refresh time
        self.__refresh_time = refresh_time

        # Set the ouput (CSV) path
        try:
            self.__cvsfile_fd = open("%s" % cvsfile, "wb")
            self.__csvfile = csv.writer(self.__cvsfile_fd)
        except IOError, error:
            print "Can not create the output CSV file: ", error[1]
            sys.exit(0)

    def exit(self):
        self.__cvsfile_fd.close()

    def update(self, stats):
        if (stats.getCpu()):
            # Update CSV with the CPU stats
            cpu = stats.getCpu()
            self.__csvfile.writerow(["cpu", cpu['user'], \
                                     cpu['kernel'], cpu['nice']])
        if (stats.getLoad()):
            # Update CSV with the LOAD stats
            load = stats.getLoad()
            self.__csvfile.writerow(["load", load['min1'], \
                                     load['min5'], load['min15']])
        if (stats.getMem() and stats.getMemSwap()):
            # Update CSV with the MEM stats
            mem = stats.getMem()
            self.__csvfile.writerow(["mem", mem['total'], \
                                     mem['used'], mem['free']])
            memswap = stats.getMemSwap()
            self.__csvfile.writerow(["swap", memswap['total'], \
                                     memswap['used'], memswap['free']])
        self.__cvsfile_fd.flush()

# Global def
#===========


def printVersion():
    print _("Glances version ") + __version__


def printSyntax():
    printVersion()
    print _("Usage: glances [-f file] [-o output] [-t sec] [-h] [-v]")
    print ""
    print _("\t-d\t\tDisable Disk I/O module")
    print _("\t-f file\t\tSet the output folder (HTML) or file (CSV)")
    print _("\t-h\t\tDisplay the syntax and exit")
    print _("\t-m\t\tDisable Mount module")    
    print _("\t-n\t\tDisable Net Rate module")    
    print _("\t-o output\tDefine additional output (available: HTML or CSV)")
    print _("\t-t sec\t\tSet the refresh time in second default is %d" \
            % refresh_time)
    print _("\t-v\t\tDisplay the version and exit")
    print ""
    print _("When Glances is running, you can press:")
    print _("'a' to set the automatic mode. " \
            "The processes are sorted automatically")
    print _("'c' to sort the processes list by CPU consumption")
    print _("'d' to disable or enable the disk I/O stats")
    print _("'f' to disable or enable the file system stats")
    print _("'h' to hide or show the help message")
    print _("'l' to hide or show the logs messages")
    print _("'m' to sort the processes list by process size")
    print _("'n' to disable or enable the network interfaces stats")
    print _("'p' to sort the processes list by name")
    print _("'q' to exit")
    print ""


def init():
    global psutil_disk_io_tag, psutil_fs_usage_tag, psutil_network_io_tag
    global limits, logs, stats, screen
    global htmloutput, csvoutput
    global html_tag, csv_tag
    global refresh_time

    # Set default tags
    html_tag = False
    csv_tag = False

    # Set the default refresh time
    refresh_time = 2

    # Manage args
    try:
        opts, args = getopt.getopt(sys.argv[1:], \
                        "dmnho:f:t:v", \
                        ["help", "output", "file", "time", "version"])
    except getopt.GetoptError, err:
        # Print help information and exit:
        print str(err)
        printSyntax()
        sys.exit(2)
    for opt, arg in opts:
        if opt in ("-v", "--version"):
            printVersion()
            sys.exit(0)
        elif opt in ("-o", "--output"):
            if arg == "html":
                if (jinja_tag):
                    html_tag = True
                else:
                    print _("Error: Need Jinja2 library to export into HTML")
                    print
                    print _("Try to install the python-jinja2 package")
                    sys.exit(2)
            elif arg == "csv":
                if (csvlib_tag):
                    csv_tag = True
                else:
                    print _("Error: Need CSV library to export to CSV")
                    sys.exit(2)
            else:
                print _("Error: Unknown output %s" % arg)
                sys.exit(2)
        elif opt in ("-f", "--file"):
            output_file = arg
            output_folder = arg
        elif opt in ("-t", "--time"):
            if int(arg) >= 1:
                refresh_time = int(arg)
            else:
                print _("Error: Refresh time should be a positive integer")
                sys.exit(2)
        elif opt in ("-d", "--diskio"):
            psutil_disk_io_tag = False
        elif opt in ("-m", "--mount"):
            psutil_fs_usage_tag = False
        elif opt in ("-n", "--netrate"):
            psutil_network_io_tag = False
        else:
            printSyntax()
            sys.exit(0)
    
    # Check options
    if (html_tag):
        try:
            output_folder
        except UnboundLocalError:
            print _("Error: HTML export (-o html) need " \
                    "output folder definition (-f <folder>)")
            sys.exit(2)

    if (csv_tag):
        try:
            output_file
        except UnboundLocalError:
            print _("Error: CSV export (-o csv) need " \
                    "output file definition (-f <file>)")
            sys.exit(2)

    # Catch CTRL-C
    signal.signal(signal.SIGINT, signal_handler)

    # Init Limits
    limits = glancesLimits()

    # Init Logs
    logs = glancesLogs()

    # Init stats
    stats = glancesStats()

    # Init HTML output
    if (html_tag):
        htmloutput = glancesHtml(htmlfolder=output_folder, \
                                 refresh_time=refresh_time)

    # Init CSV output
    if (csv_tag):
        csvoutput = glancesCsv(cvsfile=output_file, \
                               refresh_time=refresh_time)

    # Init screen
    screen = glancesScreen(refresh_time=refresh_time)


def main():
    # Init stuff
    init()

    # Main loop
    while True:
        # Get informations from libstatgrab and others...
        stats.update()

        # Update the screen
        screen.update(stats)

        # Update the HTML output
        if (html_tag):
            htmloutput.update(stats)

        # Update the CSV output
        if (csv_tag):
            csvoutput.update(stats)


def end():
    screen.end()
    
    if (csv_tag):
        csvoutput.exit()
    
    sys.exit(0)


def signal_handler(signal, frame):
    end()

# Main
#=====

if __name__ == "__main__":
    main()

# The end...
