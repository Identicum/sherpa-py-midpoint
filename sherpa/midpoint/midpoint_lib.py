# sherpa-py-midpoint is available under the MIT License. https://github.com/Identicum/sherpa-py-midpoint/
# Copyright (c) 2026, Identicum - https://identicum.com/
#
# Author: Gustavo J Gallardo - ggallard@identicum.com
#

import base64
import json
import os
import requests
from requests.auth import HTTPBasicAuth
import shutil
import time
import yaml
from importlib.metadata import version
from sherpa.utils import validators
from sherpa.utils import http
from sherpa.utils.basics import Logger
from sherpa.utils.basics import Properties
from xml.etree import ElementTree

# For detail in OID numbering see: https://github.com/Identicum/sherpa-iga/blob/main/objects/OID.md
# import_order: Numeric folder prefix (several classes can share a number)
# Block A = IDENTICUM_OID_MARKER + 4-hex customer id ("0000" for base Sherpa objects).
IDENTICUM_OID_MARKER = "1de4"
object_types = [
    {"type": "SystemConfigurationType",           "element_name": "systemConfiguration",           "endpoint": "systemConfigurations",           "import_order": 3, "oid_block_b": None},
    {"type": "UserType",                          "element_name": "user",                          "endpoint": "users",                          "import_order": 7, "oid_block_b": "0001"},
    {"type": "ResourceType",                      "element_name": "resource",                      "endpoint": "resources",                      "import_order": 4, "oid_block_b": "0002"},
    {"type": "RoleType",                          "element_name": "role",                          "endpoint": "roles",                          "import_order": 5, "oid_block_b": "0004"},
    {"type": "ObjectTemplateType",                "element_name": "objectTemplate",                "endpoint": "objectTemplates",                "import_order": 1, "oid_block_b": "0005"},
    {"type": "TaskType",                          "element_name": "task",                          "endpoint": "tasks",                          "import_order": 8, "oid_block_b": "0007"},
    {"type": "FunctionLibraryType",               "element_name": "functionLibrary",               "endpoint": "functionLibraries",              "import_order": 2, "oid_block_b": "0010"},
    {"type": "ArchetypeType",                     "element_name": "archetype",                     "endpoint": "archetypes",                     "import_order": 2, "oid_block_b": "0011"},
    {"type": "ValuePolicyType",                   "element_name": "valuePolicy",                   "endpoint": "valuePolicies",                  "import_order": 2, "oid_block_b": "0012"},
    {"type": "SecurityPolicyType",                "element_name": "securityPolicy",                "endpoint": "securityPolicies",               "import_order": 2, "oid_block_b": "0012"},
    {"type": "ObjectCollectionType",              "element_name": "objectCollection",              "endpoint": "objectCollections",              "import_order": 5, "oid_block_b": "0013"},
    {"type": "AccessCertificationDefinitionType", "element_name": "accessCertificationDefinition", "endpoint": "accessCertificationDefinitions", 'import_order': 9, 'oid_block_b': '0014'},
    {"type": "FormType",                          "element_name": "form",                          "endpoint": "forms",                          "import_order": 5, "oid_block_b": "0015"},
    {"type": 'SchemaType',                        'element_name': 'schema',                        'endpoint': 'schemas',                        'import_order': 0, 'oid_block_b': '0017'},
    {"type": 'ReportType',                        'element_name': 'report',                        'endpoint': 'reports',                        'import_order': 6, 'oid_block_b': '0018'},
]

CONTENT_TYPE_XML = "application/xml"
CONTENT_TYPE_JSON = "application/json"
CONTENT_TYPE_YAML = "application/yaml"


def get_object_type_entry(type: str = None, element_name: str = None) -> dict:
    """Look up an object_types entry by type (e.g. 'UserType') or element name (e.g. 'user')."""
    if type is None and element_name is None:
        raise ValueError("Either type or element_name must be specified.")
    for entry in object_types:
        if (type is not None and entry["type"] == type) or (element_name is not None and entry["element_name"] == element_name):
            return entry
    raise ValueError("No object_types entry found for type='{}', element_name='{}'.".format(type, element_name))


def check_sherpa_oid(oid: str, element_name: str, expected_customer_id: str = "0000", logger: Logger = None):
    """
    Validate that an oid follows the Sherpa base/customer repo numbering scheme
    for the given object type (element_name). Raises ValueError with a descriptive message
    if it doesn't; returns None if it does.
    """
    if logger is None:
        logger = Logger("check_sherpa_oid")
    if not oid:
        logger.error("Object of type {} has no oid.".format(element_name))
        raise ValueError("Object of type {} has no oid.".format(element_name))
    blocks = oid.split("-")
    if len(blocks) != 5:
        logger.error("oid '{}' does not have the expected 5 blocks.".format(oid))
        raise ValueError("oid '{}' does not have the expected 5 blocks.".format(oid))
    block_a, block_b, _block_c, _block_d, _block_e = blocks
    expected_block_a = IDENTICUM_OID_MARKER + expected_customer_id
    if block_a.lower() != expected_block_a.lower():
        logger.error("oid '{}' block A is '{}', expected '{}'.".format(oid, block_a, expected_block_a))
        raise ValueError("oid '{}' block A is '{}', expected '{}'.".format(oid, block_a, expected_block_a))
    entry = get_object_type_entry(element_name=element_name)
    expected_block_b = entry["oid_block_b"]
    if expected_block_b is not None and block_b.lower() != expected_block_b.lower():
        logger.error("oid '{}' block B is '{}', expected '{}' for type '{}'.".format(oid, block_b, expected_block_b, element_name))
        raise ValueError("oid '{}' block B is '{}', expected '{}' for type '{}'.".format(oid, block_b, expected_block_b, element_name))


class MidpointError(Exception):
    """Raised when the Midpoint API returns an unexpected response."""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class MidpointClient:
    def __init__(self, mp_baseurl: str, mp_username: str, mp_password: str, on_behalf: str = None, logger: Logger = None, properties: Properties = None, timeout: int = 10, iterations: int = 10, interval: int = 10, temp_file_path: str = "/tmp/midpoint_object"):
        self.logger = logger if logger is not None else Logger("MidpointClient")
        self.logger.debug(f"Midpoint lib version: {version("sherpa-py-midpoint")}")
        self.properties = properties
        self.base_url = mp_baseurl + "/ws/rest"
        self._timeout = timeout
        self._iterations = iterations
        self._interval = interval
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(mp_username, mp_password)
        self.session.headers.update({
            "Accept": CONTENT_TYPE_JSON
        })
        if on_behalf is not None:
            self.session.headers["Switch-To-Principal"] = on_behalf

        mp_credentials = f"{mp_username}:{mp_password}"
        http_credentials = base64.b64encode(mp_credentials.encode())
        url = f"{self.base_url}/users/00000000-0000-0000-0000-000000000002"
        headers = {'Authorization': f'Basic {http_credentials.decode()}', 'Content-Type': CONTENT_TYPE_XML}
        http.wait_for_endpoint(url, self._iterations, self._interval, self.logger, headers)
        self.temp_file_path = temp_file_path


    # ###############################################################################
    # Case

    def get_requested_cases(self, requestor_oid: str) -> list[dict]:
        self.logger.debug(f"Starting: requestor_oid={requestor_oid}")
        query_payload = {
            "query": {
                "filter": {
                    "text": f'state = "open" and requestorRef matches (oid = "{requestor_oid}")'
                }
            }
        }
        case_objects = self._search_objects("CaseType", query_payload)
        return self._normalize_objects(case_objects)


    def get_assigned_cases(self, assignee_oid: str) -> list[dict]:
        self.logger.debug(f"Starting: assignee_oid={assignee_oid}")
        query_payload = {
            "query": {
                "filter": {
                    "text": f'state = "open" and workItem/assigneeRef matches (oid = "{assignee_oid}")'
                }
            }
        }
        case_objects = self._search_objects("CaseType", query_payload)
        return self._normalize_objects(case_objects)


    def _decide_work_item(self, case_oid: str, item_id: int, decision: str, comment: str) -> dict:
        """
        Submit an approve or reject decision for a work item.
        """
        self.logger.debug(f"Starting: case_oid={case_oid}, item_id={item_id}, decision={decision}")
        try:
            # First check if the work item still exists and is open
            cases_endpoint = self._get_endpoint_from_type("CaseType")
            case_data = self._http_get(path=f"{cases_endpoint}/{case_oid}")
            self.logger.trace("case_data={}", case_data)
            items = case_data.get("case", {}).get("workItem", [])
            self.logger.trace("items={}", items)
            if isinstance(items, dict):
                items = [items]
            item = next((i for i in items if str(i.get("@id")) == str(item_id)), None)
            self.logger.trace("item={}", item)
            if item is None:
                return {"status": "not_found", "decision": decision}
            if item.get("output"):
                # Already decided
                existing = item["output"].get("outcome", "unknown")
                return {"status": "already_done", "decision": decision, "existing": existing}
            body = {
                "output" : {
                    "@type" : "c:AbstractWorkItemOutputType",
                    "comment" : comment or "Decision submitted via sherpa-py-midpoint library",
                    "outcome" : f"http://midpoint.evolveum.com/xml/ns/public/model/approval/outcome#{decision}"
                }
            }
            self._http_post(path=f"{cases_endpoint}/{case_oid}/workItems/{str(item_id)}/complete", body=body, expected_status=[204])
            return {"status": "success", "decision": decision}
        except Exception as e:
            return {"status": "error", "decision": decision, "message": str(e)}


    def approve_work_item(self, case_oid: str, item_id: int, comment: str = None) -> dict:
        """
        Approve a work item.
        Returns a result dict with success/already_done/error status.
        """
        self.logger.debug(f"Approving workItem: {item_id} in case: {case_oid}")
        return self._decide_work_item(case_oid=case_oid, item_id=item_id, decision="approve", comment=comment)


    def reject_work_item(self, case_oid: str, item_id: int, comment: str = None) -> dict:
        """
        Reject a work item.
        """
        self.logger.debug(f"Rejecting workItem: {item_id} in case: {case_oid}")
        return self._decide_work_item(case_oid=case_oid, item_id=item_id, decision="reject", comment=comment)


    # ###############################################################################
    # Role

    def get_requestable_roles(self, user_oid: str) -> list[dict]:
        self.logger.debug(f"Starting")
        query_payload = {
            "query": {
                "filter": { "text": "requestable = true" }
            }
        }
        roles = self._search_objects(object_type="RoleType", query_payload=query_payload)
        normalized_user = self.get_user(oid=user_oid)
        member_oids = {m["oid"] for m in normalized_user.get("role_membership", [])}
        normalized_roles = self._normalize_objects(roles)
        return [r for r in normalized_roles if r.get("oid") not in member_oids]


    def _add_assignment_or_inducement(self, relationship: str, assignee_type: str, assignee_oid: str, target_type: str, target_oid: str) -> dict:
        self.logger.debug(f"Starting: relationship={relationship}, assignee_type={assignee_type}, assignee_oid={assignee_oid}, target_type={target_type}, target_oid={target_oid}")
        request_body = {
            "objectModification": {
                "itemDelta": [
                    {
                        "modificationType": "add",
                        "path": relationship,
                        "value": [
                            {
                                "targetRef": {
                                    "oid": target_oid,
                                    "type": f"c:{target_type}",
                                    "relation": "org:default",
                                }
                            }
                        ]
                    }
                ]
            }
        }
        json_resp = self._http_patch(path=self._get_endpoint_from_type(assignee_type) + "/" + assignee_oid, body=request_body, expected_status=[204])
        self.logger.debug(f"json_resp={json_resp}")
        target_object = self._get_object(object_type=target_type, object_oid=target_oid)
        return {"target_name": target_object["name"], "status": "success"}


    def _request_role(self, assignee_type: str, assignee_oid: str, role_oid: str, relationship: str, message: str) -> dict:
        result = self._add_assignment_or_inducement(relationship=relationship, assignee_type=assignee_type, assignee_oid=assignee_oid, target_type="RoleType", target_oid=role_oid)
        return {"role_name": result["target_name"], "status": result["status"], "message": message}


    def request_role_assignment(self, assignee_type: str, assignee_oid: str, role_oid: str) -> dict:
        return self._request_role(assignee_type=assignee_type, assignee_oid=assignee_oid, role_oid=role_oid, relationship="assignment", message="Role requested")


    def request_role_inducement(self, assignee_type: str, assignee_oid: str, role_oid: str) -> dict:
        return self._request_role(assignee_type=assignee_type, assignee_oid=assignee_oid, role_oid=role_oid, relationship="inducement", message="Role induced")


    def add_resource_inducement_to_role(self, resource_oid: str = None, resource_name: str = None, role_oid: str = None, role_name: str = None) -> dict:
        self.logger.debug(f"Starting: resource_oid={resource_oid}, resource_name={resource_name}, role_oid={role_oid}, role_name={role_name}")
        resolved_resource_oid = self._resolve_oid(object_type="ResourceType", oid=resource_oid, name=resource_name)
        resolved_role_oid = self._resolve_oid(object_type="RoleType", oid=role_oid, name=role_name)
        result = self._add_assignment_or_inducement(relationship="inducement", assignee_type="RoleType", assignee_oid=resolved_role_oid, target_type="ResourceType", target_oid=resolved_resource_oid)
        return {"resource_name": result["target_name"], "status": result["status"], "message": "Resource inducement added"}


    def add_role_assignment_to_user(self, role_oid: str = None, role_name: str = None, user_oid: str = None, user_name: str = None) -> dict:
        self.logger.debug(f"Starting: role_oid={role_oid}, role_name={role_name}, user_oid={user_oid}, user_name={user_name}")
        resolved_role_oid = self._resolve_oid(object_type="RoleType", oid=role_oid, name=role_name)
        resolved_user_oid = self._resolve_oid(object_type="UserType", oid=user_oid, name=user_name)
        result = self._add_assignment_or_inducement(relationship="assignment", assignee_type="UserType", assignee_oid=resolved_user_oid, target_type="RoleType", target_oid=resolved_role_oid)
        return {"role_name": result["target_name"], "status": result["status"], "message": "Role assigned"}


    def add_role_inducement_to_archetype(self, role_oid: str = None, role_name: str = None, archetype_oid: str = None, archetype_name: str = None) -> dict:
        self.logger.debug(f"Starting: role_oid={role_oid}, role_name={role_name}, archetype_oid={archetype_oid}, archetype_name={archetype_name}")
        resolved_role_oid = self._resolve_oid(object_type="RoleType", oid=role_oid, name=role_name)
        resolved_archetype_oid = self._resolve_oid(object_type="ArchetypeType", oid=archetype_oid, name=archetype_name)
        result = self._add_assignment_or_inducement(relationship="inducement", assignee_type="ArchetypeType", assignee_oid=resolved_archetype_oid, target_type="RoleType", target_oid=resolved_role_oid)
        return {"role_name": result["target_name"], "status": result["status"], "message": "Role induced to archetype"}


    def add_role_inducement_to_role(self, role_oid: str = None, role_name: str = None, assignee_oid: str = None, assignee_name: str = None) -> dict:
        self.logger.debug(f"Starting: role_oid={role_oid}, role_name={role_name}, assignee_oid={assignee_oid}, assignee_name={assignee_name}")
        resolved_role_oid = self._resolve_oid(object_type="RoleType", oid=role_oid, name=role_name)
        resolved_assignee_oid = self._resolve_oid(object_type="ArchetypeType", oid=assignee_oid, name=assignee_name)
        result = self._add_assignment_or_inducement(relationship="inducement", assignee_type="RoleType", assignee_oid=resolved_assignee_oid, target_type="RoleType", target_oid=resolved_role_oid)
        return {"role_name": result["target_name"], "status": result["status"], "message": "Role induced to role"}


    def set_role_requestable(self, role_name: str, value: bool) -> dict:
        self.logger.debug(f"Starting: role_name={role_name}, value={value}")
        resolved_role_oid = self._resolve_oid(object_type="RoleType", name=role_name)
        request_body = {
            "objectModification": {
                "itemDelta": [
                    {
                        "modificationType": "add",
                        "path": "requestable",
                        "value": value
                    }
                ]
            }
        }
        json_resp = self._http_patch(path=self._get_endpoint_from_type("RoleType") + "/" + resolved_role_oid, body=request_body, expected_status=[204])
        self.logger.debug(f"json_resp={json_resp}")
        return {"status": "success", "role_name": role_name, "requestable": value}


    # ###############################################################################
    # User

    def get_user(self, oid: str = None, name: str = None) -> dict:
        object_type = "UserType"
        self.logger.debug(f"Starting: oid={oid}, name={name}")
        object = {}
        if oid is not None:
            object = self._get_object(object_type=object_type, object_oid=oid)
        elif name is not None:
            object = self._search_object_by_name(object_type=object_type, object_name=name)
        else:
            raise Exception("Either oid or name must be specified.")
        self.logger.trace("object: {}", object)
        if "@type" not in object:
            object["@type"] = f"c:{object_type}"
        return self._normalize_object(object)


    # ###############################################################################
    # Task

    def _task_action(self, action: str, task_oid: str = None, task_name: str = None) -> dict:
        self.logger.debug(f"Starting: action={action}, task_oid={task_oid}, task_name={task_name}")
        resolved_oid = self._resolve_oid(object_type="TaskType", oid=task_oid, name=task_name)
        self._http_post(path=self._get_endpoint_from_type("TaskType") + "/" + resolved_oid + "/" + action, expected_status=[202, 204])
        return {"status": "success", "oid": resolved_oid}


    def resume_task(self, task_oid: str = None, task_name: str = None) -> dict:
        self.logger.debug(f"Resuming task: task_oid={task_oid}, task_name={task_name}")
        return self._task_action(action="resume", task_oid=task_oid, task_name=task_name)


    def run_task(self, task_oid: str = None, task_name: str = None, wait_for_completion: bool = False) -> dict:
        self.logger.debug(f"Waiting for task prior to execution: task_oid={task_oid}, task_name={task_name}")
        self.wait_for_completed_task(iterations=self._iterations, interval=self._interval, task_oid=task_oid, task_name=task_name)
        self.logger.debug(f"Running task: task_oid={task_oid}, task_name={task_name}")
        result = self._task_action(action="run", task_oid=task_oid, task_name=task_name)
        if wait_for_completion:
            self.logger.debug(f"Waiting for task POST execution: task_oid={task_oid}, task_name={task_name}")
            self.wait_for_completed_task(iterations=self._iterations, interval=self._interval, task_oid=task_oid, task_name=task_name)
        return result


    def wait_for_completed_task(self, task_oid: str = None, task_name: str = None, iterations: int = None, interval: int = None) -> dict:
        self.logger.debug(f"Waiting for task to complete: task_oid={task_oid}, task_name={task_name}")
        iterations = iterations if iterations is not None else self._iterations
        interval = interval if interval is not None else self._interval
        resolved_oid = self._resolve_oid(object_type="TaskType", oid=task_oid, name=task_name)
        task_completed = False
        for iteration in range(iterations):
            self.logger.debug(f"Iteration #: {iteration}")
            try:
                task_object = self._get_object(object_type="TaskType", object_oid=resolved_oid)
                result_status = task_object.get("resultStatus")
                self.logger.debug(f"result_status: {result_status}")
                if result_status == "success":
                    task_completed = True
                    self.logger.debug(f"Task is '{result_status}'")
                    break
                elif result_status == "in_progress":
                    self.logger.debug(f"Task is '{result_status}'")
                else:
                    self.logger.error(f"Unable to recognize task status: {result_status}")
            except Exception:
                self.logger.debug(f"Exception while trying to find task_oid: {resolved_oid}")
            self.logger.trace(f"Waiting {interval} seconds for task_oid: {resolved_oid}")
            time.sleep(interval)
        if not task_completed:
            validators.raise_and_log(self.logger, MidpointError, f"Gave up waiting for task to complete: task_oid={task_oid}, task_name={task_name}")
        return {"status": "success", "oid": resolved_oid}


    # ###############################################################################
    # System Configuration

    def get_system_configuration(self) -> dict:
        self.logger.debug("Starting")
        system_configuration_object = self._get_object(object_type="SystemConfigurationType", object_oid="00000000-0000-0000-0000-000000000001")
        if system_configuration_object is None:
            validators.raise_and_log(self.logger, MidpointError, "SystemConfigurationType does not exist.")
        return system_configuration_object


    # This should be deprecated in favor of specific methods like set_class_logger, etc.
    def set_system_configuration(self, modification_type: str, path: str, value) -> dict:
        self.logger.debug(f"Starting: modification_type={modification_type}, path={path}, value={value}")
        request_body = {
            "objectModification": {
                "itemDelta": [
                    {
                        "modificationType": modification_type,
                        "path": path,
                        "value": value
                    }
                ]
            }
        }
        json_resp = self._http_patch(path=self._get_endpoint_from_type("SystemConfigurationType") + "/00000000-0000-0000-0000-000000000001", body=request_body, expected_status=[204])
        self.logger.debug(f"json_resp={json_resp}")
        return {"status": "success", "message": "System configuration updated"}


    # ###############################################################################
    # Logging

    def _get_class_loggers(self, system_configuration: dict) -> list[dict]:
        self.logger.trace("Getting existing classLoggers.")
        class_loggers = system_configuration.get("logging", {}).get("classLogger", [])
        if isinstance(class_loggers, dict):
            class_loggers = [class_loggers]
        result = [{"id": class_logger.get("@id"), "package": class_logger.get("package"), "level": class_logger.get("level")} for class_logger in class_loggers]
        self.logger.trace(f"existing classLoggers: {result}")
        return result


    def replace_class_logger(self, id: str, level: str) -> dict:
        path = f"logging/classLogger[{id}]/level"
        return self.set_system_configuration(modification_type="replace", path=path, value=level)


    def add_class_logger(self, package: str, level: str) -> dict:
        value = [{"package": package, "level": level}]
        return self.set_system_configuration(modification_type="add", path="logging/classLogger", value=value)


    def set_class_logger(self, package: str, level: str) -> dict:
        self.logger.debug(f"Starting: package={package}, level={level}")
        logger_entries = self._get_class_loggers(self.get_system_configuration())
        self.logger.trace(f"Existing logger entries: {logger_entries}")
        for logger_entry in logger_entries:
            if logger_entry["package"] == package:
                self.logger.debug(f"Logger already exists for package: {package}, updating log-level")
                return self.replace_class_logger(id=logger_entry["id"], level=level)
        return self.add_class_logger(package=package, level=level)


    # ###############################################################################
    # HTTP methods

    def _http_get(self, path: str, params: dict = None, expected_status: list[int] = [200]) -> dict:
        url = self.base_url + "/" + path
        self.logger.debug(f"GET {url} params={params}")
        resp = self.session.get(url, params=params, timeout=self._timeout)
        self.logger.trace(f"GET {url} -> status={resp.status_code} body={resp.text}")
        if resp.status_code not in expected_status:
            validators.raise_and_log(self.logger, IOError, f"Invalid HTTP response received: '{resp.status_code}'.")
        return resp.json()


    def _http_patch(self, path: str, body=None, expected_status: list[int] = [200], content_type: str = CONTENT_TYPE_JSON) -> dict:
        url = self.base_url + "/" + path
        self.logger.debug(f"PATCH {url} body={body} content_type={content_type}")
        headers = {"Content-Type": content_type}
        if content_type == CONTENT_TYPE_JSON:
            resp = self.session.patch(url, json=body, headers=headers, timeout=self._timeout)
        else:
            resp = self.session.patch(url, data=body, headers=headers, timeout=self._timeout)
        self.logger.trace(f"PATCH {url} -> status={resp.status_code} body={resp.text}")
        if resp.status_code not in expected_status:
            validators.raise_and_log(self.logger, IOError, f"Invalid HTTP response received: '{resp.status_code}'.")
        if not resp.text:
            return {}
        return resp.json()


    def _http_put(self, path: str, body=None, expected_status: list[int] = [201,202], content_type: str = CONTENT_TYPE_JSON) -> dict:
        url = self.base_url + "/" + path
        self.logger.debug(f"PUT {url} body={body} content_type={content_type}")
        headers = {"Content-Type": content_type}
        if content_type == CONTENT_TYPE_JSON:
            resp = self.session.put(url, json=body, headers=headers, timeout=self._timeout)
        else:
            resp = self.session.put(url, data=body, headers=headers, timeout=self._timeout)
        self.logger.trace(f"PUT {url} -> status={resp.status_code} body={resp.text}")
        if resp.status_code not in expected_status:
            validators.raise_and_log(self.logger, IOError, f"Invalid HTTP response received: '{resp.status_code}'.")
        if not resp.text:
            return {}
        return resp.json()


    def _http_post(self, path: str, body=None, expected_status: list[int] = [200], content_type: str = CONTENT_TYPE_JSON) -> dict:
        url = self.base_url + "/" + path
        self.logger.debug(f"POST {url}, body={body}, content_type={content_type}, headers={self.session.headers}")
        headers = {"Content-Type": content_type}
        if content_type == CONTENT_TYPE_JSON:
            resp = self.session.post(url, json=body, headers=headers, timeout=self._timeout)
        else:
            resp = self.session.post(url, data=body, headers=headers, timeout=self._timeout)
        self.logger.trace(f"POST {url} -> status={resp.status_code} body={resp.text}")
        if resp.status_code not in expected_status:
            validators.raise_and_log(self.logger, IOError, f"Invalid HTTP response received: '{resp.status_code}'.")
        if not resp.text:
            return {}
        return resp.json()


    # ###############################################################################
    # General auxiliary methods

    def _get_object(self, object_type: str, object_oid: str) -> dict:
        self.logger.debug(f"Starting: object_type={object_type}, object_oid={object_oid}")
        json_resp = self._http_get(path=self._get_endpoint_from_type(object_type) + "/" + object_oid)
        obj = next(iter(json_resp.values()), None)
        self.logger.trace(f"obj: {obj}")
        if not obj:
            self.logger.info(f"Object not found: type={object_type}, name={object_oid}")
            return None
        return obj


    def _get_objects(self, object_type: str) -> list[dict]:
        self.logger.debug(f"Starting: object_type={object_type}")
        json_resp = self._http_get(path=self._get_endpoint_from_type(object_type))
        objects = json_resp.get("object", {}).get("object", [])
        self.logger.trace(f"objects: {objects}")
        if isinstance(objects, dict):
            objects = [objects]


    def _search_objects(self, object_type: str, query_payload: dict) -> list[dict]:
        self.logger.debug(f"Starting: object_type={object_type}, query_payload={query_payload}")
        json_resp = self._http_post(path=self._get_endpoint_from_type(object_type) + "/search", body=query_payload)
        self.logger.trace(f"json_resp: {json_resp}")
        objects = json_resp.get("object", {}).get("object", [])
        if isinstance(objects, dict):
            objects = [objects]
        if not objects:
            self.logger.info(f"Object not found: type={object_type}, query_payload={query_payload}")
            return []
        self.logger.trace(f"Returning {len(objects)} objects: {objects}")
        return objects


    def _search_object_by_name(self, object_type: str, object_name: str) -> dict:
        self.logger.debug(f"Starting: object_type={object_type}, object_name={object_name}")
        query_payload = {"query": {"filter": {"equal": {"path": "name", "value": object_name}}}}
        objects = self._search_objects(object_type, query_payload)
        self.logger.trace(f"objects: {objects}")
        if not objects:
            self.logger.info(f"Object not found: type={object_type}, name={object_name}")
            return {}
        if len(objects) > 1:
            raise MidpointError(f"Multiple objects found for type={object_type}, name={object_name}")
        self.logger.trace(f"objects[0]: {objects[0]}")
        return objects[0]


    def _resolve_oid(self, object_type: str, oid: str = None, name: str = None) -> str:
        if oid:
            return oid
        if name:
            self._wait_for_object(iterations=self._iterations, interval=self._interval, object_type=object_type, object_name=name)
            object = self._search_object_by_name(object_type=object_type, object_name=name)
            if "oid" in object:
                return object["oid"]
            else:
                validators.raise_and_log(self.logger, MidpointError, f"Object does not contain oid: {object}")
        validators.raise_and_log(self.logger, MidpointError, f"Either oid or name must be specified for object_type={object_type}.")


    def _wait_for_object(self, iterations: int, interval: int, object_type: str, object_oid: str = None, object_name: str = None):
        if object_oid is None and object_name is None:
            validators.raise_and_log(self.logger, MidpointError, "Either object_oid or object_name must be specified.")
        object_exists = False
        for iteration in range(iterations):
            self.logger.debug(f"Iteration #: {iteration}")
            try:
                if object_oid is not None:
                    self.logger.debug(f"Checking if object exists. Type: {object_type}, oid: {object_oid}")
                    if self._get_object(object_type=object_type, object_oid=object_oid) is not None:
                        object_exists = True
                        break
                else:
                    self.logger.debug(f"Checking if object exists. Type: {object_type}, name: {object_name}")
                    if self._search_object_by_name(object_type=object_type, object_name=object_name):
                        object_exists = True
                        break
            except Exception:
                self.logger.debug(f"Exception while trying to find object_type: {object_type}, object_oid: {object_oid}, object_name: {object_name}")
            self.logger.trace(f"Waiting {interval} seconds for object_type: {object_type}, object_oid: {object_oid}, object_name: {object_name}")
            time.sleep(interval)
        if not object_exists:
            validators.raise_and_log(self.logger, MidpointError, f"Gave up trying to find object_type: {object_type}, object_oid: {object_oid}, object_name: {object_name}")


    def _get_object_by_oid_or_name(self, object_type: str, object_oid: str = None, object_name: str = None):
        object = {}
        if object_oid is not None:
            object = self.get_object(object_type, object_oid)
            if object is None:
                raise Exception("object_type: {}, object_oid: {} does not exist.".format(object_type, object_oid))
        elif object_name is not None:
            self._wait_for_object(iterations=self._iterations, interval=self._interval, object_type=object_type, object_name=object_name)
            object = self.get_object_by_name(object_type, object_name)
            if object is None:
                raise Exception("object_type: {}, object_name: {} does not exist.".format(object_type, object_name))
        else:
            raise Exception("Either object_oid or object_name must be specified.")
        return object


    def _get_endpoint_from_element(self, element_name: str):
        object_type_entry = get_object_type_entry(element_name=element_name)
        return object_type_entry["endpoint"]


    def _get_endpoint_from_type(self, type: str):
        object_type_entry = get_object_type_entry(type=type)
        return object_type_entry["endpoint"]


    def _get_endpoint_from_document(self, payload: str, content_type: str) -> str:
        self.logger.trace("Starting")
        element_name = self._get_element_name_from_document(payload=payload, content_type=content_type)
        object_type_entry = get_object_type_entry(element_name=element_name)
        if object_type_entry is not None:
            return object_type_entry["endpoint"]
        else:
            validators.raise_and_log(self.logger, ValueError, f"No object_types entry found for element_name '{element_name}'.")


    def _get_oid_from_document(self, payload: str, content_type: str) -> str:
        self.logger.trace("Starting")
        if content_type == CONTENT_TYPE_XML:
            tree_root = ElementTree.fromstring(payload)
            return tree_root.attrib['oid']
        else:
            validators.raise_and_log(self.logger, ValueError, f"Content type is unhandled: {content_type}.")


    def _get_element_name_from_document(self, payload: str, content_type: str) -> str:
        self.logger.trace("Starting")
        if content_type == CONTENT_TYPE_XML:
            tree_root = ElementTree.fromstring(payload)
            # remove namespace
            object_type = tree_root.tag.split('}', 1)[1] if '}' in tree_root.tag else tree_root.tag
            return object_type
        else:
            validators.raise_and_log(self.logger, ValueError, f"Content type is unhandled: {content_type}.")


    def _extract_display_name(self, ref_or_poly) -> str:
        """Extract a human-readable name from a Midpoint polyString or objectRef."""
        self.logger.debug("Starting")
        if not ref_or_poly:
            return ""
        if isinstance(ref_or_poly, str):
            return ref_or_poly
        if isinstance(ref_or_poly, dict):
            return (
                ref_or_poly.get("orig")
                or ref_or_poly.get("targetName", {}).get("orig", "")
                or ref_or_poly.get("name", {}).get("orig", "")
                or ""
            )
        return ""


    # ###############################################################################
    # Normalize objects

    def _normalize_object_reference(self, reference: dict, allowed_type: str = "*") -> list[dict]:
        self.logger.trace(f"Starting, reference: {reference}. Allowed type: {allowed_type}")
        normalized_reference = {}
        reference_type = reference["type"].removeprefix("c:")
        reference_oid = reference["oid"]
        self.logger.trace(f"Reference({reference_type}): {reference_oid}")
        if allowed_type == "*" or reference_type == allowed_type:
            self.logger.trace("Processing reference.")
            normalized_reference["type"] = reference_type.removesuffix("Type")
            reference_object = self._get_object(object_type=reference_type, object_oid=reference_oid)
            normalized_reference["oid"] = reference_oid
            normalized_reference["name"] = reference_object["name"]
            if "relation" in reference:
                normalized_reference["relation"] = reference["relation"]
        self.logger.trace(f"Returning normalized reference: {normalized_reference}")
        return normalized_reference


    def _normalize_object_references(self, references, allowed_type: str = "*") -> list[dict]:
        normalized_references = []
        if isinstance(references, dict):
            references = [references]
        self.logger.trace(f"Processing {len(references)} reference/s. Type: {allowed_type}")
        for reference in references:
            normalized_reference = self._normalize_object_reference(reference=reference, allowed_type=allowed_type)
            if normalized_reference:
                normalized_references.append(normalized_reference)
        self.logger.trace(f"Returning normalized references: {normalized_references}")
        return normalized_references


    def _normalize_assignments(self, assignments, allowed_type: str = "*", allowed_status: str = "*") -> list[dict]:
        self.logger.trace(f"Processing assignments: {assignments}")
        normalized_assignments = []
        if isinstance(assignments, dict):
            assignments = [assignments]
        for assignment in assignments:
            normalized_assignment = {}
            targetRef = assignment["targetRef"]
            target_type = targetRef["type"].removeprefix("c:")
            assignment_status = assignment.get("activation").get("effectiveStatus")
            if allowed_type in ["*", target_type] and allowed_status in ["*", assignment_status]:
                normalized_assignment["type"] = target_type.removesuffix("Type")
                target_oid = targetRef["oid"]
                target_object = self._get_object(object_type=target_type, object_oid=target_oid)
                normalized_assignment["oid"] = target_oid
                normalized_assignment["relation"] = targetRef["relation"]
                normalized_assignment["name"] = target_object["name"]
                normalized_assignments.append(normalized_assignment)
        return normalized_assignments


    def _normalize_case_workitem(self, workitem: dict) -> dict:
        self.logger.trace("workitem: {}", workitem)
        normalized_workitem = {}
        normalized_workitem["id"] = workitem["@id"]
        normalized_workitem["name"] = workitem["name"]["orig"]
        normalized_workitem["assignee"] = self._normalize_object_reference(workitem["assigneeRef"])
        return normalized_workitem


    def _normalize_case_workitems(self, workitems) -> dict:
        normalized_workitems = []
        if isinstance(workitems, dict):
            workitems = [workitems]
        self.logger.trace(f"Processing {len(workitems)} workitem/s")
        for workitem in workitems:
            normalized_workitems.append(self._normalize_case_workitem(workitem))
        return normalized_workitems


    def _normalize_object(self, raw_object: dict) -> dict:
        self.logger.trace(f"Processing object: {raw_object}")
        normalized_object = {}
        object_type = ""

        if "@type" in raw_object:
            object_type = raw_object["@type"].removeprefix("c:").removesuffix("Type")
            normalized_object["object_type"]=object_type

        for attr in ["oid", "name", "description"]:
            if attr in raw_object:
                normalized_object[attr]=raw_object[attr]

        match object_type:
            case "Case":
                for attr in ["state"]:
                    if attr in raw_object:
                        normalized_object[attr]=raw_object[attr]
                normalized_object["create_timestamp"]=raw_object.get("@metadata", {}).get("storage", {}).get("createTimestamp")
                for reference in ["object", "target", "requestor"]:
                    reference_key = f"{reference}Ref"
                    if reference_key in raw_object:
                        self.logger.debug(f"Normalizing reference: {reference_key}")
                        normalized_object[reference] = self._normalize_object_reference(raw_object[reference_key])
                if "workItem" in raw_object:
                    normalized_object["workitems"] = self._normalize_case_workitems(raw_object["workItem"])
                else:
                    # discard parent "empty" case
                    return {}
                # override name
                name_orig = normalized_object["name"]["orig"]
                normalized_object["name"] = name_orig
            case "Role":
                for attr in ["requestable"]:
                    if attr in raw_object:
                        normalized_object[attr]=raw_object[attr]
            case "User":
                for attr in ["givenName", "familyName", "fullName", "emailAddress", "title", "personalNumber"]:
                    if attr in raw_object:
                        normalized_object[attr]=raw_object[attr]
                if "extension" in raw_object:
                    extension = raw_object["extension"]
                    for ext_attr in ["metaPersonalEmail"]:
                        normalized_object[ext_attr] = extension[ext_attr]
                normalized_object["role_assignment"] = self._normalize_assignments(raw_object.get("assignment", []), "RoleType", "enabled")
                normalized_object["role_membership"] = self._normalize_object_references(raw_object.get("roleMembershipRef", []), "RoleType")
        return normalized_object


    def _normalize_objects(self, raw_objects: list[dict]) -> list[dict]:
        self.logger.debug(f"Processing {len(raw_objects)} objects")
        normalized_objects = []
        for raw_object in raw_objects:
            normalized_object = self._normalize_object(raw_object)
            # discard empty objects
            if normalized_object:
                normalized_objects.append(normalized_object)
        return normalized_objects


    # ###############################################################################
    # Importers

    def process_subfolders(self, subfolder_path: str):
        if not os.path.exists(subfolder_path):
            self.logger.error("Folder not found: {}.", subfolder_path)
            return
        self.logger.debug("Processing dir: {}.", subfolder_path)
        for object_type_folder in sorted(os.scandir(subfolder_path), key=lambda path: path.name):
            if object_type_folder.is_dir():
                self.process_folder(folder_path=object_type_folder.path)


    def process_folder(self, folder_path: str):
        self.logger.debug("Processing dir: {}.", folder_path)
        if not os.path.exists(folder_path):
            self.logger.error("Folder not found: {}.", folder_path)
            return
        for file in sorted(os.scandir(folder_path), key=lambda path: path.name):
            if file.is_file():
                self._process_file(file=file)


    def _process_file(self, file: str):
        if not os.path.exists(file):
            self.logger.error("File not found: {}.", file)
            return

        if file.path.endswith(".xml"):
            self.logger.debug("Processing file: {}.", file.name)
            shutil.copyfile(file.path, self.temp_file_path)
            self.properties.replace(self.temp_file_path)
            self._put_object_from_file(path=self.temp_file_path, content_type=CONTENT_TYPE_XML)
            return

        if file.is_file() and file.path.endswith(".json"):
            self.logger.debug("Processing file: {}.".format(file.path))
            validators.raise_and_log(self.logger, MidpointError, "JSON Implementation pending.")

        if file.is_file() and file.path.endswith(".yaml"):
            self.logger.debug("Processing file: {}.".format(file.path))
            shutil.copyfile(file.path, self.temp_file_path)
            self.properties.replace(self.temp_file_path)
            with open(self.temp_file_path) as f:
                yaml_data = yaml.safe_load(f)
            if isinstance(yaml_data, dict):
                self.logger.trace("Processing operation in YAML (dict): {}".format(yaml_data))
                self._process_operation(yaml_data)
            if isinstance(yaml_data, list):
                self.logger.trace("Processing each operation in YAML (list): {}".format(yaml_data))
                for operation in yaml_data:
                    self._process_operation(operation)
            return

        validators.raise_and_log(self.logger, MidpointError, "Unknown file type: {}.".format(file.path))


    def _put_object_from_file(self, path: str, content_type: str) -> dict:
        self.logger.trace("Starting")
        payload = ""
        with open(path, "r") as file_object:
            payload = file_object.read()
            file_object.close()
        response = self._put_object(payload=payload, content_type=content_type)
        return response


    def _put_object(self, payload: str, content_type: str) -> dict:
        self.logger.trace("Starting")
        endpoint = self._get_endpoint_from_document(payload=payload, content_type=content_type)
        oid = self._get_oid_from_document(payload=payload, content_type=content_type)
        path = endpoint + "/" + oid
        response = self._http_put(path=path, body=payload, content_type=content_type)
        return response


    def _process_operation(self, json_data):
        operation_type = json_data.get('operation_type')
        self.logger.trace("Processing operation based on operation_type: {}".format(operation_type))
        if operation_type.startswith("_"):
            validators.raise_and_log(self.logger, MidpointError, "OperationType is not allowed (internal method): {}".format(operation_type))
        operation_function = getattr(self, operation_type, None)
        if not callable(operation_function):
            validators.raise_and_log(self.logger, MidpointError, "OperationType is unknown: {}".format(operation_type))
        operation_kwargs = {key: value for key, value in json_data.items() if key != 'operation_type'}
        operation_function(**operation_kwargs)
