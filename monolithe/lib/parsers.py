# -*- coding: utf-8 -*-

import os
import json
import requests
import sys

from copy import deepcopy
from .printer import Printer
from .managers import TaskManager
from .utils import Utils

ENTRY_POINT = '/api-docs'
SCHEMA_FILEPATH = '/schema'
SWAGGER_APIS = 'apis'
SWAGGER_APIVERSION = 'apiVersion'
SWAGGER_PATH = 'path'

## Monkey patch to use PROTOCOL_TLSv1 by default in requests
from requests.packages.urllib3.poolmanager import PoolManager
import ssl

from functools import wraps


def sslwrap(func):
    @wraps(func)
    def bar(*args, **kw):
        kw['ssl_version'] = ssl.PROTOCOL_TLSv1
        return func(*args, **kw)
    return bar

PoolManager.__init__ = sslwrap(PoolManager.__init__)
## end of monkey patch


class SwaggerParserFactory(object):
    """ Factory class

    """

    @classmethod
    def create(cls, url=None, path=None, apiversion=None):
        """ Return the appropriate Parser according to the url or path given

        """
        if path:
            return SwaggerFileParser(path=path, apiversion=apiversion)

        return SwaggerURLParser(url=url, apiversion=apiversion)


class AbstractSwaggerParser(object):
    """ Abstract parser

    """
    # Methods to override

    def path_for_swagger_model(self, swagger_filepath):
        """ Compute the path to get the swagger model

            Returns:
                the path to get the swagger model

        """
        raise Exception('Not implemented')

    def get_api_docs(self):
        """ Retrieve api-docs and returns the corresponding JSON

            Returns:
                the corresponding JSON
        """
        raise Exception('Not implemented')

    def get_swagger_model(self, path, resource_name):
        """ Get the swagger file description and return a JSON

            Returns:
                the corresponding JSON
        """
        raise Exception('Not implemented')

    def get_information(self, path):
        """ Return information about

            Returns:
                (package, resource_name)
        """
        raise Exception('Not implemented')

    # Methods

    def grab_all(self):
        """ Read a JSON file and returns a dictionnary

            Args:
                url: the URL of to grab all swagger information

            Returns:
                Returns a dictionary containing all models definition

            Example:
                if url is set to http://host:port/V3_0, it will grab all information
                described in http://host:port/V3_0/schema/api-docs according to swagger
                specification
        """
        data = self.get_api_docs()

        if SWAGGER_APIS not in data:
            Printer.raiseError("No apis information found in api-docs")

        if SWAGGER_APIVERSION not in data:
            Printer.raiseError("No api version found in api-docs")

        if self.apiversion is None:
            self.apiversion = Utils.get_version(data[SWAGGER_APIVERSION])

        task_manager = TaskManager()

        models = dict()
        for api in data[SWAGGER_APIS]:
            path = self.path_for_swagger_model(api[SWAGGER_PATH])
            task_manager.start_task(method=self._grab_resource, path=path, results=models)

        task_manager.wait_until_exit()

        return models

    def _grab_resource(self, path, results=dict()):
        """ Grab resource information

            Args:
                path: the path where to grab information
                results: the dictionary to fill with all information

            Returns:
                Fills result dictionary
        """

        (package, resource_name) = self.get_information(path)
        infos = self.get_swagger_model(path, resource_name)

        if resource_name == 'Metadata':
            # Make copy for global metadata and aggregate
            # Sad that I had to do that :(

            metadata_info = deepcopy(infos)
            global_metadata_info = deepcopy(infos)
            aggregate_metadata_info = deepcopy(infos)

            metadata_info['apis'] = []
            global_metadata_info['apis'] = []
            aggregate_metadata_info['apis'] = []

            metadata_info['models']['Metadata']['id'] = 'Metadata'
            global_metadata_info['models']['Metadata']['id'] = 'GlobalMetadata'
            aggregate_metadata_info['models']['Metadata']['id'] = 'AggregateMetadata'

            for api in infos['apis']:
                api_copy = deepcopy(api)
                if '/aggregatemetadatas' in api['path']:
                    aggregate_metadata_info['apis'].append(api_copy)
                elif '/globalmetadatas' in api['path']:
                    global_metadata_info['apis'].append(api_copy)
                else:
                    metadata_info['apis'].append(api_copy)

            metadata_info['package'] = package
            global_metadata_info['package'] = package
            aggregate_metadata_info['package'] = package

            results['Metadata'] = metadata_info
            results['GlobalMetadata'] = global_metadata_info
            results['AggregateMetadata'] = aggregate_metadata_info

        else:
            infos['package'] = package
            results[resource_name] = infos


class SwaggerURLParser(AbstractSwaggerParser):
    """ Swagger Parser grabs all information from a JSON File

    """
    def __init__(self, url, apiversion):
        """ Initializes a new URL parser

        """
        self.url = url
        self.apiversion = apiversion

        if self.apiversion is None:
            Printer.raiseError("Please specify your apiversion using -v option")

        self.base_path = '%sV%s' % (self.url, str(self.apiversion).replace(".", "_"))
        self.schema_url = '%s%s%s' % (self.base_path, SCHEMA_FILEPATH, ENTRY_POINT)

    def path_for_swagger_model(self, swagger_filepath):
        """ Compute the path to get the swagger model

            Returns:
                the path to get the swagger model

        """
        return self.base_path + SCHEMA_FILEPATH + swagger_filepath

    def get_api_docs(self):
        """ Retrieve api-docs and returns the corresponding JSON

            Returns:
                the corresponding JSON
        """
        response = requests.get(self.schema_url, verify=False)

        if response.status_code != 200:
            Printer.raiseError("[HTTP %s] Could not access %s" % (response.status_code, self.schema_url))

        data = None
        try:
            data = response.json()
        except:
            Printer.raiseError("Could not load properly json from %s" % self.schema_url)

        return data

    def get_swagger_model(self, path, resource_name):
        """ Get the swagger file description and return a JSON

        """
        try:  # Ugly hack due to Java issue: http://mvjira.mv.usa.alcatel.com/browse/VSD-546
            response = requests.get(path, verify=False)
        except requests.exceptions.SSLError:
            response = requests.get(path, verify=False)

        if response.status_code != 200:
            Printer.raiseError("[HTTP %s] An error occured while retrieving %s at %s" % (response.status_code, resource_name, path))

        data = None
        try:
            data = response.json()
        except:
            Printer.raiseError("Could not load properly json from %s" % path)

        return data

    def get_information(self, path):
        """ Return information about

            Returns:
                (package, resource_name)
        """
        return path.split(SCHEMA_FILEPATH)[1].rsplit('/', 1)


class SwaggerFileParser(AbstractSwaggerParser):
    """ Parse Swagger files

    """
    def __init__(self, path, apiversion=None):
        """ Initializes a File parser

        """
        self.path = path
        self.apiversion = apiversion
        self.extension = ''

        self.schema_path = '%s%s%s' % (self.path, ENTRY_POINT, self.extension)

    def path_for_swagger_model(self, swagger_filepath):
        """ Compute the path to get the swagger model

            Returns:
                the path to get the swagger model

        """
        return '%s%s%s' % (self.path, swagger_filepath, self.extension)

    def get_api_docs(self):
        """ Retrieve api-docs and returns the corresponding JSON

            Returns:
                the corresponding JSON
        """
        schema_path = '%s%s%s' % (self.path, ENTRY_POINT, self.extension)

        if not os.path.isfile(schema_path):
            Printer.raiseError("[File Path] Could not access %s" % (schema_path))

        try:
            data = json.load(open(schema_path))
        except Exception:
            e = sys.exc_info()[1]
            Printer.raiseError("[File Path] Could load json file %s due to following error:\n%s" % (schema_path, e.args[0]))

        return data

    def get_swagger_model(self, path, resource_name):
        """ Get the swagger file description and return a JSON

            Returns:
                the corresponding JSON
        """
        if not os.path.isfile(path):
            Printer.raiseError("[File Path] Could not access %s" % (path))

        data = None
        try:
            data = json.load(open(path))
        except Exception:
            e = sys.exc_info()[1]
            Printer.raiseError("[File Path] Could load json file %s due to following error:\n%s" % (path, e.args[0]))

        return data

    def get_information(self, path):
        """ Return information about

            Returns:
                (package, resource_name)
        """
        return path.split(self.path)[1].rsplit('/', 1)