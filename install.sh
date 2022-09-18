#!/bin/bash

cd $(dirname $(readlink -f "${BASH_SOURCE[0]}"))

update-alternatives --install /usr/local/bin/lgpio lgpio $PWD/lgpio 40
update-alternatives --install /usr/local/bin/ldto ldtbo $PWD/ldto 40
