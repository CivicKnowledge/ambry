#!/usr/bin/env bash


apt-get update
apt-get install -y language-pack-en build-essential make gcc wget curl git
apt-get install -y python python-dev python-pip libffi-dev sqlite3 libsqlite3-dev libpq-dev
apt-get install -y python python-numpy python-scipy
apt-get clean && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Fixes security warnings in later pip installs. The --ignore-installed bit is requred
# because some of the installed packages already exist, but pip 8 refuses to remove
# them because they were installed with distutils.

pip install --upgrade pip && pip install --ignore-installed requests

# Ambry needs a later version, but it gets installed with python
pip install --upgrade setuptools

# I don't actually know why we'd need to do this
#export LANGUAGE=en_US.UTF-8
#export LANG=en_US.UTF-8
#export LC_ALL=en_US.UTF-8
#locale-gen en_US.UTF-8
#dpkg-reconfigure locales

if [ $(getent group ambry) ]; then
  echo "group ambry exists."
else
  groupadd ambry
fi

if getent passwd ubuntu > /dev/null 2>&1; then
    usermod -G ambry ubuntu # ubuntu user is particular to AWS
fi


# Make a fresh install of Ambry
# We're not using pip to install directly because AWS produces compile
# errors if we don't manually install the requirements. 
[ -d /opt/ambry ] && rm -rf /opt/ambry

mkdir -p /opt/ambry

[ -d /opt/ambry ] || mkdir -p /opt/ambry


# If /tmp/ambry exists, it is the development directory, mapped from 
# the host, such as for docker or Vagrant.
if [ -d /tmp/ambry ]; then
    cd /tmp/ambry
else
    git clone https://github.com/CivicKnowledge/ambry.git
    cd /opt/ambry
    cd ambry
fi

# On AWS, gets compile errors in numpy if we don't do this first
pip install -r requirements.txt
python setup.py install

ambry config install -f

pip install git+https://github.com/CivicKnowledge/ambry-admin.git
ambry config installcli ambry_admin

pip install git+https://github.com/CivicKnowledge/ambry-ui.git
ambry config installcli ambry_ui

echo 'source /usr/local/bin/ambry-aliases.sh' >> /root/.bashrc

mkdir -p /var/ambry
chown -R root.ambry  /var/ambry
chmod -R g+rw /var/ambry


# When this script is run for installing vagrant, also install
# runit and the runit services
if [ -d ./vagrant/service ]; then
  apt-get install -y runit
  mkdir -p /etc/sv
  cp -r ../vagrant/service/* /etc/sv

  mkdir -p /var/log/ambry/notebook
  mkdir -p /var/log/ambry/ambryui

  adduser log --system --disabled-password

  chown log /var/log/ambry/ambryui
  chown log /var/log/ambry/notebook

  ln -s /etc/sv/ambryui /etc/service
  ln -s /etc/sv/notebook /etc/service

fi

