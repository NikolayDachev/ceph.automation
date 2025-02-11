#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright 2018, Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import, division, print_function
__metaclass__ = type

ANSIBLE_METADATA = {
    'metadata_version': '1.1',
    'status': ['preview'],
    'supported_by': 'community'
}

DOCUMENTATION = '''
---
module: ceph_key

author: Sebastien Han (@leseb)

short_description: Manage Cephx key(s)

version_added: "1.1.0"

description:
    - Manage CephX creation, deletion and updates. It can also list and get information about keyring(s).
options:
    cluster:
        description:
            - The ceph cluster name.
        type: str
        required: false
        default: ceph
    name:
        description:
            - name of the CephX key
        type: str
        required: false
    user:
        description:
            - entity used to perform operation. It corresponds to the -n option (--name)
        type: str
        required: false
        default: 'client.admin'
    user_key:
        description:
            - the path to the keyring corresponding to the user being used. It corresponds to the -k option (--keyring)
        type: str
        required: false
    state:
        description:
            - If 'present' is used, the module creates a keyring with the associated capabilities.
            - If 'present' is used and a secret is provided the module will always add the key. Which means it will update the keyring if the secret changes, the same goes for the capabilities.  # noqa: E501
            - If 'absent' is used, the module will simply delete the keyring.
            - If 'generate_secret' is used, the module will simply output a cephx keyring.
        type: str
        required: false
        choices: ['present', 'update', 'absent', 'fetch_initial_keys', 'generate_secret']
        default: present
    caps:
        description:
            - CephX key capabilities
        type: dict
        required: false
    secret:
        description:
            - keyring's secret value
        type: str
        required: false
    import_key:
        description:
            - Wether or not to import the created keyring into Ceph.
            - This can be useful for someone that only wants to generate keyrings but not add them into Ceph.
        type: bool
        required: false
        default: true
    dest:
        description:
            - Destination to write the keyring, can a file or a directory
        type: str
        required: false
        default: /etc/ceph/
    output_format:
        description:
            - The key output format when retrieving the information of an entity.
        type: str
        choices: ['json', 'plain', 'xml', 'yaml']
        required: false
        default: json
    mode:
        description:
            - N/A
        type: raw
    owner:
        description:
            - N/A
        type: str
    group:
        description:
            - N/A
        type: str
    seuser:
        description:
            - N/A
        type: str
    serole:
        description:
            - N/A
        type: str
    selevel:
        description:
            - N/A
        type: str
    setype:
        description:
            - N/A
        type: str
    attributes:
        description:
            - N/A
        type: str
        aliases:
            - attr
    unsafe_writes:
        description:
            - N/A
        type: bool
        default: false
'''

EXAMPLES = '''

- name: Create ceph admin key
  ceph_key:
    name: client.admin
    state: present
    secret: AQAin8tU2DsKFBAAFIAzVTzkL3+gtAjjpQiomw==
    caps:
      mon: allow *
      osd: allow *
      mgr: allow *
      mds: allow
    import_key: false

- name: Create monitor initial keyring
  ceph_key:
    name: mon.
    state: present
    secret: AQAin8tUMICVFBAALRHNrV0Z4MXupRw4v9JQ6Q==
    caps:
      mon: allow *
    dest: "/var/lib/ceph/tmp/"
    import_key: false

- name: Create cephx key
  ceph_key:
    name: client.key
    user: client.bootstrap-rgw
    user_key: /var/lib/ceph/bootstrap-rgw/ceph.keyring
    state: present
    caps: 'mon: "allow rwx"'

- name: Create cephx key but don't import it in Ceph
  ceph_key:
    name: client.key
    state: present
    caps: 'mon: "allow r"'
    import_key: false

- name: Delete cephx key
  ceph_key:
    name: "my_key"
    state: absent

- name: Info cephx admin key (plain)
  ceph_key:
    name: client.admin
    output_format: plain
    state: info
  register: client_admin_key

- name: Fetch cephx keys
  ceph_key:
    state: fetch_initial_keys
'''

RETURN = '''#  '''

try:
    from ansible_collections.ceph.automation.plugins.module_utils.ceph_common import generate_cmd, is_containerized, container_exec, fatal  # type: ignore
except ImportError:
    from module_utils.ceph_common import generate_cmd, is_containerized, container_exec, fatal
try:
    from ansible_collections.ceph.automation.plugins.module_utils.ceph_key_common import exec_commands
except ImportError:
    from module_utils.ceph_key_common import exec_commands

import json
import os
import struct
import time
import base64
import datetime
import socket
from ansible.module_utils.basic import AnsibleModule  # type: ignore

CEPH_INITIAL_KEYS = ['client.admin', 'client.bootstrap-mds', 'client.bootstrap-mgr',  # noqa: E501
                     'client.bootstrap-osd', 'client.bootstrap-rbd', 'client.bootstrap-rbd-mirror', 'client.bootstrap-rgw']  # noqa: E501


def str_to_bool(val):
    try:
        val = val.lower()
    except AttributeError:
        val = str(val).lower()
    if val == 'true':
        return True
    elif val == 'false':
        return False
    else:
        raise ValueError("Invalid input value: %s" % val)


def generate_secret():
    '''
    Generate a CephX secret
    '''

    key = os.urandom(16)
    header = struct.pack('<hiih', 1, int(time.time()), 0, len(key))
    secret = base64.b64encode(header + key)

    return secret


def generate_caps(_type, caps):
    '''
    Generate CephX capabilities list
    '''

    caps_cli = []

    for k, v in caps.items():
        # makes sure someone didn't pass an empty var,
        # we don't want to add an empty cap
        if len(k) == 0:
            continue
        if _type == "ceph-authtool":
            caps_cli.extend(["--cap"])
        caps_cli.extend([k, v])

    return caps_cli


def generate_ceph_authtool_cmd(cluster, name, secret, caps, dest, container_image=None):  # noqa: E501
    '''
    Generate 'ceph-authtool' command line to execute
    '''

    if container_image:
        binary = 'ceph-authtool'
        cmd = container_exec(
            binary, container_image)
    else:
        binary = ['ceph-authtool']
        cmd = binary

    base_cmd = [
        '--create-keyring',
        dest,
        '--name',
        name,
        '--add-key',
        secret,
    ]

    cmd.extend(base_cmd)
    cmd.extend(generate_caps("ceph-authtool", caps))

    return cmd


def create_key(module,
               cluster,
               user,
               user_key,
               name,
               secret,
               caps,
               import_key,
               dest,
               container_image=None):
    '''
    Create a CephX key
    '''

    cmd_list = []
    if not secret:
        secret = generate_secret()

    if user == 'client.admin':
        args = ['import', '-i', dest]
    else:
        args = ['get-or-create', name]
        args.extend(generate_caps(None, caps))
        args.extend(['-o', dest])

    cmd_list.append(generate_ceph_authtool_cmd(
        cluster, name, secret, caps, dest, container_image))

    if import_key or user != 'client.admin':
        cmd_list.append(generate_cmd(sub_cmd=['auth'],
                                     args=args,
                                     cluster=cluster,
                                     user=user,
                                     user_key=user_key,
                                     container_image=container_image))

    return cmd_list


def delete_key(cluster, user, user_key, name, container_image=None):
    '''
    Delete a CephX key
    '''

    cmd_list = []

    args = [
        'del',
        name,
    ]

    cmd_list.append(generate_cmd(sub_cmd=['auth'],
                                 args=args,
                                 cluster=cluster,
                                 user=user,
                                 user_key=user_key,
                                 container_image=container_image))

    return cmd_list


def get_key(cluster, user, user_key, name, dest, container_image=None):
    '''
    Get a CephX key (write on the filesystem)
    '''

    cmd_list = []

    args = [
        'get',
        name,
        '-o',
        dest,
    ]

    cmd_list.append(generate_cmd(sub_cmd=['auth'],
                                 args=args,
                                 cluster=cluster,
                                 user=user,
                                 user_key=user_key,
                                 container_image=container_image))

    return cmd_list


def info_key(cluster, name, user, user_key, output_format, container_image=None):  # noqa: E501
    '''
    Get information about a CephX key
    '''

    cmd_list = []

    args = [
        'get',
        name,
        '-f',
        output_format,
    ]

    cmd_list.append(generate_cmd(sub_cmd=['auth'],
                                 args=args,
                                 cluster=cluster,
                                 user=user,
                                 user_key=user_key,
                                 container_image=container_image))

    return cmd_list


def list_keys(cluster, user, user_key, container_image=None):
    '''
    List all CephX keys
    '''

    cmd_list = []

    args = [
        'ls',
        '-f',
        'json',
    ]

    cmd_list.append(generate_cmd(sub_cmd=['auth'],
                                 args=args,
                                 cluster=cluster,
                                 user=user,
                                 user_key=user_key,
                                 container_image=container_image))

    return cmd_list


def lookup_ceph_initial_entities(module, out):
    '''
    Lookup Ceph initial keys entries in the auth map
    '''

    # convert out to json, ansible returns a string...
    try:
        out_dict = json.loads(out)
    except ValueError as e:
        fatal("Could not decode 'ceph auth list' json output: {}".format(e), module)  # noqa: E501

    entities = []
    if "auth_dump" in out_dict:
        for key in out_dict["auth_dump"]:
            for k, v in key.items():
                if k == "entity":
                    if v in CEPH_INITIAL_KEYS:
                        entities.append(v)
    else:
        fatal("'auth_dump' key not present in json output:", module)  # noqa: E501

    if len(entities) != len(CEPH_INITIAL_KEYS) and not str_to_bool(os.environ.get('CEPH_ROLLING_UPDATE', False)):  # noqa: E501
        # must be missing in auth_dump, as if it were in CEPH_INITIAL_KEYS
        # it'd be in entities from the above test. Report what's missing.
        missing = []
        for e in CEPH_INITIAL_KEYS:
            if e not in entities:
                missing.append(e)
        fatal("initial keyring does not contain keys: " + ' '.join(missing), module)  # noqa: E501
    return entities


def build_key_path(cluster, entity):
    '''
    Build key path depending on the key type
    '''

    if "admin" in entity:
        path = "/etc/ceph"
        keyring_filename = cluster + "." + entity + ".keyring"
        key_path = os.path.join(path, keyring_filename)
    elif "bootstrap" in entity:
        path = "/var/lib/ceph"
        # bootstrap keys show up as 'client.boostrap-osd'
        # however the directory is called '/var/lib/ceph/bootstrap-osd'
        # so we need to substring 'client.'
        entity_split = entity.split('.')[1]
        keyring_filename = cluster + ".keyring"
        key_path = os.path.join(path, entity_split, keyring_filename)
    else:
        return None

    return key_path


def run_module():
    module_args = dict(
        cluster=dict(type='str', required=False, default='ceph'),
        name=dict(type='str', required=False),
        state=dict(type='str', required=False, default='present', choices=['present', 'update', 'absent',  # noqa: E501
                                                                           'fetch_initial_keys', 'generate_secret']),  # noqa: E501
        caps=dict(type='dict', required=False, default=None),
        secret=dict(type='str', required=False, default=None, no_log=True),
        import_key=dict(type='bool', required=False,
                        default=True, no_log=False),
        dest=dict(type='str', required=False, default='/etc/ceph/'),
        user=dict(type='str', required=False, default='client.admin'),
        user_key=dict(type='str', required=False, default=None, no_log=False),
        output_format=dict(type='str', required=False, default='json', choices=['json', 'plain', 'xml', 'yaml']),  # noqa: E501
    )

    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True,
        add_file_common_args=True,
    )

    file_args = module.load_file_common_arguments(module.params)

    # Gather module parameters in variables
    state = module.params['state']
    name = module.params.get('name')
    cluster = module.params.get('cluster')
    caps = module.params.get('caps')
    secret = module.params.get('secret')
    import_key = module.params.get('import_key')
    dest = module.params.get('dest')
    user = module.params.get('user')
    user_key = module.params.get('user_key')
    output_format = module.params.get('output_format')

    # Can't use required_if with 'name' for some reason...
    if state in ['present', 'absent', 'update'] and not name:
        fatal(f'"state" is "{state}" but "name" is not defined.', module)

    changed = False
    cmd = ''

    result = dict(
        changed=changed,
        stdout='',
        stderr='',
        rc=0,
        start='',
        end='',
        delta='',
    )

    if module.check_mode:
        module.exit_json(**result)

    startd = datetime.datetime.now()

    # will return either the image name or None
    container_image = is_containerized()

    # Test if the key exists, if it does we skip its creation
    # We only want to run this check when a key needs to be added
    # There is no guarantee that any cluster is running and we don't need one
    _secret = secret
    _caps = caps
    key_exist = 1

    if not user_key:
        user_key_filename = '{}.{}.keyring'.format(cluster, user)
        user_key_dir = '/etc/ceph'
        user_key_path = os.path.join(user_key_dir, user_key_filename)
    else:
        user_key_path = user_key

    if (state in ["present", "update"]):
        # if dest is not a directory, the user wants to change the file's name
        # (e,g: /etc/ceph/ceph.mgr.ceph-mon2.keyring)
        if not os.path.isdir(dest):
            file_path = dest
        else:
            if 'bootstrap' in dest:
                # Build a different path for bootstrap keys as there are stored
                # as /var/lib/ceph/bootstrap-rbd/ceph.keyring
                keyring_filename = cluster + '.keyring'
            else:
                keyring_filename = cluster + "." + name + ".keyring"
            file_path = os.path.join(dest, keyring_filename)

        file_args['path'] = file_path

        if import_key:
            _info_key = []
            rc, cmd, out, err = exec_commands(
                module, info_key(cluster, name, user, user_key_path, output_format, container_image))  # noqa: E501
            key_exist = rc
            if not caps and key_exist != 0:
                fatal("Capabilities must be provided when state is 'present'", module)  # noqa: E501
            if key_exist != 0 and secret is None and caps is None:
                fatal("Keyring doesn't exist, you must provide 'secret' and 'caps'", module)  # noqa: E501
            if key_exist == 0:
                _info_key = json.loads(out)
                if not secret:
                    secret = _info_key[0]['key']
                _secret = _info_key[0]['key']
                if not caps:
                    caps = _info_key[0]['caps']
                _caps = _info_key[0]['caps']
                if secret == _secret and caps == _caps:
                    if not os.path.isfile(file_path):
                        rc, cmd, out, err = exec_commands(module, get_key(cluster, user, user_key_path, name, file_path, container_image))  # noqa: E501
                        result["rc"] = rc
                        if rc != 0:
                            result["stdout"] = "Couldn't fetch the key {0} at {1}.".format(name, file_path)  # noqa: E501
                            module.exit_json(**result)
                        result["stdout"] = "fetched the key {0} at {1}.".format(name, file_path)  # noqa: E501

                    result["stdout"] = "{0} already exists and doesn't need to be updated.".format(name)  # noqa: E501
                    result["rc"] = 0
                    module.set_fs_attributes_if_different(file_args, False)
                    module.exit_json(**result)
        else:
            if os.path.isfile(file_path) and not secret or not caps:
                result["stdout"] = "{0} already exists in {1} you must provide secret *and* caps when import_key is {2}".format(name, dest, import_key)  # noqa: E501
                result["rc"] = 0
                module.exit_json(**result)
        if (key_exist == 0 and (secret != _secret or caps != _caps)) or key_exist != 0:  # noqa: E501
            rc, cmd, out, err = exec_commands(module, create_key(
                module, cluster, user, user_key_path, name, secret, caps, import_key, file_path, container_image))  # noqa: E501
            if rc != 0:
                result["stdout"] = "Couldn't create or update {0}".format(name)
                result["stderr"] = err
                module.exit_json(**result)
            module.set_fs_attributes_if_different(file_args, False)
            changed = True

    elif state == "absent":
        rc, cmd, out, err = exec_commands(
            module, info_key(cluster, name, user, user_key_path, output_format, container_image))  # noqa: E501
        if rc == 0:
            rc, cmd, out, err = exec_commands(
                module, delete_key(cluster, user, user_key_path, name, container_image))  # noqa: E501
            changed = True
        else:
            rc = 0

    elif state == "fetch_initial_keys":
        hostname = socket.gethostname().split('.', 1)[0]
        user = "mon."
        keyring_filename = cluster + "-" + hostname + "/keyring"
        user_key_path = os.path.join("/var/lib/ceph/mon/", keyring_filename)
        rc, cmd, out, err = exec_commands(
            module, list_keys(cluster, user, user_key_path, container_image))
        if rc != 0:
            result["stdout"] = "failed to retrieve ceph keys"
            result["sdterr"] = err
            result['rc'] = 0
            module.exit_json(**result)

        entities = lookup_ceph_initial_entities(module, out)

        output_format = "plain"
        for entity in entities:
            key_path = build_key_path(cluster, entity)
            if key_path is None:
                fatal("Failed to build key path, no entity yet?", module)
            elif os.path.isfile(key_path):
                # if the key is already on the filesystem
                # there is no need to fetch it again
                continue

            extra_args = [
                '-o',
                key_path,
            ]

            info_cmd = info_key(cluster, entity, user,
                                user_key_path, output_format, container_image)
            # we use info_cmd[0] because info_cmd is an array made of an array
            info_cmd[0].extend(extra_args)
            rc, cmd, out, err = exec_commands(
                module, info_cmd)  # noqa: E501

            file_args = module.load_file_common_arguments(module.params)
            file_args['path'] = key_path
            module.set_fs_attributes_if_different(file_args, False)
    elif state == "generate_secret":
        out = generate_secret().decode()
        cmd = ''
        rc = 0
        err = ''
        changed = True

    endd = datetime.datetime.now()
    delta = endd - startd

    result = dict(
        cmd=cmd,
        start=str(startd),
        end=str(endd),
        delta=str(delta),
        rc=rc,
        stdout=out.rstrip("\r\n"),
        stderr=err.rstrip("\r\n"),
        changed=changed,
    )

    if rc != 0:
        module.fail_json(msg='non-zero return code', **result)

    module.exit_json(**result)


def main():
    run_module()


if __name__ == '__main__':
    main()
