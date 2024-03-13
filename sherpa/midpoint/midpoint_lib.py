# sherpa-py-midpoint is available under the MIT License. https://github.com/Identicum/sherpa-py-midpoint/
# Copyright (c) 2024, Identicum - https://identicum.com/
#
# Author: Gustavo J Gallardo - ggallard@identicum.com
#

import base64
import json
import requests
import shutil
import time
import os
from xml.etree import ElementTree
from sherpa.utils import validators
from sherpa.utils import http
from sherpa.utils.basics import Logger

endpoints = {
    "ArchetypeType": "archetypes",
    "ConnectorHostType": "connectorHosts",
    "ConnectorType": "connectors",
    "FunctionLibraryType": "functionLibraries",
    "GenericObjectType": "genericObjects",
    "ObjectTemplateType": "objectTemplates",
    "OrgType": "orgs",
    "ResourceType": "resources",
    "RoleType": "roles",
    "SecurityPolicyType": "securityPolicies",
    "ShadowType": "shadows",
    "SystemConfigurationType": "systemConfigurations",
    "TaskType": "tasks",
    "UserType": "users",
    "ValuePolicyType": "valuePolicies"
}


class Midpoint:
    def __init__(self, mp_baseurl, mp_username, mp_password, properties, logger=Logger("Midpoint"), temp_file_path="/tmp/midpoint_object", iterations=10, interval=10):
        self._baseurl = mp_baseurl
        mp_credentials = "{}:{}".format(mp_username, mp_password)
        self._credentials = base64.b64encode(mp_credentials.encode())
        self._logger = logger
        self._properties = properties
        self._temp_file_path = temp_file_path
        url = "{}users/00000000-0000-0000-0000-000000000002".format(self._baseurl)
        headers = {'Authorization': 'Basic {}'.format(self._credentials.decode()), 'Content-Type': 'application/xml'}
        http.wait_for_endpoint(url, iterations, interval, logger, headers)


    def _midpoint_call(self, method, endpoint, oid, payload, content_type = 'application/xml'):
        url = self._baseurl + endpoint
        if method=="GET" or method=="PATCH" or method=="PUT":
            url = url + "/" + oid
        headers = {
            'Authorization': 'Basic {}'.format(self._credentials.decode()),
            'Content-Type': content_type
        }
        self._logger.debug("Calling URL: {} with method: {}, headers: {}", url, method, headers)
        self._logger.trace("payload: {}", payload)
        http_response = requests.request(method, url, headers=headers, data=payload)
        self._logger.trace("http_response: {}", http_response)
        response_code = http_response.status_code
        self._logger.trace("response_code: {}", response_code)
        if response_code not in [200, 201, 202, 204]:
            validators.raise_and_log(self._logger, IOError, "Invalid HTTP response received: '{}'.", response_code)
        response = http_response.text.encode('utf8')
        self._logger.trace("response: {}", response)
        return response


    def _get_endpoint(self, object_type):
        for endpoint_class, endpoint_rest in endpoints.items():
            if endpoint_class.lower().startswith(object_type.lower()):
                return endpoint_rest
        raise AttributeError("Can't find REST type for class " + object_type)


    def _get_oid_from_document(self, xml_data):
        tree_root = ElementTree.fromstring(xml_data)
        return tree_root.attrib['oid']


    def _get_objectType_from_document(self, xml_data):
        tree_root = ElementTree.fromstring(xml_data)
        # remove namespace
        object_type = tree_root.tag.split('}', 1)[1] if '}' in tree_root.tag else tree_root.tag
        return object_type


    def _get_endpoint_from_document(self, xml_data):
        object_type = self._get_objectType_from_document(xml_data)
        return self._get_endpoint(object_type)


    def get_object(self, object_type, object_oid):
        endpoint = self._get_endpoint(object_type)
        response = self._midpoint_call("GET", endpoint, oid=object_oid, payload=None)
        return response


    def get_object_by_name(self, object_type, object_name):
        endpoint = self._get_endpoint(object_type) + "/search"
        payload = """<?xml version="1.0" encoding="utf-8"?>
                    <query>
                        <filter>
                            <equal>
                                <path>name</path>
                                <value>{}</value>
                            </equal>
                        </filter>
                    </query>""".format(object_name)
        response = self._midpoint_call("POST", endpoint, payload=payload, oid=None)
        self._logger.trace("response: {}", response)
        tree_root = ElementTree.fromstring(response)
        objects = tree_root.findall('{http://midpoint.evolveum.com/xml/ns/public/common/api-types-3}object')
        self._logger.trace("objects: {}", objects)
        object = objects[0]
        self._logger.trace("object: {}", object)
        object_string = ElementTree.tostring(object, encoding="unicode")
        self._logger.trace("object_string: {}", object_string)
        return object_string


    def get_object_oid(self, object_type, object_name):
        object_document = self.get_object(object_type, object_name)
        return self._get_oid_from_document(object_document)


    def put_object(self, xml_data):
        endpoint = self._get_endpoint_from_document(xml_data)
        oid = self._get_oid_from_document(xml_data)
        response = self._midpoint_call("PUT", endpoint, oid=oid, payload=xml_data)
        return response


    def put_object_from_file(self, xml_file):
        self._logger.debug("Starting")
        xml_data = ""
        with open(xml_file, "r") as file_object:
            xml_data = file_object.read()
            file_object.close()
        response = self.put_object(xml_data)
        return response


    def patch_object(self, xml_data, endpoint, oid):
        self._logger.debug("Starting")
        response = self._midpoint_call("PATCH", endpoint, oid=oid, payload=xml_data)
        return response


    def patch_object_from_file(self, xml_file, endpoint, oid):
        self._logger.debug("Starting")
        xml_data = ""
        with open(xml_file, "r") as file_object:
            xml_data = file_object.read()
            file_object.close()
        response = self.patch_object(xml_data, endpoint, oid)
        return response


    def check_object_exists(self, object_type, object_oid):
        object_document = self.get_object(object_type, object_oid)
        if object_document is None:
            return False
        else:
            return True


    def _add_inducement(self, inducement_type, target_type, inducement_oid=None, inducement_name=None, target_oid=None, target_name=None):
        self._logger.trace("_add_inducement(inducement_type={}, inducement_oid={}, inducement_name={}, target_type={}, target_oid={}, target_name={}", inducement_type, inducement_oid, inducement_name, target_type, target_oid, target_name)
        target_object = {}
        if target_oid is not None:
            target_object = self.get_object(target_type, target_oid)
            if target_object is None:
                raise Exception("target_type: {}, target_oid: {} does not exist.".format(target_type, target_oid))
        elif target_name is not None:
            target_object = self.get_object_by_name(target_type, target_name)
            if target_object is None:
                raise Exception("target_type: {}, target_name: {} does not exist.".format(target_type, target_name))
            target_oid = self._get_oid_from_document(target_object)
        else:
            raise Exception("Either target_oid or target_name must be specified.")

        self.wait_for_object(iterations=2, interval=30, object_type=inducement_type, object_oid=inducement_oid, object_name=inducement_name)
        self.wait_for_object(iterations=2, interval=30, object_type=target_type, object_oid=target_oid, object_name=target_name)

        inducement_object = {}
        if inducement_oid is not None:
            inducement_object = self.get_object(inducement_type, inducement_oid)
            if inducement_object is None:
                raise Exception("inducement_type: {}, inducement_oid: {} does not exist.".format(inducement_type, inducement_oid))
        elif inducement_name is not None:
            inducement_object = self.get_object_by_name(inducement_type, inducement_name)
            if inducement_object is None:
                raise Exception("inducement_type: {}, inducement_name: {} does not exist.".format(inducement_type, inducement_name))
            inducement_oid = self._get_oid_from_document(inducement_object)
        else:
            raise Exception("Either inducement_oid or inducement_name must be specified.")

        self._logger.debug("Checking if inducement already exists for target_object: {}, target_oid: {}, inducement_name: {}, inducement_oid: {}", target_name, target_oid, inducement_name, inducement_oid)
        target_object_normalized = target_object.decode() if type(target_object) is bytes else target_object
        if inducement_oid in target_object_normalized:
            self._logger.debug("Inducement already exists for target_object: {}, target_oid: {}, inducement_name: {}, inducement_oid: {}", target_name, target_oid, inducement_name, inducement_oid)
            return

        self._logger.debug("Adding inducement type: {}, oid: {} to object type: {}, oid: {}", inducement_type, inducement_oid, target_type, target_oid)
        if inducement_type=="ResourceType":
            new_inducement = """<c:construction>
                                    <c:resourceRef type="c:ResourceType" oid="{}" />
                                </c:construction>""".format(inducement_oid)
        elif inducement_type=="RoleType":
            new_inducement = """<c:targetRef type="c:RoleType" oid="{}" />""".format(inducement_oid)
        else:
            raise Exception("Unknown structure for inducement")

        xml_data = """<objectModification
                    xmlns='http://midpoint.evolveum.com/xml/ns/public/common/api-types-3'
                    xmlns:c='http://midpoint.evolveum.com/xml/ns/public/common/common-3'
                    xmlns:t='http://prism.evolveum.com/xml/ns/public/types-3'>
                        <itemDelta>
                            <t:modificationType>add</t:modificationType>
                            <t:path>c:inducement</t:path>
                            <t:value>
                                {}
                            </t:value>
                        </itemDelta>
                    </objectModification>""".format(new_inducement)
        endpoint = self._get_endpoint(target_type)
        response = self.patch_object(xml_data, endpoint, target_oid)
        return response

    def add_resource_inducement_to_role(self, resource_oid=None, resource_name=None, role_oid=None, role_name=None):
        response = self._add_inducement(inducement_type="ResourceType", inducement_oid=resource_oid, inducement_name=resource_name, target_type="RoleType", target_oid=role_oid, target_name=role_name)
        return response

    def add_role_inducement_to_role(self, child_oid=None, child_name=None, parent_oid=None, parent_name=None):
        response = self._add_inducement(inducement_type="RoleType", inducement_oid=child_oid, inducement_name=child_name, target_type="RoleType", target_oid=parent_oid, target_name=parent_name)
        return response

    def add_role_inducement_to_archetype(self, role_oid=None, role_name=None, archetype_oid=None, archetype_name=None):
        response = self._add_inducement(inducement_type="RoleType", inducement_oid=role_oid, inducement_name=role_name, target_type="ArchetypeType", target_oid=archetype_oid, target_name=archetype_name)
        return response

    def wait_for_object(self, iterations, interval, object_type, object_oid=None, object_name=None):
        object_exists = False
        for iteration in range(iterations):
            self._logger.debug("Iteration #: {}", iteration)
            try:
                if object_oid is not None:
                    self._logger.debug("Checking if object exists. Type: {}, oid: {}", object_type, object_oid)
                    if self.check_object_exists(object_type, object_oid):
                        object_exists = True
                        break
                elif object_name is not None:
                    self._logger.debug("Checking if object exists. Type: {}, name: {}", object_type, object_name)
                    if self.get_object_by_name(object_type, object_name) is not None:
                        object_exists = True
                        self._logger.debug("Checking if object exists. Type: {}, name: {}", object_type, object_name)
                        break
                else:
                    self._logger.error("Either object_oid or object_name must be specified.")
            except:
                self._logger.debug("Exception while trying to find object_type: {}, object_oid: {}, object_name: {}", object_type, object_oid, object_name)
            self._logger.trace("Waiting {} seconds for object_type: {}, object_oid: {}, object_name: {}", interval, object_type, object_oid, object_name)
            time.sleep(interval)
        if not object_exists:
            raise Exception("Gave up trying to find object_type: {}, object_oid: {}, object_name: {}".format(object_type, object_oid, object_name))
    
    def process_subfolders(self, subfolder_path):
        if not os.path.exists(subfolder_path):
            self._logger.error("Folder not found: {}.", subfolder_path)
            return
        self._logger.debug("Processing dir: {}.", subfolder_path)
        for object_type_folder in sorted(os.scandir(subfolder_path), key=lambda path: path.name):
            if object_type_folder.is_dir():
                self.process_folder(object_type_folder.path)

    def process_folder(self, folder_path):
        self._logger.debug("Processing dir: {}.", folder_path)
        if not os.path.exists(folder_path):
            self._logger.error("Folder not found: {}.", folder_path)
            return
        for file in sorted(os.scandir(folder_path), key=lambda path: path.name):
            if file.is_file():
                self.process_file(file)

    def process_file(self, file):
        if not os.path.exists(file):
            self._logger.error("File not found: {}.", file)
            return
        
        if file.path.endswith(".xml"):
            self._logger.debug("Processing file: {}.", file.name)
            shutil.copyfile(file.path, self._temp_file_path)
            self._properties.replace(self._temp_file_path)
            self.put_object_from_file(self._temp_file_path)

        if file.is_file() and file.path.endswith(".patch"):
            self._logger.debug("Processing file: {}.", file.name)
            shutil.copyfile(file.path, self._temp_file_path)
            self._properties.replace(self._temp_file_path)
            self._logger.trace("File name: {}.", file.name)
            oid = file.name.split(".")[0]
            folder_path = os.path.dirname(file)
            self._logger.debug("Spliting folder name for endpoint: {}.", folder_path)
            endpoint = folder_path.split("_")[1]
            self.patch_object_from_file(self._temp_file_path, endpoint, oid)

        if file.is_file() and file.path.endswith(".json"):
            self._logger.debug("Processing file: {}.".format(file.path))
            shutil.copyfile(file.path, self._temp_file_path)
            self._properties.replace(self._temp_file_path)
            with open(self._temp_file_path) as f:
                json_data = json.load(f)
            self._logger.trace("JSON data: {}".format(json_data))
            if isinstance(json_data, dict):
                self._logger.trace("JSON is dictionary")
                self.process_operation(json_data)
            if isinstance(json_data, list):
                self._logger.trace("JSON is list")
                for operation in json_data:
                    self.process_operation(operation)

    def process_operation(self, json_data):
        self._logger.trace("Processing operation based on operation_type: {}".format(json_data.get('operation_type')))
        match json_data["operation_type"]:
            case "add_resource_inducement_to_role":
                self.add_resource_inducement_to_role(resource_oid=json_data.get('resource_oid'), resource_name=json_data.get('resource_name'), role_oid=json_data.get('role_oid'), role_name=json_data.get('role_name'))
            case "add_role_inducement_to_role":
                self.add_role_inducement_to_role(child_oid=json_data.get('child_oid'), child_name=json_data.get('child_name'), parent_oid=json_data.get('parent_oid'), parent_name=json_data.get('parent_name'))
            case "add_role_inducement_to_archetype":
                self.add_role_inducement_to_archetype(role_oid=json_data.get('role_oid'), role_name=json_data.get('role_name'), archetype_oid=json_data.get('archetype_oid'), archetype_name=json_data.get('archetype_name'))
            case "set_system_configuration":
                self.set_system_configuration(modification_type=json_data.get('modification_type'), path=json_data.get('path'), value=json_data.get('value'))
            case "set_class_logger":
                self.set_class_logger(package=json_data.get('package'), level=json_data.get('level'))
            case "set_notification_configuration":
                self.set_notification_configuration(modification_type=json_data.get('modification_type'), path=json_data.get('path'), json=json_data.get('value'))
            case "set_message_configuration":
                self.set_message_configuration(modification_type=json_data.get('modification_type'), path=json_data.get('path'), json=json_data.get('value'))
            case _:
                self._logger.error("OperationType is unknown: {}.", json_data["operation_type"])

    def set_system_configuration(self, modification_type, path, value):
        self._logger.debug("set_system_configuration(modification_type={}, path={}, value={}", modification_type, path, value)
        if isinstance(value, dict):
            value = self.json_to_xml(value)
        xml_data = """<objectModification
                xmlns='http://midpoint.evolveum.com/xml/ns/public/common/api-types-3'
                xmlns:c='http://midpoint.evolveum.com/xml/ns/public/common/common-3'
                xmlns:org='http://midpoint.evolveum.com/xml/ns/public/common/org-3'
                xmlns:t='http://prism.evolveum.com/xml/ns/public/types-3'>
                    <itemDelta>
                        <t:modificationType>{}</t:modificationType>
                        <t:path>{}</t:path>
                        <t:value>{}</t:value>
                    </itemDelta>
                </objectModification>""".format(modification_type, path, value)
        endpoint = self._get_endpoint("SystemConfigurationType")
        response = self.patch_object(xml_data, endpoint, "00000000-0000-0000-0000-000000000001")
        return response
    
    def parse_class_logger(self, xml_content):
        self._logger.trace("Parsing existing classLoggers.")
        ns = {'c': 'http://midpoint.evolveum.com/xml/ns/public/common/common-3'}
        root = ElementTree.fromstring(xml_content)
        class_loggers = root.findall('c:logging/c:classLogger', namespaces=ns)
        result = []
        for logger in class_loggers:
            level = logger.find('c:level', namespaces=ns).text
            package = logger.find('c:package', namespaces=ns).text
            logger_id = logger.get('id')
            entry = {
                "id": logger_id,
                "operation_type": "set_class_logger",
                "package": package,
                "level": level
            }
            result.append(entry)
        self._logger.trace("existing classLoggers: {}".format(result))
        return result

    def replace_class_logger(self, id, level):
        path = "c:logging/c:classLogger[{}]/level".format(id)
        self.set_system_configuration("REPLACE", path, level)
        
    def add_class_logger(self, package, level):
        value = """
                <c:level>{}</c:level>
                <c:package>{}</c:package>
        """.format(level, package)
        path = "c:logging/c:classLogger"
        self.set_system_configuration("ADD", path, value)

    def set_class_logger(self, package, level):
        system_configuration_object = self.get_object("SystemConfigurationType", "00000000-0000-0000-0000-000000000001")
        existing_logger_id = None
        logger_entries = self.parse_class_logger(system_configuration_object)
        self._logger.trace("Existing logger entries: {}", logger_entries)
        for logger_entry in logger_entries:
            self._logger.trace("Checking if logger entry already exist: {}", logger_entry)
            if logger_entry["package"] == package:
                existing_logger_id = logger_entry["id"]
                self._logger.debug("Logger already exists for package: {}, updating log-level", package)
                self.replace_class_logger(existing_logger_id, level)
                return
        self.add_class_logger(package, level)

    def parse_notification_configuration(self, xml_content):
        self._logger.debug("Parsing existing handlers in notification configuration.")
        ns = {'c': 'http://midpoint.evolveum.com/xml/ns/public/common/common-3'}
        root = ElementTree.fromstring(xml_content)
        handlers = root.findall('c:notificationConfiguration/c:handler', namespaces=ns)
        result = []
        for handler in handlers:
            handler_id = handler.get('id')
            handler_name = handler.find('c:name', namespaces=ns).text
            entry = {
                "handler_id": handler_id,
                "handler_name": handler_name
            }
            result.append(entry)
        self._logger.debug("Existing handlers in notification configuration: {}".format(result))
        return result

    def convert_dict(self, obj, namespace_prefix='c'):
        elements = []
        for key, val in obj.items():
            if isinstance(val, dict):
                elements.append('<{}:{}>{}</{}:{}>'.format(namespace_prefix, key, self.convert_dict(val), namespace_prefix, key))
            else:
                elements.append('<{}:{}>{}</{}:{}>'.format(namespace_prefix, key, val, namespace_prefix, key))
        return ''.join(elements)
    
    def json_to_xml(self, json_data):
        xml_content = self.convert_dict(json_data)
        self._logger.trace("xml_content: {}".format(xml_content))
        return xml_content
    
    #ToDo: Add support for modification_type "replace" in set_notification_configuration
    def set_notification_configuration(self, modification_type, path, json):
        notifier_name = json["name"]
        self._logger.debug("notifier_name in user configuration file: {}".format(notifier_name))
        xml_data = self.json_to_xml(json)
        system_configuration_object = self.get_object("SystemConfigurationType", "00000000-0000-0000-0000-000000000001")
        handler_entries = self.parse_notification_configuration(system_configuration_object)
        self._logger.debug("Existing notification handlers in xml: {}".format(handler_entries))
        handler_id = None
        for handler in handler_entries:
            if handler.get('handler_name') == notifier_name:
                self._logger.debug("Handler with name {} already exist. Skiping configuration file.".format(notifier_name))
                handler_id = handler.get('handler_id')
                return
        self._logger.debug("handler_id doesnt exist: {}".format(handler_id))
        self.set_system_configuration(modification_type, path, xml_data)
        return

    def set_message_configuration(self, modification_type, path, json):
        xml_data = self.json_to_xml(json)
        self.set_system_configuration(modification_type, path, xml_data)
        return

    def wait_for_completed_task(self, iterations, interval, object_type="TaskType", object_oid=None, object_name=None):
        self._logger.debug("Waiting task: {}".format(object_name))
        self.wait_for_object(iterations=3, interval=30, object_type=object_type, object_oid=object_oid, object_name=object_name)
        task_completed = False
        for iteration in range(iterations):
            object_task_string = self.get_object_by_name(object_type, object_name)
            namespace = {'ns': 'http://midpoint.evolveum.com/xml/ns/public/common/common-3'}
            result_element = ElementTree.fromstring(object_task_string).find('.//ns:resultStatus', namespace).text
            self._logger.debug("result_element: {}", result_element)
            self._logger.debug("Iteration #: {}", iteration)
            try:
                if result_element == "success":
                    task_completed = True
                    self._logger.debug("Task is '{}'".format(result_element))
                    break
                elif result_element == "in_progress" :
                    self._logger.debug("Task is '{}'".format(result_element))
                else:
                    self._logger.error("Unable to recognize task status")
            except:
                self._logger.debug("Exception while trying to find object_task_string: {}, object_oid: {}, object_name: {}", object_type, object_oid, object_name)
            self._logger.trace("Waiting {} seconds for object_task_string: {}, object_oid: {}, object_name: {}", interval, object_type, object_oid, object_name)
            time.sleep(interval)
        if not task_completed:
            raise Exception("Gave up trying to find object_task_string: {}, object_oid: {}, object_name: {}".format(object_type, object_oid, object_name))