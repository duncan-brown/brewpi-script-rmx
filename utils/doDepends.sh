#!/bin/bash

# Copyright (C) 2018  Lee C. Bussy (@LBussy)

# This file is part of LBussy's BrewPi Tools Remix (BrewPi-Tools-RMX).
#
# BrewPi Script RMX is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# BrewPi Script RMX is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with BrewPi Script RMX. If not, see <https://www.gnu.org/licenses/>.

# These scripts were originally a part of brewpi-script, an installer for
# the BrewPi project. Legacy support (for the very popular Arduino
# controller) seems to have been discontinued in favor of new hardware.

# All credit for the original brewpi-script goes to @elcojacobs,
# @m-mcgowan, @rbrady, @steersbob, @glibersat, @Niels-R and I'm sure
# many more contributors around the world. My apologies if I have
# missed anyone; those were the names listed as contributors on the
# Legacy branch.

# See: 'original-license.md' for notes about the original project's
# license and credits.

############
### Init
############

# Change to current dir (assumed to be in a repo) so we can get the git info
pushd . &> /dev/null || exit 1
cd "$(dirname "$0")" || exit 1 # Move to where the script is
GITROOT="$(git rev-parse --show-toplevel)" &> /dev/null
if [ -z "$GITROOT" ]; then
  echo -e "\nERROR:  Unable to find my repository, did you move this file?"
  popd &> /dev/null || exit 1
  exit 1
fi

############
### Init
############

# Change to current dir (assumed to be in a repo) so we can get the git info
pushd . &> /dev/null || exit 1
cd "$(dirname "$0")" || exit 1 # Move to where the script is
GITROOT="$(git rev-parse --show-toplevel)" &> /dev/null
if [ -z "$GITROOT" ]; then
  echo -e "\nERROR:  Unable to find my repository, did you move this file?"
  popd &> /dev/null || exit 1
  exit 1
fi

# Get project constants
. "$GITROOT/inc/const.inc"

# Get error handling functionality
. "$GITROOT/inc/error.inc"

# Get help and version functionality
. "$GITROOT/inc/asroot.inc"

# Get help and version functionality
. "$GITROOT/inc/help.inc" "$@"

# Network test
. "$GITROOT/inc/nettest.inc"

# Packages to be installed/checked via apt
APTPACKAGES="git arduino-core git-core pastebinit build-essential apache2 libapache2-mod-php php-cli php-common php-cgi php php-mbstring python-dev python-pip python-configobj php-xml"
# nginx packages to be uninstalled via apt if present
NGINXPACKAGES="libgd-tools, fcgiwrap, nginx-doc, ssl-cert, fontconfig-config, fonts-dejavu-core, libfontconfig1, libgd3, libjbig0, libnginx-mod-http-auth-pam, libnginx-mod-http-dav-ext, libnginx-mod-http-echo, libnginx-mod-http-geoip, libnginx-mod-http-image-filter, libnginx-mod-http-subs-filter, libnginx-mod-http-upstream-fair, libnginx-mod-http-xslt-filter, libnginx-mod-mail, libnginx-mod-stream, libtiff5, libwebp6, libxpm4, libxslt1.1, nginx, nginx-common, nginx-full"
# Packages to be installed/check via pip
PIPPACKAGES="pyserial psutil simplejson configobj gitpython"

echo -e "\n***Script $THISSCRIPT starting.***"

############
### Check last apt update date
############

# Run 'apt update' if last run was > 1 week ago
lastUpdate=$(stat -c %Y /var/lib/apt/lists)
nowTime=$(date +%s)
if [ $(($nowTime - $lastUpdate)) -gt 604800 ] ; then
  echo -e "\nLast apt update was over a week ago. Running apt update before updating"
  echo -e "dependencies."
  apt update||die
  echo
fi

############
### Remove php5 packages if installed
############

echo -e "\nChecking for previously installed php5 packages."
# Get list of installed packages
php5packages="$(dpkg --get-selections | awk '{ print $1 }' | grep 'php5')"
if [[ -z "$php5packages" ]] ; then
  echo -e "\nNo php5 packages found."
else
  echo -e "\nFound php5 packages installed.  It is recomended to uninstall all php before"
  echo -e "proceeding as BrewPi requires php7 and will install it during the install"
  read -p "process.  Would you like to clean this up before proceeding?  [Y/n]: " yn  < /dev/tty
  case $yn in
    [Nn]* )
      echo -e "\nUnable to proceed with php5 installed, exiting.";
      exit 1;;
    * )
      php_packages="$(dpkg --get-selections | awk '{ print $1 }' | grep 'php')"
      # Loop through the php5 packages that we've found
      for pkg in ${php_packages,,}; do
        echo -e "\nRemoving '$pkg'.\n"
        sudo apt remove --purge $pkg -y
      done
	  echo -e "\nCleanup of the php environment complete."
      ;;
  esac
fi

############
### Remove nginx packages if installed
############

echo -e "\nChecking for previously installed nginx packages."
# Get list of installed packages
nginxPackage="$(dpkg --get-selections | awk '{ print $1 }' | grep 'nginx')"
if [[ -z "$nginxPackage" ]] ; then
  echo -e "\nNo nginx packages found."
else
  echo -e "\nFound nginx packages installed.  It is recomended to uninstall nginx before"
  echo -e "proceeding as BrewPi requires apache2 and they will conflict with each other."
  read -p "Would you like to clean this up before proceeding?  [Y/n]: " yn  < /dev/tty
  case $yn in
    [Nn]* )
      echo -e "\nUnable to proceed with nginx installed, exiting.";
      exit 1;;
    * )
      # Loop through the php5 packages that we've found
      for pkg in ${NGINXPACKAGES,,}; do
        echo -e "\nRemoving '$pkg'.\n"
        sudo apt remove --purge $pkg -y
      done
	  echo -e "\nCleanup of the nginx environment complete."
      ;;
  esac
fi

############
### Install and update required packages
############

# Now install any necessary packages if they are not installed
echo -e "\nChecking and installing required dependencies via apt."
for pkg in ${APTPACKAGES,,}; do
  pkgOk=$(dpkg-query -W --showformat='${Status}\n' ${pkg,,} | \
    grep "install ok installed")
  if [ -z "$pkgOk" ]; then
    echo -e "\nInstalling '$pkg'.\n"
    apt install ${pkg,,} -y||die
    echo
  fi
done

# Get list of installed packages with upgrade available
upgradesAvail=$(dpkg --get-selections | xargs apt-cache policy {} | \
  grep -1 Installed | sed -r 's/(:|Installed: |Candidate: )//' | \
  uniq -u | tac | sed '/--/I,+1 d' | tac | sed '$d' | sed -n 1~2p)

# Loop through only the required packages and see if they need an upgrade
for pkg in ${APTPACKAGES,,}; do
  if [[ ${upgradesAvail,,} == *"$pkg"* ]]; then
    echo -e "\nUpgrading '$pkg'.\n"
    apt upgrade ${pkg,,} -y||die
    doCleanup=1
  fi
done

# Cleanup if we updated packages
if [ -n "$doCleanup" ]; then
  echo -e "\nCleaning up local repositories."
  apt clean -y||warn
  apt autoclean -y||warn
  apt autoremove --purge -y||warn
else
  echo -e "\nNo apt updates to apply."
fi

# Install any Python packages not installed, update those installed
echo -e "\nChecking and installing required dependencies via pip."
pipcmd='pipInstalled=$(pip list --format=legacy)'
eval "$pipcmd"
pipcmd='pipInstalled=$(echo "$pipInstalled" | cut -f1 -d" ")'
eval "$pipcmd"
for pkg in ${PIPPACKAGES,,}; do
  if [[ ! ${pipInstalled,,} == *"$pkg"* ]]; then
    echo -e "\nInstalling '$pkg'."
    pip install $pkg||die
  else
    echo -e "\nChecking for update to '$pkg'.\n"
    pip install $pkg --upgrade||die
  fi
done

echo -e "\n***Script $THISSCRIPT complete.***"

exit 0
