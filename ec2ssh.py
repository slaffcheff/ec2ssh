#!/usr/bin/env python3

"""
ec2ssh: SSH *securely* to an EC2 instance without known_hosts hassles

Features

    - Custom known_hosts files (per-instance-address) are stored in ~/.ec2ssh/.
    - Reassigning elastic IPs is fine!
    - Caching of pubkeys is done basically for free
    - Exit status is propagated from SSH (e.g. 255 on network failure)

Requirements

    - A Linux EC2 instance running cloud-init (the default for ubuntu)
    - Instance must have a "Name" tag

Usage

    ec2ssh <instance_name> [args to pass to ssh]

Example

    ec2ssh mydev                                   # Interactive login
    ec2ssh mydev -l ubuntu                         # Specify the user
    ec2ssh mydev echo "Hello Secure Cloud World"   # Run command

Bugs

    - Should atomically write/rename the known_hosts files
    - Should support sftp too
    - AWS doc on how long console output is retained is clear as mud!
    - AWS should have a standard pubkey API and not use this hack!

(C) 2017 Karl Pickett
"""

import subprocess
import sys
import re
import os.path

import boto3


SSH_KEY_TMPDIR = os.path.expanduser("~/.ec2ssh")


def get_instance_by_tag_name(client, name):
    tagfilter = dict(Name='tag:Name', Values=[name])
    response = client.describe_instances(Filters=[tagfilter])
    ret = []
    for reservation in response["Reservations"]:
        instances = reservation["Instances"]
        ret += instances
    if not ret:
        raise Exception("No instances found", name)
    if len(ret) > 1:
        raise Exception("Multiple instances found", name)
    return ret[0]


def get_ssh_host_keys_from_console_output(client, instance_id):
    response = client.get_console_output(InstanceId=instance_id)
    regex = ("-----BEGIN SSH HOST KEY KEYS-----(.*)"
            "-----END SSH HOST KEY KEYS-----")
    output = response["Output"]
    mo = re.search(regex, output, re.DOTALL)
    if mo:
        keys = mo.group(1).strip().split("\n")
        return keys
    else:
        raise Exception("No SSH HOST KEY KEYS found", instance_id)


def get_known_hosts_name(instance_id, ssh_hostname):
    file_name = "pubkey-%s-%s" % (instance_id, ssh_hostname)
    return os.path.join(SSH_KEY_TMPDIR, file_name)


def write_known_hosts_file(file_name, keys, ssh_hostname):
    data = ""
    for key in keys:
        data += (ssh_hostname + " " + key + "\n")
    # Warning this is not atomic - not concurrent safe
    open(file_name, "w").write(data)


def trace(message):
    sys.stderr.write(message.strip() + "\n")
    sys.stderr.flush()


def main():
    args = sys.argv[1:]
    instance_name = args[0]
    ssh_forwarded_args = args[1:]

    os.makedirs(SSH_KEY_TMPDIR, exist_ok=True)

    client = boto3.client('ec2')
    instance = get_instance_by_tag_name(client, instance_name)

    # Could use private IP, e.g. if you are in VPN/VPC
    ssh_hostname = instance["PublicIpAddress"]
    instance_id = instance["InstanceId"]

    file_name = get_known_hosts_name(instance_id, ssh_hostname)
    if not os.path.exists(file_name):
        keys = get_ssh_host_keys_from_console_output(client, instance_id)
        write_known_hosts_file(file_name, keys, ssh_hostname)
        trace("Created new file: {}".format(file_name))
    else:
        trace("Using cached file: {}".format(file_name))

    args = ["ssh", "-o", "UserKnownHostsFile " + file_name]
    args += [ssh_hostname]
    args += ssh_forwarded_args
    trace("Running: {}".format(args))

    # We probably could just exec this
    p = subprocess.Popen(args)
    rc = p.wait()
    trace("Exit status: {}".format(rc))
    sys.exit(rc)


if __name__ == "__main__":
    main()
