from flask import Flask, request
from netaddr import IPNetwork, IPAddress
import docker
import subprocess
import os
import uwsgidecorators

ip_whitelist_env = "IP_WHITELIST"
docker_compose_root_env = "DOCKER_COMPOSE_ROOT"
docker_compose_filename_env = "DOCKER_COMPOSE_FILENAME"
docker_compose_targets_env = "DOCKER_COMPOSE_TARGETS"

app = Flask(__name__)

client = docker.DockerClient(base_url='unix://var/run/docker.sock')

global ip_whitelist
global docker_compose_root
global docker_compose_filename
global docker_compose_targets


def parse_list(listenv):
    if (listenv is not None) and (len(listenv) > 0):
        targetlist = listenv.split(",")
        return [x.strip() for x in targetlist]
    else:
        return None


def build_env_lists():
    global ip_whitelist
    ip_whitelist = os.environ.get(ip_whitelist_env)
    ip_whitelist = parse_list(ip_whitelist)

    global docker_compose_targets
    docker_compose_targets = os.environ.get(docker_compose_targets_env)
    docker_compose_targets = parse_list(docker_compose_targets)

    global docker_compose_root
    docker_compose_root = os.environ.get(docker_compose_root_env)
    if docker_compose_root is None:
        docker_compose_root = "/opt/docker"

    global docker_compose_filename
    docker_compose_filename = os.environ.get(docker_compose_filename_env)
    if docker_compose_filename is None:
        docker_compose_filename = "docker-compose.yml"


def valid_ip():
    remoteclient = request.remote_addr

    if ip_whitelist is not None:
        for ip in ip_whitelist:
            if IPAddress(remoteclient) in IPNetwork(ip):
                return True
            else:
                return False
    else:
        return True


def docker_compose_cmd(cmd=None, name=None):
    if valid_ip() and (name is not None):
        if (docker_compose_targets is not None) and (name not in docker_compose_targets):
            return "The docker-compose definition %s was not found in %s" % (name, docker_compose_root), 404
        else:
            command = "docker-compose -f %s/%s/%s %s" % (docker_compose_root, name, docker_compose_filename, cmd)
            print(command.split())

            try:
                result = subprocess.run(command.split(), text=True, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT).stdout
            except subprocess.CalledProcessError as e:
                return "An error occurred while trying to launch %s. %s %s" % (
                    command, e.returncode, e.output), 500

            return '%s' % result
    else:
        return "The requested URL was not found or permitted on the server", 404


@app.route('/docker-compose/pull/<name>', methods=['POST'])
def docker_compose_pull(name=None):
    command = "pull"
    parameters = request.args.to_dict(flat=False)

    if "service" in parameters:
        for x in parameters["service"]:
            command = "%s %s" % (command, x)

    result = docker_compose_cmd(command, name)

    if "image is up to date" in result:
        return "up-to-date"
    elif "pull complete" in result:
        return "updated"
    else:
        return result


@app.route('/docker-compose/recreate/<name>', methods=['POST'])
def docker_compose_recreate(name=None):
    command = "up -d"

    parameters = request.args.to_dict(flat=False)

    if "force" in parameters:
        command = "%s --force" % command

    result = docker_compose_cmd(command, name)

    if "up-to-date" in result:
        return "up-to-date"
    elif "Recreating" in result:
        return "recreated"
    else:
        return result


@app.route('/docker/status/<name>', methods=['GET'])
def docker_status(name=None):
    container = client.containers.get(name)

    return container.status


@app.route('/docker/stop/<name>', methods=['POST'])
def docker_stop(name=None):
    container = client.containers.get(name)

    if container.status == "running":
        try:
            container.stop()
            container = client.containers.get(name)
        except docker.errors.APIError as e:
            return "%s %s" % (e.returncode, e.output), 500

    return container.status


@app.route('/docker/start/<name>', methods=['POST'])
def docker_start(name=None):
    container = client.containers.get(name)

    if container.status == "exited":
        try:
            container.start()
            container = client.containers.get(name)
        except docker.errors.APIError as e:
            return "%s %s" % (e.returncode, e.output), 500

    return container.status


@app.route('/docker/restart/<name>', methods=['POST'])
def docker_restart(name=None):
    container = client.containers.get(name)

    if container.status == "running":
        try:
            container.restart()
            container = client.containers.get(name)
        except docker.errors.APIError as e:
            return "%s %s" % (e.returncode, e.output), 500

    return container.status


@uwsgidecorators.postfork
def preload():
    build_env_lists()
    print("%s: %s" % (ip_whitelist_env, ip_whitelist))
    print("%s: %s" % (docker_compose_root_env, docker_compose_root))
    print("%s: %s" % (docker_compose_filename_env, docker_compose_filename))
    print("%s: %s" % (docker_compose_targets_env, docker_compose_targets))


if __name__ == '__main__':
    app.run(host='0.0.0.0')
