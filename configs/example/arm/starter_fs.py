# Copyright (c) 2016-2017, 2020 ARM Limited
# All rights reserved.
#
# The license below extends only to copyright in the software and shall
# not be construed as granting a license to any other intellectual
# property including but not limited to intellectual property relating
# to a hardware implementation of the functionality of the software
# licensed hereunder.  You may use the software subject to the license
# terms below provided that you ensure that this notice is replicated
# unmodified and in its entirety in all distributions of the software,
# modified or unmodified, in source code or in binary form.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met: redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer;
# redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution;
# neither the name of the copyright holders nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""This script is the full system example script from the ARM
Research Starter Kit on System Modeling. More information can be found
at: http://www.arm.com/ResearchEnablement/SystemModeling
"""

import os
from pathlib import Path
import m5
from m5.util import addToPath
from m5.objects import *
from m5.options import *
import argparse

m5.util.addToPath('../..')

from common import Options
from common import Simulation
from common import SysPaths
from common import ObjectList
from common import CacheConfig
from common import MemConfig
from common.cores.arm import HPI

import devices


default_kernel = 'vmlinux.arm64'
default_disk = 'linaro-minimal-aarch64.img'
default_root_device = '/dev/vda'
GEM5_UARCH_SUFFIX = 'gem5_uarch'
TAGE_RESTORE_TEMPLATE = 'tage_restore_state.core{core}.json'


# Pre-defined CPU configurations. Each tuple must be ordered as : (cpu_class,
# l1_icache_class, l1_dcache_class, walk_cache_class, l2_Cache_class). Any of
# the cache class may be 'None' if the particular cache is not present.
cpu_types = {

    "atomic" : ( AtomicSimpleCPU, None, None, None, None),
    "minor" : (MinorCPU,
               devices.L1I, devices.L1D,
               devices.WalkCache,
               devices.L2),
    "hpi" : ( HPI.HPI,
              HPI.HPI_ICache, HPI.HPI_DCache,
              HPI.HPI_WalkCache,
              HPI.HPI_L2),
    "ooo" : ( O3CPU,
               devices.L1I, devices.L1D,
               devices.WalkCache,
               devices.L2)
}

def create_cow_image(name):
    """Helper function to create a Copy-on-Write disk image"""
    image = CowDiskImage()
    image.child.image_file = SysPaths.disk(name)

    return image;


def discover_gem5_uarch_dir(restore_dir: Path):
    workload_dir = restore_dir.parent
    snapshot_name = restore_dir.name
    nested = workload_dir / snapshot_name / GEM5_UARCH_SUFFIX
    sibling = workload_dir / f"{snapshot_name}.{GEM5_UARCH_SUFFIX}"

    if nested.is_dir():
        return nested
    if sibling.is_dir():
        return sibling
    return nested


def discover_tage_restore_files(args):
    if not getattr(args, 'restore_tage_state', False):
        return {}

    if not getattr(args, 'restore', None):
        m5.util.warn(
            '--restore-tage-state was set without --restore; '
            'skipping TAGE warm-state import.'
        )
        return {}

    restore_dir = Path(args.restore).resolve()
    gem5_uarch_dir = discover_gem5_uarch_dir(restore_dir)

    if not gem5_uarch_dir.is_dir():
        m5.util.warn(
            f'gem5 uarch restore directory not found: {gem5_uarch_dir}. '
            'Running with a cold TAGE.'
        )
        return {}

    restore_files = {}
    for core in range(getattr(args, 'num_cores', 0)):
        target_path = gem5_uarch_dir / TAGE_RESTORE_TEMPLATE.format(core=core)
        if target_path.is_file():
            restore_files[core] = str(target_path)

    if not restore_files:
        m5.util.warn(
            f'No TAGE restore files were found in {gem5_uarch_dir}. '
            'Running with a cold TAGE.'
        )

    return restore_files


def configure_tage_restore(system, args):
    restore_files = discover_tage_restore_files(args)
    for cluster in getattr(system, 'cpu_cluster', []):
        for cpu in cluster.cpus:
            if (
                not hasattr(cpu, 'branchPred')
                or not hasattr(cpu.branchPred, 'tage')
            ):
                continue

            if cpu.cpu_id in restore_files:
                cpu.branchPred.tage.restoreTageState = True
                cpu.branchPred.tage.tageRestoreFile = restore_files[cpu.cpu_id]
            else:
                cpu.branchPred.tage.restoreTageState = False
                cpu.branchPred.tage.tageRestoreFile = ''


def configure_tage_decision_trace(system, args):
    enabled = bool(getattr(args, 'tage_decision_trace', False))
    limit = int(getattr(args, 'tage_decision_trace_limit', 0))
    for cluster in getattr(system, 'cpu_cluster', []):
        for cpu in cluster.cpus:
            if (
                not hasattr(cpu, 'branchPred')
                or not hasattr(cpu.branchPred, 'tage')
            ):
                continue

            cpu.branchPred.tage.tageDecisionTraceEnable = enabled
            cpu.branchPred.tage.tageDecisionTraceLimit = limit
            cpu.branchPred.tage.tageDecisionTraceFile = (
                os.path.join(
                    m5.options.outdir,
                    f'tage_decision_trace_core_{cpu.cpu_id}.json',
                )
                if enabled
                else ''
            )


def create(args):
    ''' Create and configure the system object. '''

    if args.script and not os.path.isfile(args.script):
        print("Error: Bootscript %s does not exist" % args.script)
        sys.exit(1)

    want_caches = False
    if args.cpu_type == "O3CPU":
        (CPUClass, test_mem_mode, FutureClass) = Simulation.setCPUClass(args)
        print(test_mem_mode)
        cpu_class = CPUClass
        mem_mode = test_mem_mode
        args.cpu = "ooo"
        want_caches = True
    else:
        cpu_class = cpu_types[args.cpu][0]
        mem_mode = cpu_class.memory_mode()
        want_caches = True if mem_mode == "timing" else False

    # Only simulate caches when using a timing CPU (e.g., the HPI model)
    #want_caches = True

    system = devices.SimpleSystem(caches=want_caches,
                                  mem_size = args.mem_size,
                                  mem_mode=mem_mode,
                                  workload=ArmFsLinux(
                                      object_file=
                                      SysPaths.binary(args.kernel)),
                                  readfile=args.script,
                                  m1=args.m1)

    #CacheConfig.config_cache(args, system)
    MemConfig.config_mem(args, system)

    system.realview.vio[0].vio=VirtIOBlock(image=create_cow_image(args.disk_image))
    # Add the PCI devices we need for this system. The base system
    # doesn't have any PCI devices by default since they are assumed
    # to be added by the configuration scripts needing them.
    #system.pci_devices = [
    #    # Create a VirtIO block device for the system's boot
    #    # disk. Attach the disk image using gem5's Copy-on-Write
    #    # functionality to avoid writing changes to the stored copy of
    #    # the disk image.
    #    PciVirtIO(vio=VirtIOBlock(image=create_cow_image(args.disk_image))),
    #]

    ## Attach the PCI devices to the system. The helper method in the
    ## system assigns a unique PCI bus ID to each of the devices and
    ## connects them to the IO bus.
    #for dev in system.pci_devices:
    #    system.attach_pci(dev)

    # Wire up the system's memory system
    system.connect()

    # Add CPU clusters to the system
    system.cpu_cluster = [
        devices.CpuCluster(system,
                           args.num_cores,
                           args.cpu_freq, "1.0V",
                           *cpu_types[args.cpu],
                           l1i_rp=args.l1i_rp,
                           l2_rp=args.l2_rp,
                           preserve_ways=args.preserve_ways,
                           args=args),
    ]

    configure_tage_restore(system, args)
    configure_tage_decision_trace(system, args)

    # Create a cache hierarchy for the cluster. We are assuming that
    # clusters have core-private L1 caches and an L2 that's shared
    # within the cluster.
    system.addCaches(want_caches, last_cache_level=3)

    # Setup gem5's minimal Linux boot loader.
    system.realview.setupBootLoader(system, SysPaths.binary, args.bootloader)
    #system.realview.setupBootLoader(system, SysPaths.binary)

    if args.dtb:
        system.workload.dtb_filename = args.dtb
    else:
        # No DTB specified: autogenerate DTB
        system.workload.dtb_filename = \
            os.path.join(m5.options.outdir, 'system.dtb')
        system.generateDtb(system.workload.dtb_filename)

    # Linux boot command flags
    kernel_cmd = [
        # Tell Linux to use the simulated serial port as a console
        "console=ttyAMA0",
        # Hard-code timi
        "lpj=19988480",
        # Disable address space randomisation to get a consistent
        # memory layout.
        "norandmaps",
        # Tell Linux where to find the root disk image.
        "root=%s" % args.root_device,
        # Mount the root disk read-write by default.
        "rw",
        # Tell Linux about the amount of physical memory present.
        "mem=%s" % args.mem_size,
    ]
    system.workload.command_line = " ".join(kernel_cmd)

    return system

def parse_stats(args):
    stats_file = os.path.join(m5.options.outdir,'stats.txt')
    stats_file_handle = open(stats_file,'r')
    found = False

    warmup_instcount = 5000000
    if args.warmup_insts:
        warmup_instcount = args.warmup_insts
    for line in stats_file_handle:
        if "simInsts" in line:
            toks = line.split()
            inst_count = int(toks[1])
            #print(toks)
            #print(inst_count)
            if(inst_count >= warmup_instcount):
                found = True
                break
    stats_file_handle.close()
    #os.remove(stats_file)
    #with open(stats_file,'w') as fp:
    #    pass
    return found

def run(args):
    cptdir = m5.options.outdir
    if args.checkpoint:
        print("Checkpoint directory: %s" % cptdir)

    if args.warmup_insts:
        while True:
            event = m5.simulate(250000000)
            m5.stats.dump()
            if(parse_stats(args)):
                break

        # Reset stats and prepare to get final stats
        m5.stats.reset()
        m5.stats.outputList.clear()
        m5.stats.addStatVisitor("stats_final.txt")

    while True:
        event = m5.simulate()
        exit_msg = event.getCause()
        if exit_msg == "checkpoint":
            print("Dropping checkpoint at tick %d" % m5.curTick())
            cpt_dir = os.path.join(m5.options.outdir, "cpt.%d" % m5.curTick())
            m5.checkpoint(os.path.join(cpt_dir))
            print("Checkpoint done.")
        else:
            print(exit_msg, " @ ", m5.curTick())
            break

    m5.stats.dump()
    sys.exit(event.getCode())


def main():
    parser = argparse.ArgumentParser(epilog=__doc__)

    parser.add_argument("--dtb", type=str, default=None,
                        help="DTB file to load")
    parser.add_argument("--kernel", type=str, default=default_kernel,
                        help="Linux kernel")
    parser.add_argument("--disk-image", type=str,
                        default=default_disk,
                        help="Disk to instantiate")
    parser.add_argument("--bootloader", type=str,
                        default="boot.arm64",
                        help="bootloader")
    parser.add_argument("--root-device", type=str,
                        default=default_root_device,
                        help="OS device name for root partition (default: {})"
                             .format(default_root_device))
    parser.add_argument("--script", type=str, default="",
                        help = "Linux bootscript")
    parser.add_argument("--cpu", type=str, choices=list(cpu_types.keys()),
                        default="atomic",
                        help="CPU model to use")
    parser.add_argument("--cpu-freq", type=str, default="2GHz")
    parser.add_argument("--m1", default=False, action="store_true")
    parser.add_argument("--opt", default=False, action="store_true")
    parser.add_argument("--numSets", type=int, default=64,
                        help="Number of L1i sets")
    parser.add_argument("--num-cores", type=int, default=1,
                        help="Number of CPU cores")
    #parser.add_argument("--mem-type", default="DDR3_1600_8x8",
    #                    choices=ObjectList.mem_list.get_names(),
    #                    help = "type of memory to use")
    #parser.add_argument("--mem-channels", type=int, default=1,
    #                    help = "number of memory channels")
    #parser.add_argument("--mem-ranks", type=int, default=None,
    #                    help = "number of memory ranks per channel")
    #parser.add_argument("--mem-size", action="store", type=str,
    #                    default="1GB",
    #                    help="Specify the physical memory size")
    parser.add_argument("--checkpoint", action="store_true")
    parser.add_argument("--restore", type=str, default=None)
    parser.add_argument("--branch-trace", action="store_true",
                        help="Enable per-core branch trace logging")
    parser.add_argument("--data-trace", action="store_true",
                        help="Enable per-core data access trace logging")
    parser.add_argument(
        "--restore-tage-state",
        action="store_true",
        help="Restore staged TAGE predictor state when available")
    parser.add_argument(
        "--tage-decision-trace",
        action="store_true",
        help="Emit compact per-conditional TAGE decision logs")
    parser.add_argument(
        "--tage-decision-trace-limit",
        type=int,
        default=0,
        help=(
            "Maximum number of conditional TAGE decisions to log "
            "(0 = unlimited)"
        ))


    Options.addCommonOptions(parser)
    args = parser.parse_args()
    print(args)
    root = Root(full_system=True)
    root.system = create(args)

    if args.restore is not None:
        m5.instantiate(args.restore)
    else:
        m5.instantiate()

    run(args)


if __name__ == "__m5_main__":
    main()
