#!/usr/bin/env python3

import os
import sys

from sherpa.utils.basics import Logger
from sherpa.utils.basics import Properties

sys.path.insert(0, './sherpa/')
from midpoint.midpoint_lib import Midpoint


def main():
	properties = Properties("./testing/local.properties", "./testing/local.properties", "$(", ")")
	logger = Logger(os.path.basename(__file__), properties.get("log_level"), properties.get("log_file"))
	run(logger, properties)
	logger.info("{} finished.".format(os.path.basename(__file__)))


def run(logger, properties):
	logger.info("{} starting.".format(os.path.basename(__file__)))
	mp_baseurl = "http://midpoint:8080/midpoint/ws/rest/"
	midpoint = Midpoint(mp_baseurl=mp_baseurl, mp_username="administrator", mp_password="Test5ecr3t", properties=properties, logger=logger, iterations=30, interval=30)
	midpoint.process_subfolders("./testing/objects")
	task_name = "USERS_recompute"
	midpoint.run_task(task_name=task_name)
	midpoint.wait_for_completed_task(iterations=10, interval=10, object_name=task_name)
	midpoint.add_role_inducement_to_role(child_name="role01", parent_name="role02")
	midpoint.add_role_assignment_to_user(role_name="role02", user_name="administrator")
	midpoint.set_security_policy(policy_oid="00000000-0000-1de4-0012-000000000002")
	midpoint.delete_object_collection_view("person-view")

	# midpoint.process_folder("./testing/test")


if __name__ == "__main__":
	sys.exit(main())
