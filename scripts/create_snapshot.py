import argparse
import sys
import os
import re
import shutil
import gzip
from telnetlib import Telnet
import subprocess
import time

import parse_reg_info
import gen_mem_file

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def parse_args():
    parser = argparse.ArgumentParser(description='Script to generate Full System Snapshot to be used with gem5 simulator')

    parser.add_argument('--m1',  default=False,
            action='store_true',
            help='Set this flag if snapshot is collected on m1 mac')

    parser.add_argument('--num-cores', type=int, default=1,
            help='Number of cores for multi core snapshot collection')

    parser.add_argument('--skip-dump',  default=False,
            action='store_true',
            help='Flag to skip the first part of snapshot collection process')

    parser.add_argument('--disk-image',type=str,
            help='Disk image file name (required with --copy-disk-img)')

    parser.add_argument('--dest-dir',type=str, required=True,
            help='Destination directory to save snapshot files')
    parser.add_argument('--monitor-port', type=int, default=45454,
            help='QEMU monitor telnet port (default: 45454)')

    parser.add_argument('--copy-disk-img', default=False,
            action='store_true',
            help='Flag to enable disk image copy')

    args = parser.parse_args()
    if args.copy_disk_img and not args.disk_image:
        parser.error("--disk-image is required when --copy-disk-img is set")
    return args

def extract_addr(inp_byte_str):
  inp_str = inp_byte_str.decode('utf-8')
  toks=inp_str.split('\n')
  addr = toks[1].split()[-1]
  addr = int(addr,base=16)
  addr = addr << 12
  return addr

def extract_value(inp_byte_str):
  #Decode the input byte string
  inp_str = inp_byte_str.decode('utf-8')
  lines=inp_str.split('\n')
  toks = lines[1].split()
  last_tok = toks[-1]
  addr = int(last_tok,base=16)
  return addr

def _resolve_gdb_script_path(script_file):
  base_dir = os.path.dirname(os.path.abspath(__file__))
  template_path = os.path.join(base_dir, 'templates', script_file)
  if os.path.exists(template_path):
    return template_path
  return os.path.join(base_dir, 'gdb_scripts', script_file)

def _run_gdb_script(dest_dir, script_path):
  dest_dir = os.path.abspath(dest_dir)
  script_path = os.path.abspath(script_path)
  subprocess.run(
    ['gdb-multiarch', '-x', script_path],
    cwd=dest_dir,
    check=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    input="quit\ny\n",
  )

def _render_multicore_gdb_script(template_text, thread_id, core_idx):
  script_text = re.sub(r'^thread\s+\S+\s*$', 'thread {}'.format(thread_id),
                       template_text, flags=re.MULTILINE)
  script_text = re.sub(r'^set logging file\s+\S+\s*$',
                       'set logging file reg_info.virtio.{}'.format(core_idx),
                       script_text, flags=re.MULTILINE)
  return script_text

def run_gdb_on_docker(args):
  script_file = 'gdb.script'

  if args.num_cores < 1:
    raise ValueError("num_cores must be >= 1 for snapshots")

  if args.num_cores > 1:
      script_file = 'gdb.script.multi'

  if not args.m1:
    script_file += '.linux'

  if args.num_cores == 1:
    script_path = _resolve_gdb_script_path(script_file)
    _run_gdb_script(args.dest_dir, script_path)
    return

  template_path = _resolve_gdb_script_path(script_file)
  with open(template_path, 'r', encoding='utf-8') as fh:
    template_text = fh.read()

  for core_idx in range(args.num_cores):
    thread_id = 1 + core_idx
    script_text = _render_multicore_gdb_script(template_text, thread_id, core_idx)
    script_name = 'gdb.script.multi.core{}'.format(core_idx)
    script_path = os.path.join(args.dest_dir, script_name)
    with open(script_path, 'w', encoding='utf-8') as fh:
      fh.write(script_text)
    _run_gdb_script(args.dest_dir, script_path)

def copy_base_files(out_dir):
  base_files_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'base_files')
  for name in os.listdir(base_files_dir):
    src = os.path.join(base_files_dir, name)
    dst = os.path.join(out_dir, name)
    if os.path.isdir(src):
      if os.path.exists(dst):
        shutil.rmtree(dst)
      shutil.copytree(src, dst)
    else:
      if name == 'system.physmem.store0.pmem':
        with open(src, 'rb') as fh:
          magic = fh.read(2)
        if magic == b'\x1f\x8b':
          with gzip.open(src, 'rb') as inf, open(dst, 'wb') as outf:
            shutil.copyfileobj(inf, outf)
          continue
      shutil.copy2(src, dst)



def run_gdb_process_test():
  subprocess.run(
          ['gdb-multiarch', '-x', 'gdb.script'],
          stdout=subprocess.PIPE,
          stderr=subprocess.PIPE,
          check=True,
          input=b"quit\ny\n"
          )

def run_gdb_process():
  return subprocess.run(
          ['gdb-multiarch'],
          stdout=subprocess.PIPE,
          stderr=subprocess.PIPE,
          check=True,
          input=(
              b"help\n"
              b"target remote localhost:1234\n"
              b"set pagination off\n"
              b"set logging file reg_info_test.virtio\n"
              b"set logging on\n"
              b"info registers all\n"
              b"set logging off\n"
              b"quit\n"
              b"y\n"
              )
          )

def copy_disk_image(dest_dir, disk_image):
  #Make sure all pending write are writtenback to disc
  subprocess.run(['sync'], check=True)

  #Now copy the image
  shutil.copy2(disk_image, dest_dir)

def move_file_dest_dir(dest_dir, fname):
  if not os.path.exists(fname):
      eprint("{} does not exist".format(fname))
      return
  shutil.move(fname, dest_dir)


def dump_to_file(fname, value_map):
    fh = open(fname,'a')
    for key in value_map.keys():
        fh.write('{} {} {}\n'.format(key, hex(value_map[key]), value_map[key]))

def dump_disk_dev_info(tn, dest_dir, fname):
  out_file = os.path.join(dest_dir, fname)
  fh= open(out_file, 'w')

  tn.write(b"xp /xw 0xa003e40\n")
  inp=tn.read_until(b"(qemu)")
  eprint(inp.decode('utf-8'))
  addr = extract_addr(inp)
  vio_base = hex(addr)
  addr = addr + 0x4002
  addr = hex(addr)
  type(addr)
  tn.write(b"xp /xw "+ addr.encode('ascii') + b"\n")
  inp=tn.read_until(b"(qemu)")

  OFFSET_MASK = ( 1 << 16) - 1
  eprint("offset",inp.decode('utf-8'))
  offset_val = extract_value(inp)
  eprint("offse_val", offset_val)
  offset = offset_val & OFFSET_MASK

  eprint(offset)
  fh.write("vio_base {}\n".format(vio_base))
  fh.write("queue0_offset {}\n".format(offset))

  fh.close()

def collect_snapshot(args):
  host="localhost"
  
  # Hack for M1 Mac
  if args.m1:
    host="host.docker.internal"

  tn = Telnet(host, args.monitor_port)

  inp=tn.read_until(b"(qemu)")
  tn.write(b"stop\n")
  inp=tn.read_until(b"(qemu)")
  tn.write(b"commit all\n")
  inp=tn.read_until(b"(qemu)")

  tn.write(b"commit all\n")
  inp=tn.read_until(b"(qemu)")

  if args.copy_disk_img:
    copy_disk_image(dest_dir = args.dest_dir,
            disk_image = args.disk_image)

  tn.write(bytes(f"dump-guest-memory {args.dest_dir}/physmem.elf\n", 'ascii'))
  inp=tn.read_until(b"(qemu)")


  dump_disk_dev_info(tn, args.dest_dir, "dev.info")

  #Start gdb server
  tn.write(b"gdbserver\n")
  inp=tn.read_until(b"(qemu)")

  #run_gdb_process_test()
  run_gdb_on_docker(args)
  time.sleep(2)
  #move_file_dest_dir(dest_dir = args.dest_dir,
  #        fname = 'reg_info.virtio')

  # Quit QEMU via monitor.
  tn.write(b"quit\n")
  tn.read_until(b"(qemu)", timeout=2)
  tn.close()

def get_elf_skip_bytes(elf_name):
  proc = subprocess.run(
          ['readelf', '-l', elf_name],
          stdout=subprocess.PIPE,
          stderr=subprocess.PIPE,
          check=True,
          text=True)
  for line in proc.stdout.splitlines():
    toks = line.split()
    if toks and toks[0] == 'LOAD':
      return toks[1]
  raise ValueError("No LOAD segment found in {}".format(elf_name))

def process_snapshot(args):
    reg_info_fname = "{}/reg_info.virtio".format(args.dest_dir)
    dev_info_fname = "{}/dev.info".format(args.dest_dir)
    
    skip_bytes = get_elf_skip_bytes('{}/physmem.elf'.format(args.dest_dir))

    reg_info_args = []

    reg_info_args.append('--gdb-reg-info')
    reg_info_args.append(reg_info_fname)

    reg_info_args.append('--dev-info')
    reg_info_args.append(dev_info_fname)

    reg_info_args.append('--num-cores')
    reg_info_args.append(str(args.num_cores))

    reg_info_args.append('--m5-miscreg-info')
    reg_info_args.append('gem5_misc_regs')

    reg_info_args.append('--out-reg-info')
    reg_info_args.append('{}/m5.cpt'.format(args.dest_dir))

    reg_info_args.append('--m5-template')
    if args.m1:
        reg_info_args.append('m5.cpt.gicv2.template')
    else:
        if int(args.num_cores) == 1:
            reg_info_args.append('m5.cpt.template')
        else:
            reg_info_args.append('m5.cpt.multicore.template')

    parse_reg_info.gen_m5cpt(reg_info_args)

    #--skip-bytes=0x470 --input-elf=/scratch/bgodala/qemu_workspace/qemu_local_kernel_build/finagle-http/physmem.elf --out-file=/scratch/bgodala/qemu_workspace/qemu_local_kernel_build/finagle-http/physmem
    #mem_conv_args = ['--skip-bytes=0x830', '--input-elf={}/physmem.elf'.format(args.dest_dir),
    mem_conv_args = ['--skip-bytes={}'.format(skip_bytes), '--input-elf={}/physmem.elf'.format(args.dest_dir),
            '--out-file={}/system.physmem.store1.pmem'.format(args.dest_dir)]

    gen_mem_file.gen_physmem(mem_conv_args)

    #Copy base files
    copy_base_files(out_dir=args.dest_dir)


if __name__ == "__main__":
    args = parse_args()


    if not args.skip_dump:
        if not os.path.exists(args.dest_dir):
            print(f"Destination directory does not exist: {args.dest_dir}", file=sys.stdout)
            sys.exit(1)

        collect_snapshot(args)

    process_snapshot(args)
