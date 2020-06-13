from flask import Flask, request, jsonify
from flask_executor import Executor
from netaddr import IPNetwork, IPAddress
import docker
import os
import subprocess
import uwsgidecorators
import yaml

ip_whitelist_env = "IP_WHITELIST"
docker_compose_root_env = "DOCKER_COMPOSE_ROOT"
docker_compose_filename_env = "DOCKER_COMPOSE_FILENAME"
docker_compose_targets_env = "DOCKER_COMPOSE_TARGETS"

app = Flask(__name__)
executor = Executor(app)

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


def docker_compose_cmd_execute(cmd=None, name=None):
    if valid_ip() and (name is not None):
        if (docker_compose_targets is not None) and (name not in docker_compose_targets):
            return "The docker-compose definition %s was not found in %s" % (name, docker_compose_root), 404
        else:
            command = "docker-compose -f %s/%s/%s %s" % (docker_compose_root, name, docker_compose_filename, cmd)

            try:
                result = subprocess.run(command.split(), text=True, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT).stdout
            except subprocess.CalledProcessError as e:
                return "An error occurred while trying to launch %s. %s %s" % (
                    command, e.returncode, e.output), 500

            return '%s' % result
    else:
        return "The requested URL was not found or permitted on the server", 404


def docker_compose_cmd(name=None, parameters=None, base_command=None, checks=None):
    commands_dict = {}

    if "service" in parameters:
        for service in parameters["service"]:
            command = "%s %s" % (base_command, service)
            commands_dict[service] = command
    else:
        with open(r'%s/%s/%s' % (docker_compose_root, name, docker_compose_filename)) as file:
            compose_dict = yaml.load(file, Loader=yaml.FullLoader)

            if "services" in compose_dict:
                if len(compose_dict["services"].keys()) > 0:
                    for service_key in compose_dict["services"].keys():
                        command = "%s %s" % (base_command, service_key)
                        commands_dict[service_key] = command

    results_dict = {}

    for service,command in commands_dict.items():
        result = executor.submit(docker_compose_cmd_execute, command, name).result()

        final_response = None
        for term,response in checks.items():
            if term in result:
                final_response = response

        if final_response is None:
            final_response = result

        results_dict[service] = final_response

    return jsonify(results_dict)


@app.route('/docker-compose/pull/<name>', methods=['POST'])
def docker_compose_pull(name=None):
    base_command = "pull"
    parameters = request.args.to_dict(flat=False)
    checks = {
        "image is up to date": "up-to-date",
        "pull complete": "updated"
    }
    return docker_compose_cmd(name, parameters, base_command, checks)


@app.route('/docker-compose/recreate/<name>', methods=['POST'])
def docker_compose_recreate(name=None):
    base_command = "up -d"
    parameters = request.args.to_dict(flat=False)
    checks = {
        "up-to-date": "up-to-date",
        "Recreating": "recreated",
        "Creating": "created",
        "Starting": "started"
    }

    if "force" in parameters:
        base_command = "%s --force" % base_command

    return docker_compose_cmd(name, parameters, base_command, checks)


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
            return "%s %s" % (e.status_code, e.response), 500

    return container.status


@app.route('/docker/start/<name>', methods=['POST'])
def docker_start(name=None):
    container = client.containers.get(name)

    if container.status == "exited":
        try:
            container.start()
            container = client.containers.get(name)
        except docker.errors.APIError as e:
            return "%s %s" % (e.status_code, e.response), 500

    return container.status


@app.route('/docker/restart/<name>', methods=['POST'])
def docker_restart(name=None):
    container = client.containers.get(name)

    if container.status == "running":
        try:
            container.restart()
            container = client.containers.get(name)
        except docker.errors.APIError as e:
            return "%s %s" % (e.status_code, e.response), 500

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
