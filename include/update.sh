#!/bin/sh

if [ -z "$1" ]; then
	echo "$0 LINUX_DIR"
	return 1
fi

for i in $(find dt-bindings -iname "*.h"); do
	echo $i
	if [ -f "$1/include/$i" ]; then
		cp "$1/include/$i" $i
	else
		echo "$i not found..."
	fi
done
