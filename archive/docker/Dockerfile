#FROM arm64v8/ubuntu:latest
FROM ubuntu:24.04

# Update package lists
RUN apt-get update

# Install gdb-multiarch
RUN apt-get install -y gdb-multiarch
RUN apt-get install -y python3
RUN apt-get install -y python3-pip
RUN apt-get install -y qemu-utils
RUN apt-get install -y qemu-system
RUN apt-get install -y python3-jinja2 
RUN pip3 install --break-system-packages gdown 
RUN apt-get install -y vim

# Set the entrypoint to start a shell
WORKDIR /qpoints
ENTRYPOINT ["/bin/bash"]
