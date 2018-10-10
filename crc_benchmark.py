#
#    ICRAR - International Centre for Radio Astronomy Research
#    (c) UWA - The University of Western Australia, 2017
#    Copyright by UWA (in the framework of the ICRAR)
#    All rights reserved
#
#    This library is free software; you can redistribute it and/or
#    modify it under the terms of the GNU Lesser General Public
#    License as published by the Free Software Foundation; either
#    version 2.1 of the License, or (at your option) any later version.
#
#    This library is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#    Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public
#    License along with this library; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston,
#    MA 02111-1307  USA
#

import argparse
import collections
import functools
import itertools
import math
import multiprocessing.sharedctypes
import multiprocessing.pool
import time
import sys
import binascii
import zlib

try:
    import crc32c
except ImportError:
    crc32c = None
try:
    import xxhash
except ImportError:
    xxhash = None

checksum_info = collections.namedtuple('checksum_info', 'name init method final')
checksums = {
    'crc32': checksum_info("binascii's crc32 implementation", lambda: 0, binascii.crc32, lambda x: x & 0xffffffff),
    'crc32z': checksum_info("zlib's crc32 implementation", lambda: 0, zlib.crc32, lambda x: x & 0xffffffff),
    'adler32': checksum_info("zlib's adler32 implementation", lambda: 0, zlib.adler32, lambda x: x & 0xffffffff),
}
if crc32c:
    checksums['crc32c'] = checksum_info("crc32c's crc32c implementation", lambda: 0, crc32c.crc32, lambda x: x & 0xffffffff)
if xxhash:
    def _update_xxhash(x, crc):
        crc.update(x)
        return crc
    checksums['xxhash32'] = checksum_info("xxhash's xxhash32 implementation", xxhash.xxh32, _update_xxhash, lambda x: x.intdigest() & 0xffffffff)

def chunker(seq, size):
    return (seq[pos:pos + size] for pos in range(0, len(seq), size))

def get_checksum(bufsize, data, variant):
    crc_info = checksums[variant]
    crc_method = crc_info.method
    crc = crc_info.init()
    for block in (data[pos:pos + bufsize] for pos in range(0, len(data), bufsize)):
        crc = crc_method(block, crc)
    crc = crc_info.final(crc)
    return crc

def checksum_data(data, bufsize, variant):
    if bufsize == 0:
        start = time.time()
        crc_info = checksums[variant]
        crc = crc_info.final(crc_info.method(data, crc_info.init()))
    else:
        start = time.time()
        crc = get_checksum(bufsize, data, variant)
    return crc, start, time.time() - start

_shmem_val = None
def set_shmem_val(val):
    global _shmem_val
    _shmem_val = val

def _checksum_data_shmem_proc(bufsize, variant, _):
    return checksum_data(_shmem_val, bufsize, variant)

def _checksum_data_proc(data, bufsize, variant, _):
    return checksum_data(data, bufsize, variant)

def mean_and_stddev(x):
    mean = sum(x) / len(x)
    stddev = math.sqrt(sum([(_x - mean) ** 2 for _x in x]) / len(x))
    return mean, stddev

class _serial_pool(object):
    def map(self, f, iterable):
        return [f(i) for i in iterable]

def _get_pool(opts, data, size_mb):
    if opts.threads:
        return multiprocessing.pool.ThreadPool(opts.number_tasks)
    elif opts.processes:
        t0 = time.time()
        shmem_val = multiprocessing.sharedctypes.RawArray('c', len(data))
        t1 = time.time()
        shmem_val.raw = bytes(data)
        del data[:]
        print("\n%.2f [MB] of shared memory created in %.3f [s] and initialized in %.3f [s]" % (size_mb, t1 - t0, time.time() - t1))
        return multiprocessing.Pool(opts.number_tasks, set_shmem_val, (shmem_val,))
    elif opts.processes_copy:
        return multiprocessing.Pool(opts.number_tasks)
    return _serial_pool()

def _get_checksum_function(opts, data, bufsize, variant):
    if opts.processes:
        return functools.partial(_checksum_data_shmem_proc, bufsize, variant)
    elif opts.processes_copy:
        return functools.partial(_checksum_data_proc, data, bufsize, variant)
    return lambda _: checksum_data(data, bufsize, variant)

def do_benchmarking(opts, data):

    size_mb = len(data) / 1024. / 1024
    mechanism = 'serial evaluation(s)'
    if opts.threads:
        mechanism = "thread(s)"
    elif opts.processes or opts.processes_copy:
        mechanism = "process(es)"

    print("Using python: %s" % ('.'.join(map(str, sys.version_info[:3])),))
    print("Checksuming %.2f [MB] using %d %s" % (size_mb, opts.number_tasks, mechanism))
    print("Checksum methods to be tested:")
    for variant, info in checksums.items():
        print(' * %s: %s' % (variant, info.name))

    pool = _get_pool(opts, data, size_mb)
    print("")
    print("Algo     Chksum   Chksum(int) BufSize         Speed [MB/s]       Time [s] Setup Time [s]")
    print("======== ======== =========== ======= ==================== ============== ==============")
    for variant, bufsize_log2 in itertools.product(checksums, list(range(9, 21)) + [0]):

        # bufsize = 0 causes the whole buffer to be processed in one go
        bufsize = 2 ** bufsize_log2 if bufsize_log2 > 0 else 0

        # Go, go, go!
        _checksum_data = _get_checksum_function(opts, data, bufsize, variant)
        t0 = time.time()
        res = pool.map(_checksum_data, range(opts.number_tasks))
        crcs = [x[0] for x in res]
        setup_times = [x[1] - t0 for x in res]
        times = [x[2] for x in res]
        speeds = [size_mb / t for t in times]

        if not all(x == crcs[0] for x in crcs):
            raise Exception("Different checksum results obtained for %s: %r" % (variant, crcs))
        crc = crcs[0]
        mean_time, stddev_time = mean_and_stddev(times)
        mean_setup, stddev_setup = mean_and_stddev(setup_times)
        mean_speed, stddev_speed = mean_and_stddev(speeds)
        args = (variant, crc & 0xffffffff, crc, bufsize, mean_speed,
                stddev_speed, mean_time, stddev_time, mean_setup, stddev_setup)
        print(u"%-8s %08x %11d %-7d %9.3f \u00b1 %8.3f %6.3f \u00b1 %5.3f %6.3f \u00b1 %5.3f" % args)

def main():

    parser = argparse.ArgumentParser(description="Benchmarks the performance of various checksum algorithms")
    parser.add_argument('-n', '--number-tasks', help='# of checksums to perform, defaults to 1', default=1, type=int)
    data = parser.add_mutually_exclusive_group()
    data.add_argument('-f', '--file', help='File contents to checksum. If none given fake data is checksumed', default=None)
    data.add_argument('-m', '--megabytes', help='# megabytes to checksum. Mutually exclusive with -f', default=128, type=int)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('-t', '--threads', help='Use threads for parallel execution', action='store_true', default=False)
    mode.add_argument('-p', '--processes', help='Use processes with shared memory for parallel execution', action='store_true', default=False)
    mode.add_argument('-P', '--processes-copy', help='Like -p, but copying data instead of using shared memory', action='store_true', default=False)
    opts = parser.parse_args()

    if opts.file:
        with open(opts.file, 'rb') as f:
            data = f.read()
            print("Checking file %s (%d bytes)\n" % (opts.file, len(data)))
    else:
        data = b' ' * 1024 * 1024 * opts.megabytes

    if opts.processes:
        # turn it into a modifiable array so we can easily empty it later
        # after copying to the shared memory area
        data = bytearray(data)

    do_benchmarking(opts, data)

if __name__ == '__main__':
    main()
