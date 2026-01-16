#!/bin/bash

echo Creating required directories
mkdir checkpoints

echo cloning gem5 repo
git clone -b cassandra-issue-fix https://github.com/bgodala/gem5_ARM_FDIP.git  gem5

echo Pulling Docker image
docker pull cloudsuitetest/gem5-qpoints
echo done

echo Getting ARM kernel image files for gem5
cd bin/m5
wget http://dist.gem5.org/dist/v22-0/arm/aarch-system-20220707.tar.bz2
tar -xvf aarch-system-20220707.tar.bz2
cd ../../

echo Setup is complete!
