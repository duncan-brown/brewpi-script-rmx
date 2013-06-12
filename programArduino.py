import os.path
# Copyright 2012 BrewPi/Elco Jacobs.
# This file is part of BrewPi.

# BrewPi is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# BrewPi is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with BrewPi.  If not, see <http://www.gnu.org/licenses/>.

import subprocess as sub
import serial
from time import sleep
import simplejson as json
import os
from brewpiVersion import AvrInfo

def fetchBoardSettings(boardsFile, boardType, restoreSettings):
	boardSettings = {}
	for line in boardsFile:
		if(line.startswith(boardType)):
			setting = line.replace(boardType + '.', '', 1).strip() # strip board name, period and \n
			[key, sign, val] = setting.rpartition('=')
			boardSettings[key] = val
	return boardSettings

def loadBoardsFile(arduinohome):
	return open(arduinohome+'hardware/arduino/boards.txt', 'rb').readlines()

def programArduino(config, boardType, hexFile):
	try:
		arduinohome = config.get('arduinoHome', '/usr/share/arduino/')  # location of Arduino sdk
		avrdudehome = config.get('avrdudeHome', arduinohome + 'hardware/tools/')  # location of avr tools
		avrsizehome = config.get('avrsizeHome', '')  # default to empty string because avrsize is on path
		avrconf = config.get('avrConf', avrdudehome + 'avrdude.conf')  # location of global avr conf
		returnString = ""

		boardsFile = loadBoardsFile(arduinohome)
		boardSettings = fetchBoardSettings(boardsFile, boardType)
		port = config['port']

		# open serial port to read old settings and version
		try:
			ser = serial.Serial(port, 57600, timeout=1)  # timeout=1 is too slow when waiting on temp sensor reads
		except serial.SerialException, e:
			print e

		retries = 0
		while 1:  # read all lines on serial interface
			line = ser.readline()
			if line:  # line available?
				if line[0] == 'N':
					data = line.strip('\n')[2:]
					avrVersionOld = AvrInfo(data)
					returnString += "Checking old version before programming.\n"
					returnString +=( "Found Arduino " + avrVersionOld.board +
								" with a " + avrVersionOld.shield + " shield, " +
								"running BrewPi version " + avrVersionOld.version +
								" build " + str(avrVersionOld.build) + "\n")
					break
			else:
				ser.write('n')  # request version info
				sleep(1)
				retries += 1
				if retries > 5:
					returnString += ("Warning: Cannot receive version number from Arduino. " +
								 "Your Arduino is either not programmed yet or running a very old version of BrewPi. "
								 "Arduino will be reset to defaults. \n")
					break

		ser.flush()

		oldSettings = {}

		# request all settings from board before programming
		ser.write("d{}")  # installed devices
		ser.write("c{}")  # control constants
		ser.write("s{}")  # control settings
		sleep(1)

		returnString += "Requesting old settings from Arduino \n"

		while 1:  # read all lines on serial interface
			line = ser.readline()
			if line:  # line available?
				try:
					if line[0] == 'C':
						oldSettings['controlConstants'] = json.loads(line[2:])
					elif line[0] == 'S':
						oldSettings['controlSettings'] = json.loads(line[2:])
					elif line[0] == 'd':
						oldSettings['installedDevices'] = json.loads(line[2:])

				except json.decoder.JSONDecodeError, e:
					returnString += ("JSON decode error: %s \n" % e)
					returnString += ("Line received was: " + line + "\n")
			else:
				break

		ser.close()
		del ser  # Arduino won't reset when serial port is not completely removed

		returnString += "Saving old settings to file 'settings/oldAvrSettings.json"

		scriptDir = "" # os.path.dirname(__file__)  # <-- absolute dir the script is in
		oldSettingsFile = open(scriptDir + 'settings/oldAvrSettings.json', 'wb')
		oldSettingsFile.write(json.dumps(oldSettings))
		print scriptDir + "nu wel he"
		oldSettingsFile.truncate()
		oldSettingsFile.close()
		print "hier kom ik ook"

		# parse the Arduino board file to get the right program settings
		for line in boardsFile:
			if(line.startswith(boardType)):
				  # strip board name, period and \n
				setting = line.replace(boardType + '.', '', 1).strip()
				[key, sign, val] = setting.rpartition('=')
				boardSettings[key] = val

		# start programming the Arduino
		avrsizeCommand = avrsizehome + 'avr-size ' + hexFile
		returnString = returnString + avrsizeCommand + '\n'
		# check program size against maximum size
		p = sub.Popen(avrsizeCommand, stdout=sub.PIPE, stderr=sub.PIPE, shell=True)
		output, errors = p.communicate()
		if errors != "":
			returnString = returnString + 'avr-size error: ' + errors + '\n'
			return returnString

		returnString = returnString + ('Progam size: ' + output.split()[7] +
			' bytes out of max ' + boardSettings['upload.maximum_size'] + '\n')

		hexFileDir = os.path.dirname(hexFile)
		hexFileLocal = os.path.basename(hexFile)

		programCommand = (avrdudehome + 'avrdude' +
					' -F ' +
					' -p ' + boardSettings['build.mcu'] +
					' -c ' + boardSettings['upload.protocol'] +
					' -b ' + boardSettings['upload.speed'] +
					' -P ' + port +
					' -U ' + 'flash:w:' + hexFileLocal +
					' -C ' + avrconf)

		returnString = returnString + programCommand + '\n'

		# open and close serial port at 1200 baud. This resets the Arduino Leonardo
		# the Arduino Uno resets every time the serial port is opened automatically
		if(boardType == 'leonardo'):
			ser = serial.Serial(port, 1200)
			ser.close()
			sleep(1)  # give the bootloader time to start up

		p = sub.Popen(programCommand, stdout=sub.PIPE, stderr=sub.PIPE, shell=True,cwd=hexFileDir)
		output, errors = p.communicate()

		# avrdude only uses stderr, append its output to the returnString
		returnString = returnString + errors

		returnString += "avrdude done! Now trying to restore settings"

		try:
			ser = serial.Serial(port, 57600, timeout=1)  # timeout=1 is too slow when waiting on temp sensor reads
		except serial.SerialException, e:
			print e

		retries = 0

		# read new version
		while 1:  # read all lines on serial interface
			line = ser.readline()
			if line:  # line available?
				if line[0] == 'N':
					data = line.strip('\n')[2:]
					avrVersionNew = AvrInfo(data)
					returnString +=( "Found Arduino " + avrVersionNew.board +
					                 " with a " + avrVersionNew.shield + " shield, " +
					                 "running BrewPi version " + avrVersionNew.version +
					                 " build " + str(avrVersionNew.build) + "\n")
					break
			else:
				ser.write('n')  # request version info
				sleep(1)
				retries += 1
				if retries > 5:
					returnString += ("Warning: Cannot receive version number from Arduino after programming. " +
					                 "Something must have gone wrong. \n")
					break

		ser.flush()

		# Initialize EEPROM to defaults:

		# read
	except Exception, e: # except all errors, so they can be returned to the script
 	    returnString += "Fatal exception while running program script: " + e
 	finally:
 		print returnString
		return returnString
