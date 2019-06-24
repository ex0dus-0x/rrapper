FROM i386/ubuntu

ENV DEBIAN_FRONTEND noninteractive
ARG RR_BRANCH=spin-off
ARG RRAPPER_BRANCH=master

########################
# Initialization
########################

# get necessary dependencies and cleanup
RUN apt-get update && apt-get -y install \
      ccache cmake make g++-multilib gdb libdw-dev \
      pkg-config coreutils python-pexpect manpages-dev git \
      ninja-build capnproto libcapnp-dev autoconf \
      libpython2.7-dev zlib1g-dev python-pip \
      gawk man libbz2-dev libunwind-dev

# (re)install man pages
RUN rm /etc/dpkg/dpkg.cfg.d/excludes
RUN apt-get install --reinstall -y manpages manpages-dev

# create a new nonroot user
RUN useradd crashsim -m
RUN chown -R crashsim:crashsim /home/crashsim

########################
# Installing modified rr
########################

RUN git clone -b ${RR_BRANCH} https://github.com/pkmoore/rr
WORKDIR rr/

# compile and install the modified strace
RUN MAKEFLAGS="-j$(nproc)" setarch i686 bash -c "cd third-party/strace && ./bootstrap && make && make install"

# compile and install rr
RUN MAKEFLAGS="-j$(nproc)" setarch i686 bash -c "mkdir obj && cd obj && cmake .. && make install"

########################
# Installing rrapper
########################

COPY . /home/crashsim/
WORKDIR /home/crashsim

# install rrdump
RUN pip install ./rrdump

# install requirements.txt
RUN pip install -r requirements.txt

# run setup.py
RUN python setup.py install

########################
# Finalize
########################

USER crashsim

RUN rrinit
CMD ["/bin/bash"]
