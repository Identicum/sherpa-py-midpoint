#!/usr/bin/env python3

import os
import sys

from sherpa.utils.basics import Logger
from sherpa.utils.basics import Properties

sys.path.insert(0, './sherpa/')
from midpoint.midpoint_lib import MidpointClient, Midpoint


def main():
	properties = Properties("./testing/local.properties", "./testing/local.properties", "$(", ")")
	logger = Logger(os.path.basename(__file__), properties.get("log_level"), properties.get("log_file"))
	run(logger, properties)
	logger.info("{} finished.".format(os.path.basename(__file__)))


def run(logger, properties):
	logger.info("{} starting.".format(os.path.basename(__file__)))

	# mp_baseurl = "http://midpoint:8080/midpoint/ws/rest/"
	# midpoint = Midpoint(mp_baseurl=mp_baseurl, mp_username="administrator", mp_password="Sherpa.2026", properties=properties, logger=logger)
	# midpoint.process_subfolders("./testing/objects")

	mp_baseurl = "http://midpoint:8080/midpoint"
	midpoint_admin = MidpointClient(mp_baseurl=mp_baseurl, mp_username="administrator", mp_password="Sherpa.2026", logger=logger, properties=properties)
	midpoint_admin.process_subfolders("./testing/objects")


if __name__ == "__main__":
	sys.exit(main())
