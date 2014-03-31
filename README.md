usbmon_replay
=============

A little Python script for replaying USB traffic from usbmon dumps.

Requirements:
-------------
* Recent( >2.6 ) Linux kernel and distribution
* [The libusb1 package for Python] (https://pypi.python.org/pypi/libusb1)
* Python > 2.6 and < 3
* Probably root access (to open and work with USB devices)

Usage:
-------------
In order for this script to work, you will almost certainly need to provide a filter string. This is used to determine with which of the devices in your capture file you want to communicate. A filter consists of a plus or minus, followed by a list of USB transfer types, which can be any of Co, Ci, Io, Ii, Bo, Bi, Zo, and Zi (Control out and in, Interrupt out and in, Bulk out and in, and Isosyncronous out and in respectively). "-f +Bi" means that a device must have bulk input occur in the dumpfile to be considered. "-f -Bi" means that only devices with *no* bulk input should be considered.

Here is a typical usage string:

<program name> -b -f "+CoCi" -n "canon" mydump.mon

This will search for a device with "canon" (case insensitive) in its description, then parse mydump.mon as a binary file, ignoring any devices that don't contain Co or Ci.
