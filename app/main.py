from fastapi import FastAPI, Query, Request, Response
from netaddr import IPNetwork, IPAddress
from typing import List
import docker
import docker.errors
import os
import subprocess
import yaml

ip_whitelist_env = "IP_WHITELIST"
docker_compose_root_env = "DOCKER_COMPOSE_ROOT"
docker_compose_filename_env = "DOCKER_COMPOSE_FILENAME"
docker_compose_targets_env = "DOCKER_COMPOSE_TARGETS"

global ip_whitelist
global docker_compose_root
global docker_compose_filename
global docker_compose_targets


def parse_list(listenv):
    if (listenv is not None) and (len(listenv) > 0):
        targetlist = listenv.split(",")
        return [x.strip() for x in targetlist if x]
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

    print("%s: %s" % (ip_whitelist_env, ip_whitelist))
    print("%s: %s" % (docker_compose_root_env, docker_compose_root))
    print("%s: %s" % (docker_compose_filename_env, docker_compose_filename))
    print("%s: %s" % (docker_compose_targets_env, docker_compose_targets))


build_env_lists()
app = FastAPI()

client = docker.DockerClient(base_url='unix://var/run/docker.sock')


def valid_ip(remoteclient):
    if ip_whitelist is not None:
        for ip in ip_whitelist:
            if IPAddress(remoteclient) in IPNetwork(ip):
                return True
            else:
                return False
    else:
        return True


def docker_compose_cmd_execute(cmd=None, name=None):
    command = "docker-compose -f %s/%s/%s %s" % (docker_compose_root, name, docker_compose_filename, cmd)

    try:
        result = subprocess.run(command.split(), text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT).stdout
    except subprocess.CalledProcessError as e:
        return Response("An error occurred while trying to launch %s. %s %s" % (
            command, e.returncode, e.output), status_code=500)

    return result


def docker_compose_cmd(name=None, services=None, base_command=None, checks=None):
    if name is not None:
        if (docker_compose_targets is not None) and (name not in docker_compose_targets):
            return Response("The docker-compose definition %s was not found in %s" % (
                name, docker_compose_root), status_code=404)
        else:
            commands_dict = {}

            if services is not None:
                for service in services:
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

            for service, command in commands_dict.items():
                result = docker_compose_cmd_execute(command, name)

                final_response = None
                for term, response in checks.items():
                    if term in result:
                        final_response = response

                if final_response is None:
                    final_response = result

                results_dict[service] = final_response

            return results_dict
    else:
        return Response("The requested URL was not found on the server", status_code=404)


@app.post("/docker-compose/pull/{name}")
async def docker_compose_pull(name: str = None, service: List[str] = Query(None)):
    base_command = "pull"

    checks = {
        "image is up to date": "up-to-date",
        "pull complete": "updated"
    }

    return docker_compose_cmd(name, service, base_command, checks)


@app.post("/docker-compose/up/{name}")
async def docker_compose_up(name: str, detach: bool = False, force: bool = False, service: List[str] = Query(None)):
    base_command = "up"

    checks = {
        "up-to-date": "up-to-date",
        "Recreating": "recreated",
        "Creating": "created",
        "Starting": "started"
    }

    if detach:
        base_command = "%s --detach" % base_command

    if force:
        base_command = "%s --force" % base_command

    return docker_compose_cmd(name, service, base_command, checks)


@app.post("/docker-compose/restart/{name}")
async def docker_compose_restart(name: str = None, service: List[str] = Query(None)):
    base_command = "restart"

    checks = {
        "Restarting": "restarted"
    }

    return docker_compose_cmd(name, service, base_command, checks)


@app.get("/docker/status/{name}")
async def docker_status(name: str = None):
    container = client.containers.get(name)

    return container.status


@app.post("/docker/stop/{name}")
async def docker_stop(name: str = None):
    container = client.containers.get(name)

    if container.status == "running":
        try:
            container.stop()
            container = client.containers.get(name)
        except docker.errors.APIError as e:
            return Response("%s %s" % (e.status_code, e.response), status_code=500)

    return container.status


@app.post("/docker/start/{name}")
async def docker_start(name: str = None):
    container = client.containers.get(name)

    if container.status == "exited":
        try:
            container.start()
            container = client.containers.get(name)
        except docker.errors.APIError as e:
            return Response("%s %s" % (e.status_code, e.response), status_code=500)

    return container.status


@app.post("/docker/restart/{name}")
async def docker_restart(name: str = None):
    container = client.containers.get(name)

    if container.status == "running":
        try:
            container.restart()
            container = client.containers.get(name)
        except docker.errors.APIError as e:
            return Response("%s %s" % (e.status_code, e.response), status_code=500)

    return container.status


@app.middleware("http")
async def before_request_func(request: Request, call_next):
    if valid_ip(request.client.host):
        response = await call_next(request)
        return response
    else:
        response = Response("The client request has been refused through IP whitelist verification.", status_code=500)
        return response
