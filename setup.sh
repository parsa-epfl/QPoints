#!/bin/bash

# TODO: these packages must be installed in the Dockerfile, not here
if command -v apt-get >/dev/null 2>&1; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    SUDO=""
  fi
  $SUDO apt-get update
  $SUDO apt-get remove -y scons
  $SUDO apt-get install -y \
    build-essential \
    bzip2 \
    git \
    libboost-all-dev \
    libprotobuf-dev \
    libsqlite3-dev \
    m4 \
    netcat-openbsd \
    pkg-config \
    sshpass \
    protobuf-compiler \
    gdb-multiarch \
    python3 \
    python3-dev \
    python3-pip \
    python3-jinja2 \
    python3-six \
    qemu-utils \
    vim \
    wget \
    zlib1g-dev
  python3 -m pip install "scons==3.1.2"
  python3 -m pip install --break-system-packages gdown
fi

echo cloning gem5 repo
git clone -b cassandra-issue-fix https://github.com/bgodala/gem5_ARM_FDIP.git  gem5
cp scripts/qflex/gem5_patch/init_signals.cc gem5/src/sim/init_signals.cc 

echo build gem5
cd gem5
scons -j8 build/ARM/gem5.opt CXX=g++ CXXFLAGS="-std=c++17"
cd ..

echo Getting ARM kernel image files for gem5
cd bin/m5
wget http://dist.gem5.org/dist/v22-0/arm/aarch-system-20220707.tar.bz2
tar -xvf aarch-system-20220707.tar.bz2
cd ../../

echo Setup is complete!
