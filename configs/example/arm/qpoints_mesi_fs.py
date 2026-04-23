# Copyright (c) 2026 EPFL
# All rights reserved.

"""QPoints ARM full-system configuration for O3 + Ruby MESI_Two_Level."""

import argparse
import os
import sys

import m5
from m5.objects import *
from m5.options import *

m5.util.addToPath("../..")

from common import Options
from common import SysPaths
from ruby import Ruby

import devices


default_kernel = "vmlinux.arm64"
default_disk = "linaro-minimal-aarch64.img"
default_root_device = "/dev/vda"


# Ruby creates the private L1I/L1D caches and the shared L2 LLC, so the
# CpuCluster cache classes are intentionally None.
cpu_types = {
    "ooo": (O3CPU, None, None, None, None),
}


def create_cow_image(name):
    """Create a copy-on-write wrapper around the input disk image."""
    image = CowDiskImage()
    image.child.image_file = SysPaths.disk(name)

    return image


def get_cpus(system):
    cpus = []
    for cluster in system.cpu_cluster:
        cpus.extend(cluster.cpus)
    return cpus


def normalize_args(args):
    """Force the architectural model this config is meant to validate."""
    args.cpu = "ooo"
    args.cpu_type = "O3CPU"
    args.ruby = True

    # QPoints uses --num-cores; Ruby expects --num-cpus.
    args.num_cpus = args.num_cores

    # The target model has one shared L2, acting as the LLC.
    args.num_l2caches = 1
    args.num_dirs = args.mem_channels

    # Keep TAGE/BTB active even if run_gem5.sh omits them initially.
    if args.bp_type is None:
        args.bp_type = "TAGE"
    if args.btb_entries is not None:
        args.btb_entries = int(args.btb_entries)


def config_ruby(system, args):
    cpus = get_cpus(system)

    Ruby.create_system(
        args,
        True,
        system,
        system.iobus,
        system._dma_ports,
        system.realview.bootmem,
        cpus,
    )

    system.ruby.clk_domain = SrcClockDomain(
        clock=args.ruby_clock,
        voltage_domain=system.voltage_domain,
    )


class RubyCpuPortAdapter(object):
    def __init__(self, ruby_port):
        self.cpu_side_ports = ruby_port.in_ports


def connect_system(system):
    system.realview.attachOnChipIO(
        system.iobus,
        dma_ports=system._dma_ports,
        mem_ports=system._mem_ports,
    )
    system.realview.attachIO(system.iobus, dma_ports=system._dma_ports)

    port_idx = 0
    for cluster in system.cpu_cluster:
        for cpu in cluster.cpus:
            cpu.connectAllPorts(
                RubyCpuPortAdapter(system.ruby._cpu_ports[port_idx])
            )
            port_idx += 1


def create(args):
    """Create and configure the target full-system object."""
    if args.script and not os.path.isfile(args.script):
        print("Error: Bootscript %s does not exist" % args.script)
        sys.exit(1)

    cpu_class = cpu_types[args.cpu][0]
    mem_mode = cpu_class.memory_mode()

    system = devices.ArmRubySystem(
        args.mem_size,
        mem_mode=mem_mode,
        workload=ArmFsLinux(object_file=SysPaths.binary(args.kernel)),
        readfile=args.script,
        m1=args.m1,
    )

    system.realview.vio[0].vio = VirtIOBlock(
        image=create_cow_image(args.disk_image)
    )

    system.cpu_cluster = [
        devices.CpuCluster(
            system,
            args.num_cores,
            args.cpu_freq,
            "1.0V",
            *cpu_types[args.cpu],
            l1i_rp=args.l1i_rp,
            l2_rp=args.l2_rp,
            preserve_ways=args.preserve_ways,
            args=args
        ),
    ]

    config_ruby(system, args)
    connect_system(system)

    system.realview.setupBootLoader(system, SysPaths.binary, args.bootloader)

    if args.dtb:
        system.workload.dtb_filename = args.dtb
    else:
        system.workload.dtb_filename = os.path.join(
            m5.options.outdir, "system.dtb"
        )
        system.generateDtb(system.workload.dtb_filename)

    kernel_cmd = [
        "console=ttyAMA0",
        "lpj=19988480",
        "norandmaps",
        "root=%s" % args.root_device,
        "rw",
        "mem=%s" % args.mem_size,
    ]
    system.workload.command_line = " ".join(kernel_cmd)

    return system


def parse_stats(args):
    stats_file = os.path.join(m5.options.outdir, "stats.txt")
    stats_file_handle = open(stats_file, "r")
    found = False

    warmup_instcount = 5000000
    if args.warmup_insts:
        warmup_instcount = args.warmup_insts
    for line in stats_file_handle:
        if "simInsts" in line:
            toks = line.split()
            inst_count = int(toks[1])
            if inst_count >= warmup_instcount:
                found = True
                break
    stats_file_handle.close()

    return found


def run(args):
    cptdir = m5.options.outdir
    if args.checkpoint:
        print("Checkpoint directory: %s" % cptdir)

    if args.warmup_insts:
        while True:
            event = m5.simulate(250000000)
            exit_msg = event.getCause()
            if exit_msg != "simulate() limit reached":
                print(
                    "Warmup terminated before reaching --warmup-insts:",
                    exit_msg,
                    "@",
                    m5.curTick(),
                )
                m5.stats.dump()
                sys.exit(event.getCode())
            m5.stats.dump()
            if parse_stats(args):
                break

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
    parser.add_argument("--disk-image", type=str, default=default_disk,
                        help="Disk to instantiate")
    parser.add_argument("--bootloader", type=str, default="boot.arm64",
                        help="bootloader")
    parser.add_argument("--root-device", type=str, default=default_root_device,
                        help="OS device name for root partition")
    parser.add_argument("--script", type=str, default="",
                        help="Linux bootscript")
    parser.add_argument("--cpu", type=str, choices=list(cpu_types.keys()),
                        default="ooo", help="CPU model to use")
    parser.add_argument("--cpu-freq", type=str, default="2GHz")
    parser.add_argument("--m1", default=False, action="store_true")
    parser.add_argument("--opt", default=False, action="store_true")
    parser.add_argument("--numSets", type=int, default=64,
                        help="Number of L1I sets")
    parser.add_argument("--num-cores", type=int, default=1,
                        help="Number of CPU cores")
    parser.add_argument("--checkpoint", action="store_true")
    parser.add_argument("--restore", type=str, default=None)
    parser.add_argument("--branch-trace", action="store_true",
                        help="Enable per-core branch trace logging")
    parser.add_argument("--data-trace", action="store_true",
                        help="Enable per-core data access trace logging")

    Options.addCommonOptions(parser)
    Ruby.define_options(parser)

    args = parser.parse_args()
    normalize_args(args)
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
