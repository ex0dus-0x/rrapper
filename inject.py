""" Attach to a spun-off process and perform all CrashSimulator's business
"""

from __future__ import print_function
import sys
import os
import signal
import json
import traceback

import logging

from syscallreplay import syscall_dict

from syscallreplay import generic_handlers
from syscallreplay import file_handlers
from syscallreplay import kernel_handlers
from syscallreplay import socket_handlers
from syscallreplay import recv_handlers
from syscallreplay import send_handlers
from syscallreplay import time_handlers
from syscallreplay import multiplex_handlers
from syscallreplay import util
from syscallreplay.util import ReplayDeltaError

sys.path.append('posix-omni-parser/')
import Trace

logging.basicConfig(stream=sys.stderr, level=4)


def _kill_parent_process(pid):
    f = open('/proc/' + str(pid) + '/status', 'r')
    for i in f:
        s = i.split()
        if s[0] == 'Tgid:':
            tgid = int(s[1])
    if tgid != pid:
        logging.debug('Got differing tgid {}, killing group'
                      .format(tgid))
        os.kill(tgid, signal.SIGKILL)
    else:
        os.kill(pid, signal.SIGKILL)


def handle_socketcall(syscall_id, syscall_object, entering, pid):
    ''' Validate the subcall (NOT SYSCALL!) id of the socket subcall against
    the subcall name we expect based on the current system call object.  Then,
    hand off responsibility to the appropriate subcall handler.


    '''
    subcall_handlers = {
        ('socket', True): socket_handlers.socket_entry_handler,
        #('socket', False): socket_exit_handler,
        ('accept', True): socket_handlers.accept_subcall_entry_handler,
        ('accept4', True): socket_handlers.accept_subcall_entry_handler,
        #('accept', False): accept_subcall_entry_handler,
        ('bind', True): socket_handlers.bind_entry_handler,
        #('bind', False): bind_exit_handler,
        ('listen', True): socket_handlers.listen_entry_handler,
        #('listen', False): listen_exit_handler,
        ('recv', True): recv_handlers.recv_subcall_entry_handler,
        #('recvfrom', True): recvfrom_subcall_entry_handler,
        ('setsockopt', True): socket_handlers.setsockopt_entry_handler,
        ('send', True): send_handlers.send_entry_handler,
        #('send', False): send_exit_handler,
        ('connect', True): socket_handlers.connect_entry_handler,
        #('connect', False): connect_exit_handler,
        ('getsockopt', True): socket_handlers.getsockopt_entry_handler,
        ## ('sendmmsg', True): sendmmsg_entry_handler,
        #('sendto', True): sendto_entry_handler,
        #('sendto', False): sendto_exit_handler,
        ('shutdown', True): socket_handlers.shutdown_subcall_entry_handler,
        #('recvmsg', True): recvmsg_entry_handler,
        #('recvmsg', False): recvmsg_exit_handler,
        ('getsockname', True): socket_handlers.getsockname_entry_handler,
        ('getpeername', True): socket_handlers.getpeername_entry_handler
    }
    # The subcall id of the socket subcall is located in the EBX register
    # according to our Linux's convention.
    subcall_id = syscallreplay.peek_register(pid, syscallreplay.EBX)
    util.validate_subcall(subcall_id, syscall_object)
    try:
        subcall_handlers[(syscall_object.name, entering)](syscall_id,
                                                          syscall_object,
                                                          pid)
    except KeyError:
        raise NotImplementedError('No handler for socket subcall %s %s',
                                  syscall_object.name,
                                  'entry' if entering else 'exit')


def debug_handle_syscall(pid, syscall_id, syscall_object, entering):
    try:
        handle_syscall(pid, syscall_id, syscall_object, entering)
    except ReplayDeltaError:
        debug_printers = {
            4: file_handlers.write_entry_debug_printer,
            5: file_handlers.open_entry_debug_printer,
            197: file_handlers.fstat64_entry_debug_printer,
            146: file_handlers.writev_entry_debug_printer,
            }
        if syscall_id in debug_printers.keys():
            debug_printers[syscall_id](pid, syscall_id, syscall_object)
        else:
            logging.debug('No debug printer associated with syscall_id')
        raise


def handle_syscall(pid, syscall_id, syscall_object, entering):
    ''' Validate the id of the system call against the name of the system call
    we are expecting based on the current system call object.  Then hand off
    responsiblity to the appropriate subcall handler.
    TODO: cosmetic - Reorder handler entrys numerically


    '''
    logging.debug('Handling syscall')
    # If we are entering a system call, update the number of system calls we
    # have handled
    # System call id 102 corresponds to 'socket subcall'.  This system call is
    # the entry point for code calls the appropriate socketf code based on the
    # subcall id in EBX.
    if syscall_id == 102:
        ## Hand off to code that deals with socket calls and return once that is
        ## complete.  Exceptions will be thrown if something is unsuccessful
        ## that end.  Return immediately after because we don't want our system
        ## call handler code double-handling the already handled socket subcall
        handle_socketcall(syscall_id, syscall_object, entering, pid)
        return
    #logging.debug('Checking syscall against execution')
    forgers = {
        13: time_handlers.time_forger,
        78: time_handlers.gettimeofday_forger,
        265: time_handlers.clock_gettime_forger,
    }
    # if there is a forger registerd, check for a mismatch between the called
    # syscall and the trace syscall -- indicating we need to forge a call that
    # isn't present in the trace
    if syscall_id in forgers.keys():
        if syscall_object.name != syscall_dict.SYSCALLS[syscall_id][4:]:
            forgers[syscall_id](pid)
            return
    util.validate_syscall(syscall_id, syscall_object)

    # We ignore these system calls because they have to do with aspecs of
    # execution that we don't want to try to replay and, at the same time,
    # don't have interesting information that we want to validate with a
    # handler.
    ignore_list = [
        77,   # sys_getrusage
        162,  # sys_nanosleep
        125,  # sys_mprotect
        175,  # sys_rt_sigprocmask
        116,  # sys_sysinfo
        119,  # sys_sigreturn
        126,  # sys_sigprocmask
        186,  # sys_sigaltstack
        252,  # exit_group
        266,  # set_clock_getres
        240,  # sys_futex
        242,  # sys_sched_getaffinity
        243,  # sys_set_thread_area
        311,  # sys_set_robust_list
        340,  # sys_prlimit64
        191,  # !!!!!!!!! sys_getrlimit
        ]
    handlers = {
        ##(8, True): creat_entry_handler,
        #(8, False): check_return_value_exit_handler,
        ## These calls just get their return values checked ####
        ## (9, True): check_return_value_entry_handler,
        ## (9, False): check_return_value_exit_handler,
        #(12, True): syscall_return_success_handler,
        #(39, True): check_return_value_entry_handler,
        #(39, False): check_return_value_exit_handler,
        (10, True): file_handlers.unlink_entry_handler,
        (27, True): generic_handlers.syscall_return_success_handler,
        (43, True): time_handlers.times_entry_handler,
        (45, True): kernel_handlers.brk_entry_handler,
        (45, False): kernel_handlers.brk_exit_handler,
        (60, True): generic_handlers.syscall_return_success_handler,
        (91, True): generic_handlers.check_return_value_entry_handler,
        (91, False): generic_handlers.check_return_value_exit_handler,
        ## (125, True): check_return_value_entry_handler,
        ## (125, False): check_return_value_exit_handler,
        ## mmap2 calls are never replayed. Sometimes we must fix a file
        ## descriptor  in position 4.
        #(20, True): syscall_return_success_handler,
        #(30, True): syscall_return_success_handler,
        (38, True): file_handlers.rename_entry_handler,
        #(38, False): check_return_value_exit_handler,
        (15, True): generic_handlers.syscall_return_success_handler,
        (13, True): time_handlers.time_entry_handler,
        #(27, True): syscall_return_success_handler,
        (5, True): file_handlers.open_entry_handler,
        #(5, False): open_exit_handler,
        #(85, True): readlink_entry_handler,
        #(93, True): ftruncate_entry_handler,
        #(93, False): ftruncate_exit_handler,
        (94, True): file_handlers.fchmod_entry_handler,
        #(94, False): check_return_value_entry_handler,
        #(145, True): readv_entry_handler,
        #(145, False): check_return_value_exit_handler,
        (78, True): time_handlers.gettimeofday_entry_handler,
        (122, True): kernel_handlers.uname_entry_handler,
        (140, True): file_handlers.llseek_entry_handler,
        (140, False): file_handlers.llseek_exit_handler,
        (142, True): multiplex_handlers.select_entry_handler,
        (146, True): file_handlers.writev_entry_handler,
        #(146, False): writev_exit_handler,
        (183, True): file_handlers.getcwd_entry_handler,
        (187, True): send_handlers.sendfile_entry_handler,
        (192, True): kernel_handlers.mmap2_entry_handler,
        (192, False): kernel_handlers.mmap2_exit_handler,
        (196, True): file_handlers.lstat64_entry_handler,
        (197, True): file_handlers.fstat64_entry_handler,
        #(197, False): check_return_value_exit_handler,
        #(42, True): pipe_entry_handler,
        ## (10, True): syscall_return_success_handler,
        #(33, True): syscall_return_success_handler,
        #(199, True): syscall_return_success_handler,
        #(200, True): syscall_return_success_handler,
        #(201, True): syscall_return_success_handler,
        #(202, True): syscall_return_success_handler,
        (4, True): file_handlers.write_entry_handler,
        #(4, False): file_handlers.write_exit_handler,
        (3, True): file_handlers.read_entry_handler,
        #(3, False): check_return_value_exit_handler,
        (6, True): file_handlers.close_entry_handler,
        #(6, False): close_exit_handler,
        (168, True): multiplex_handlers.poll_entry_handler,
        (54, True): kernel_handlers.ioctl_entry_handler,
        #(54, False): ioctl_exit_handler,
        (174, True): kernel_handlers.rt_sigaction_entry_handler,
        (195, True): file_handlers.stat64_entry_handler,
        (207, True): file_handlers.fchown_entry_handler,
        (219, True): generic_handlers.syscall_return_success_handler,
        (220, True): file_handlers.getdents64_entry_handler,
        (221, True): file_handlers.fcntl64_entry_handler,
        #(141, True): getdents_entry_handler,
        #(142, False): getdents_exit_handler,
        #(82, True): select_entry_handler,
        #(196, True): lstat64_entry_handler,
        #(268, True): statfs64_entry_handler,
        #(265, True): clock_gettime_entry_handler,
        #(41, True): dup_entry_handler,
        #(41, False): dup_exit_handler,
        #(150, True): syscall_return_success_handler,
        #(186, True): sigaltstack_entry_handler,
        #(194, True): ftruncate64_entry_handler,
        #(194, False): ftruncate64_entry_handler,
        #(207, False): check_return_value_entry_handler,
        #(209, True): getresuid_entry_handler,
        #(211, True): getresgid_entry_handler,
        #(220, False): getdents64_exit_handler,
        #(228, True): fsetxattr_entry_handler,
        #(228, False): fsetxattr_exit_handler,
        #(231, True): fgetxattr_entry_handler,
        #(231, False): fgetxattr_exit_handler,
        #(234, True): flistxattr_entry_handler,
        #(234, False): flistxattr_entry_handler,
        #(242, True): sched_getaffinity_entry_handler,
        #(243, True): syscall_return_success_handler,
        (254, True): multiplex_handlers.epoll_create_entry_handler,
        (255, True): multiplex_handlers.epoll_ctl_entry_handler,
        (256, True): multiplex_handlers.epoll_wait_entry_handler,
        #(258, True): set_tid_address_entry_handler,
        #(258, False): set_tid_address_exit_handler,
        #(259, True): timer_create_entry_handler,
        #(260, True): timer_settime_entry_handler,
        #(261, True): timer_gettime_entry_handler,
        #(263, True): timer_delete_entry_handler,
        #(265, True): clock_gettime_entry_handler,
        #(271, True): syscall_return_success_handler,
        #(272, True): fadvise64_64_entry_handler,
        #(272, False): check_return_value_exit_handler,
        #(295, True): openat_entry_handler,
        #(295, False): openat_exit_handler,
        #(300, True): fstatat64_entry_handler,
        #(300, False): check_return_value_exit_handler,
        #(301, True): unlinkat_entry_handler,
        #(301, False): check_return_value_exit_handler,
        #(311, True): syscall_return_success_handler,
        (320, True): time_handlers.utimensat_entry_handler,
        #(320, False): check_return_value_exit_handler,
        (328, True): file_handlers.eventfd2_entry_handler,
        #(340, True): prlimit64_entry_handler,
        #(345, True): sendmmsg_entry_handler,
        #(345, False): sendmmsg_exit_handler
        }
    if syscall_id not in ignore_list:
        found = False
        for i in handlers.keys():
            if syscall_id == i[0]:
                found = True
        if not found:
            raise NotImplementedError('Encountered un-ignored syscall {} '
                                      'with no handler: {}({})'
                                      .format('entry' if entering else 'exit',
                                              syscall_id,
                                              syscall_object.name))
        handlers[(syscall_id, entering)](syscall_id, syscall_object, pid)


def parse_backing_files(bfs):
    if bfs[-1] != ';':
        bfs += ';'
    bfs = bfs.split(';')
    bfs = bfs[:-1]
    tmp = {}
    for i in bfs:
        bf = i.split(':')
        tmp[bf[0]] = bf[1]
    return tmp


if __name__ == '__main__':
    with open(sys.argv[1], 'r') as f:
        syscallreplay.injected_state = json.load(f)
    os.remove(sys.argv[1])

    # Configure various locals from the config section of our injected state
    event = syscallreplay.injected_state['config']['event']
    pid = int(syscallreplay.injected_state['config']['pid'])
    rec_pid = syscallreplay.injected_state['config']['rec_pid']
    syscallreplay.injected_state['open_fds'] = syscallreplay.injected_state['open_fds'][rec_pid]
    trace = Trace.Trace(syscallreplay.injected_state['config']['trace_file'])
    syscallreplay.syscalls = trace.syscalls
    syscallreplay.syscall_index = int(syscallreplay.injected_state['config']['trace_start'])
    syscallreplay.syscall_index_end = int(syscallreplay.injected_state['config']['trace_end'])
    if 'mmap_backing_files' in syscallreplay.injected_state['config']:
        syscallreplay.injected_state['config']['mmap_backing_files'] = parse_backing_files(syscallreplay.injected_state['config']['mmap_backing_files'])

    # Requires kernel.yama.ptrace_scope = 0
    # in /etc/sysctl.d/10-ptrace.conf
    # on modern Ubuntu
    logging.debug('Injecting %d', pid)
    syscallreplay.attach(pid)
    syscallreplay.syscall(pid, signal.SIGCONT)
    # We need an additional call to PTRACE_SYSCALL here in order to skip
    # past an rr syscall buffering related injected system call
    syscallreplay.syscall(pid, signal.SIGCONT)
    logging.debug('Continuing %d', pid)
    syscallreplay.entering_syscall = True
    _, status = os.waitpid(pid, 0)
    while not os.WIFEXITED(status):
        syscall_object = syscallreplay.syscalls[syscallreplay.syscall_index]
        try:
            debug_handle_syscall(pid,
                                 syscallreplay.peek_register(pid,
                                                             syscallreplay.ORIG_EAX),
                                 syscall_object,
                                 syscallreplay.entering_syscall)
        except:
            traceback.print_exc()
            print('Failed to complete trace')
            _kill_parent_process(pid)
            sys.exit(1)
        if not syscallreplay.entering_syscall:
            syscallreplay.syscall_index += 1
        syscallreplay.entering_syscall = not syscallreplay.entering_syscall
        syscallreplay.syscall(pid, 0)
        _, status = os.waitpid(pid, 0)
        if syscallreplay.syscall_index == syscallreplay.syscall_index_end:
            print('Completed the trace')
            _kill_parent_process(pid)
            sys.exit(0)
