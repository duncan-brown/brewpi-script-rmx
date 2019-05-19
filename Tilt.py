#!/usr/bin/python

# Copyright (C) 2019 Lee C. Bussy (@LBussy)

# This file is part of LBussy's BrewPi Tilt Remix (BrewPi-Tilt-RMX).
#
# BrewPi Tilt RMX is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# BrewPi Tilt RMX is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with BrewPi Tilt RMX. If not, see <https://www.gnu.org/licenses/>.

# These scripts were originally a part of brewpi-brewometer, which provided
# support in BrewPi for the Tilt Electronic Hydrometer (formerly Brewometer.)

# Credit for the original brewpi-brewometer goes to @sibowler. @supercow
# then forked that work and released a more "Legacy"-capable version for
# the BrewPi Legacy users. This was an obvious jumping-off point for
# brewpi-tilt-rmx.

# As a derivative work of BrewPi, a project released under the GNU General
# Public License v3.0, this license is attached here giving precedence for
# prior work by the BrewPi team.  Both @sibowler and @supercow have agreed
# to this licensing approach.

import blescan
import sys
import datetime
import time
import os
import bluetooth._bluetooth as bluez
import threading
import thread
import numpy
from scipy.interpolate import interp1d
from scipy import arange, array, exp
import csv
import functools
import ConfigParser

TILT_COLORS = ['Red', 'Green', 'Black',
               'Purple', 'Orange', 'Blue', 'Yellow', 'Pink']

# Default time in seconds to wait before checking config files to see if
# calibration data has changed.
DATA_REFRESH_WINDOW = 60


def extrap1d(interpolator):
    '''
    Extrapolation of configuration points.

    This function is required as the interp1d function doesn't support
    extrapolation in the version of scipy that is currently available on
    the pi.
    '''

    # extrap1d Sourced from sastanin @ StackOverflow:
    # http://stackoverflow.com/questions/2745329/

    xs = interpolator.x
    ys = interpolator.y

    def pointwise(x):
        if x < xs[0]:
            return ys[0]+(x-xs[0])*(ys[1]-ys[0])/(xs[1]-xs[0])
        elif x > xs[-1]:
            return ys[-1]+(x-xs[-1])*(ys[-1]-ys[-2])/(xs[-1]-xs[-2])
        else:
            return interpolator(x)

    def ufunclike(xs):
        return array(map(pointwise, array(xs)))

    return ufunclike


def offsetCalibration(offset, value):
    '''Simple offset calibration if only one point available.'''
    return value + offset


def extrapolationCalibration(extrapolationFunction, value):
    '''Interpolation calibration if >1 calibration point available.'''
    inputValue = [value]
    returnValue = extrapolationFunction(inputValue)
    return returnValue[0]


def noCalibration(value):
    '''Return unconverted argument if no calibration points available.'''
    return value


def median(values):
    '''Returns median of supplied values.'''
    return numpy.median(numpy.array(values))


class TiltValue:
    '''Holds a Tilt reading.'''
    temperature = 0
    gravity = 0
    timestamp = 0

    def __init__(self, temperature, gravity):
        self.temperature = temperature
        self.gravity = gravity
        self.timestamp = datetime.datetime.now()

    def __str__(self):
        return "T: " + str(self.temperature) + " G: " + str(self.gravity)


class Tilt:
    '''
    Manages Tilt values.

    Looks after calibration, storing of values and smoothing of read values.
    '''

    color = ''
    values = None
    lock = None
    averagingPeriod = 0
    medianWindow = 0
    tempCalibrationFunction = None
    gravityCalibrationFunction = None
    calibrationDataTime = {}

    def __init__(self, color, averagingPeriod=0, medianWindow=0):
        self.color = color
        self.lock = threading.Lock()
        self.averagingPeriod = averagingPeriod
        self.medianWindow = medianWindow
        self.values = []
        self.calibrate()
        self.displayedError = False

    def calibrate(self):
        """Load/reload calibration functions."""

        # Check for temperature function. If none, then not changed since
        # last load.
        tempFunction = self.tiltCalibrationFunction(
            "temperature", self.color)
        if (tempFunction is not None):
            self.tempCalibrationFunction = tempFunction

        # Check for gravity function. If none, then not changed since last
        # load.
        gravityFunction = self.tiltCalibrationFunction(
            "gravity", self.color)
        if (gravityFunction is not None):
            self.gravityCalibrationFunction = gravityFunction

    def setValues(self, temperature, gravity):
        """
        Set/add the latest temperature & gravity readings to the store.

        These values will be calibrated before storing if calibration is
        enabled
        """
        with self.lock:
            try:
                self.cleanValues()
                self.calibrate()
                calibratedTemperature = self.tempCalibrationFunction(temperature)
                calibratedGravity = self.gravityCalibrationFunction(gravity)
                self.values.append(TiltValue(
                    calibratedTemperature, calibratedGravity))
            except TypeError:
                if self.displayedError is False:
                    print '\nERROR: Detected a type error, >1 Tilt available? Results will be erratic.'
                    self.displayedError = True

    def getValues(self):
        """
        Returns the temperature & gravity values of the Tilt. 

        This will be the latest read value unless averaging / median has
        been enabled
        """
        with self.lock:
            returnValue = None
            if (len(self.values) > 0):
                if (self.medianWindow == 0):
                    returnValue = self.averageValues()
                else:
                    returnValue = self.medianValues(self.medianWindow)

                self.cleanValues()
        return returnValue

    def averageValues(self):
        """Average all the stored values."""
        returnValue = None
        if (len(self.values) > 0):
            returnValue = TiltValue(0, 0)
            for value in self.values:
                returnValue.temperature += value.temperature
                returnValue.gravity += value.gravity

            # Average values
            returnValue.temperature /= len(self.values)
            returnValue.gravity /= len(self.values)

            # Round values
            returnValue.temperature = returnValue.temperature
            returnValue.gravity = returnValue.gravity
        return returnValue

    def medianValues(self, window=3):
        """
        Use a median method across the stored values to reduce noise.

        window: Smoothing window to apply across the data. If the window
                is less than the dataset size, the window will be moved
                across the dataset taking a median value for each window,
                with the resultant set averaged
        """
        returnValue = None
        # Ensure there are enough values to do a median filter, if not shrink
        # window temporarily
        if (len(self.values) < window):
            window = len(self.values)

        #print "Median filter"
        returnValue = TiltValue(0, 0)

        sidebars = (window - 1) / 2
        medianValueCount = 0

        for i in range(len(self.values)-(window-1)):
            # Work out range of values to do median. At start and end of
            # assessment, need to pad with start and end values.
            medianValues = self.values[i:i+window]
            medianValuesTemp = []
            medianValuesGravity = []

            # Separate out Temp and Gravity values
            for medianValue in medianValues:
                medianValuesTemp.append(medianValue.temperature)
                medianValuesGravity.append(medianValue.gravity)

            # Add the median value to the running total.
            returnValue.temperature += median(medianValuesTemp)
            returnValue.gravity += median(medianValuesGravity)

            # Increase count
            medianValueCount += 1

        # Average values
        returnValue.temperature /= medianValueCount
        returnValue.gravity /= medianValueCount

        # Round values
        returnValue.temperature = returnValue.temperature
        returnValue.gravity = returnValue.gravity

        return returnValue

    def cleanValues(self):
        """
        Clean out stale values that are beyond the desired window.
        """
        nowTime = datetime.datetime.now()

        for value in self.values:
            if ((nowTime - value.timestamp).seconds >= self.averagingPeriod):
                self.values.pop(0)
            else:
                # The list is sorted in chronological order, so once we've hit
                # this condition we can stop searching.
                break

    def tiltCalibrationFunction(self, type, color):
        '''
        Load the calibration settings.

        Loads settings from file and create the calibration functions.
        '''

        returnFunction = noCalibration

        originalValues = []
        actualValues = []
        csvFile = None
        configDir = os.path.dirname(os.path.abspath(__file__)) + "/settings/"
        filename = configDir + type.upper() + "." + color.lower()

        lastChecked = self.calibrationDataTime.get(type + "_checked", 0)
        if ((int(time.time()) - lastChecked) < DATA_REFRESH_WINDOW):
            # Only check every DATA_REFRESH_WINDOW seconds
            return None

        lastLoaded = self.calibrationDataTime.get(type, 0)
        self.calibrationDataTime[type + "_checked"] = int(time.time())

        try:
            if (os.path.isfile(filename)):
                fileModificationTime = os.path.getmtime(filename)
                if (lastLoaded >= fileModificationTime):
                    # No need to load, no change
                    return None
                csvFile = open(filename, "rb")
                csvFileReader = csv.reader(csvFile, skipinitialspace=True)
                self.calibrationDataTime[type] = fileModificationTime

                for row in csvFileReader:
                    # Skip any comment rows
                    if (row[0][:1] != "#"):
                        originalValues.append(float(row[0]))
                        actualValues.append(float(row[1]))

                # Close file
                csvFile.close()
        except IOError:
            print "Tilt (" + color + "):  " + type.capitalize() + \
                ": No calibration data (" + filename + ")"
        except Exception, e:
            print "ERROR: Tilt (" + color + "): Unable to initialise " + \
                type.capitalize() + " Calibration data (" + filename + ") - " + e.message
            # Attempt to close the file
            if (csvFile is not None):
                # Close file
                csvFile.close()

        # If more than two values, use interpolation
        if (len(actualValues) >= 2):
            interpolationFunction = interp1d(
                originalValues, actualValues, bounds_error=False, fill_value=1)
            returnFunction = functools.partial(
                extrapolationCalibration, extrap1d(interpolationFunction))
            print "Tilt (" + color + "): Initialized " + \
                type.capitalize() + " Calibration: Interpolation"
        # Not enough values. Likely just an offset calculation
        elif (len(actualValues) == 1):
            offset = actualValues[0] - originalValues[0]
            returnFunction = functools.partial(offsetCalibration, offset)
            print "Tilt (" + color + "): Initialized " + \
                type.capitalize() + " Calibration: Offset (" + str(offset) + ")"
        return returnFunction


class TiltManager:
    '''Manages the monitoring of all Tilts and storing the read values.'''
    color = ''
    dev_id = 0
    averagingPeriod = 0
    medianWindow = 0

    scanning = True
    # Dictionary to hold Tilts - index on color
    tilts = {}

    tiltthread = None

    def __init__(self, color='', averagingPeriod=0, medianWindow=0, dev_id=0):
        self.color = color
        self.dev_id = dev_id
        self.averagingPeriod = averagingPeriod
        self.medianWindow = medianWindow

    def tiltName(self, uuid):
        '''Return color given UUID.'''
        return {
            'a495bb10c5b14b44b5121370f02d74de': 'Red',
            'a495bb20c5b14b44b5121370f02d74de': 'Green',
            'a495bb30c5b14b44b5121370f02d74de': 'Black',
            'a495bb40c5b14b44b5121370f02d74de': 'Purple',
            'a495bb50c5b14b44b5121370f02d74de': 'Orange',
            'a495bb60c5b14b44b5121370f02d74de': 'Blue',
            'a495bb70c5b14b44b5121370f02d74de': 'Yellow',
            'a495bb80c5b14b44b5121370f02d74de': 'Pink'
        }.get(uuid)

    def storeValue(self, color, temperature, gravity):
        '''Store Tilt values by color.'''
        tilt = self.tilts.get(color)
        if (tilt is None):
            tilt = Tilt(
                color, self.averagingPeriod, self.medianWindow)
            self.tilts[color] = tilt
        tilt.setValues(temperature, gravity)

    def getValue(self, color):
        '''Retrieve Tilt values per color.'''
        returnValue = None
        tilt = self.tilts.get(color)
        if (tilt is not None):
            returnValue = tilt.getValues()
        return returnValue

    def scan(self):
        '''Scan for BLE messages, stores Tilt values.'''
        try:
            sock = bluez.hci_open_dev(self.dev_id)

        except Exception, e:
            print "ERROR: Accessing bluetooth device: " + e.message
            sys.exit(1)

        blescan.hci_le_set_scan_parameters(sock)
        blescan.hci_enable_le_scan(sock)

        # Keep scanning until the manager is told to stop.
        while self.scanning:

            returnedList = blescan.parse_events(sock, 10)

            for beacon in returnedList:
                beaconParts = beacon.split(",")

                # Resolve whether the received BLE event is for a Tilt
                # by looking at the UUID.
                name = self.tiltName(beaconParts[2])

                # If the event is for a Tilt, process the data
                if name is not None:
                    # Store only the Tilt we are monitoring or all if
                    # we have not selected one

                    # DEBUG
                    # print('DEBUG: {0} Tilt beacon: {1}'.format(name, beaconParts))
                    # ts = beaconParts[0]
                    # mac = beaconParts[1]
                    # uuid = beaconParts[2]
                    # temp = beaconParts[3]
                    # grav = beaconParts[4]
                    # txp = beaconParts[5]
                    # rssi = beaconParts[6]
                    # print('DEBUG:  TS: {0}, MAC: {1}, UUID: {2}, Name: {7}, Temp: {3}, Grav: {4}, TXP: {5}, RSSI: {6}'.format(ts, mac, name, temp, grav, txp, rssi, name))
                    # DEBUG

                    if self.color == '' or name == self.color:
                        # Get the temperature (in F, conversion in brewpi.py)
                        temperature = int(beaconParts[3])

                        # Get the gravity
                        gravity = float(beaconParts[4]) / 1000

                        # Store the retrieved values in the relevant Tilt object.
                        self.storeValue(name, temperature, gravity)

    def stop(self):
        '''Stop scanning function.'''
        self.scanning = False

    def start(self):
        '''Start the scanning thread.'''
        self.scanning = True
        self.tiltthread = thread.start_new_thread(self.scan, ())

    def loadSettings(self):
        '''
        Load Settings from config file.

        Overrides values given at creation. This needs to be called before
        the start function is called.
        '''
        myDir = os.path.dirname(os.path.abspath(__file__))
        filename = '{0}/settings/tiltsettings.ini'.format(myDir)
        try:
            config = ConfigParser.ConfigParser()
            config.read(filename)

            # BT Device ID
            try:
                self.dev_id = config.getint("Manager", "DeviceID")
            except:
                pass

            # Time period for noise smoothing
            try:
                self.averagingPeriod = config.getint("Manager", "AvgWindow")
            except:
                pass

            # Median filter setting
            try:
                self.medianWindow = config.getint("Manager", "MedWindow")
            except:
                pass

        except Exception, e:
            print "WARN: Config file does not exist or cannot be read: ({0}): {1}".format(
                filename, e.message)


def main():
    '''Test run for stand-alone run.'''
    threads = []
    tilt = TiltManager()
    tilt.loadSettings()
    tilt.start()

    print "\nScanning Tilt for 20 Secs (Control+C to exit early)."
    for x in range(4):
        time.sleep(5)
        print('\nLoop Iteration: {0}'.format(x + 1))
        for color in TILT_COLORS:
            print color + ": " + str(tilt.getValue(color))

    tilt.stop()

    for thread in threads:
        time.sleep(2)
        thread.join()


if __name__ == "__main__":
    main()
    exit(0)
