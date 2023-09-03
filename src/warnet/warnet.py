"""
  Warnet is the top-level class for a simulated network.
"""

import docker
import logging
import networkx
import shutil
import subprocess
import yaml
from pathlib import Path
from templates import TEMPLATES
from typing import List

from services.prometheus import Prometheus
from services.node_exporter import NodeExporter
from services.grafana import Grafana
from services.tor import Tor
from services.fork_observer import ForkObserver
from services.dns_seed import DnsSeed
from warnet.tank import Tank
from warnet.utils import parse_bitcoin_conf, gen_config_dir

logger = logging.getLogger("Warnet")
FO_CONF_NAME = "fork_observer_config.toml"
ZONE_FILE_NAME = "dns-seed.zone"
logging.getLogger("docker.utils.config").setLevel(logging.WARNING)
logging.getLogger("docker.auth").setLevel(logging.WARNING)


class Warnet:
    def __init__(self, config_dir):
        self.config_dir: Path = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.docker = docker.from_env()
        self.bitcoin_network: str = "regtest"
        self.docker_network: str = "warnet"
        self.subnet: str = "100.0.0.0/8"
        self.graph = None
        self.graph_name = "graph.graphml"
        self.tanks: List[Tank] = []
        self.fork_observer_config = self.config_dir / FO_CONF_NAME
        logger.info(
            f"copying config {TEMPLATES / FO_CONF_NAME} to {self.fork_observer_config}"
        )
        shutil.copy(TEMPLATES / FO_CONF_NAME, self.fork_observer_config)

    def __str__(self) -> str:
        tanks_str = ",\n".join([str(tank) for tank in self.tanks])
        return (
            f"Warnet(\n"
            f"\tTemp Directory: {self.config_dir}\n"
            f"\tBitcoin Network: {self.bitcoin_network}\n"
            f"\tDocker Network: {self.docker_network}\n"
            f"\tSubnet: {self.subnet}\n"
            f"\tGraph: {self.graph}\n"
            f"\tTanks: [\n{tanks_str}\n"
            f"\t]\n"
            f")"
        )

    @classmethod
    def from_graph_file(
        cls, graph_file: str, config_dir: Path, network: str = "warnet"
    ):
        self = cls(config_dir)
        destination = self.config_dir / self.graph_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(graph_file, destination)
        self.docker_network = network
        self.graph = networkx.read_graphml(graph_file, node_type=int)
        self.tanks_from_graph()
        logger.info(f"Created Warnet using directory {self.config_dir}")
        return self

    @classmethod
    def from_graph(cls, graph):
        self = cls(Path())
        self.graph = graph
        self.tanks_from_graph()
        logger.info(f"Created Warnet using directory {self.config_dir}")
        return self

    @classmethod
    def from_network(
        cls, config_dir: Path = Path(), network: str = "warnet", tanks=True
    ):
        self = cls(config_dir)
        self.config_dir = gen_config_dir(network)
        self.graph = networkx.read_graphml(
            Path(self.config_dir / self.graph_name), node_type=int
        )
        if tanks:
            self.tanks_from_graph()
        return self

    @classmethod
    def from_docker_env(cls, network_name):
        config_dir = gen_config_dir(network_name)
        self = cls(config_dir)
        self.graph = networkx.read_graphml(
            Path(self.config_dir / self.graph_name), node_type=int
        )
        self.docker_network = network_name
        index = 0
        while index <= 999999:
            try:
                self.tanks.append(Tank.from_docker_env(self.docker_network, index))
                index = index + 1
            except:
                assert index == len(self.tanks)
                break
        return self

    @property
    def zone_file_path(self):
        return self.config_dir / ZONE_FILE_NAME

    def tanks_from_graph(self):
        for node_id in self.graph.nodes():
            if int(node_id) != len(self.tanks):
                raise Exception(
                    f"Node ID in graph must be incrementing integers (got '{node_id}', expected '{len(self.tanks)}')"
                )
            self.tanks.append(Tank.from_graph_node(node_id, self))
        logger.info(f"Imported {len(self.tanks)} tanks from graph")

    def write_bitcoin_confs(self):
        with open(TEMPLATES / "bitcoin.conf", "r") as file:
            text = file.read()
        base_bitcoin_conf = parse_bitcoin_conf(text)
        for tank in self.tanks:
            tank.write_bitcoin_conf(base_bitcoin_conf)

    def apply_network_conditions(self):
        for tank in self.tanks:
            tank.apply_network_conditions()

    def generate_zone_file_from_tanks(self):
        records_list = [
            f"seed.dns-seed.     300 IN  A   {tank.ipv4}" for tank in self.tanks
        ]
        content = []
        with open(str(TEMPLATES / ZONE_FILE_NAME), "r") as f:
            content = [line.rstrip() for line in f]

        # TODO: Really we should also read active SOA value from dns-seed, and increment from there

        content.extend(records_list)
        # Join the content into a single string and escape single quotes for echoing
        content_str = "\n".join(content).replace("'", "'\\''")
        with open(self.config_dir / ZONE_FILE_NAME, "w") as f:
            f.write(content_str)

    def apply_zone_file(self):
        """
        Sync the dns seed list served by dns-seed with currently active Tanks.
        """
        seeder = self.docker.containers.get("dns-seed")

        # Read the content from the generated zone file
        with open(self.config_dir / ZONE_FILE_NAME, "r") as f:
            content_str = f.read().replace("'", "'\\''")

        # Overwrite all existing content
        result = seeder.exec_run(
            f"sh -c 'echo \"{content_str}\" > /etc/bind/dns-seed.zone'"
        )
        logging.debug(f"result of updating {ZONE_FILE_NAME}: {result}")

        # Reload that single zone only
        seeder.exec_run("rndc reload dns-seed")

    def connect_edges(self):
        for edge in self.graph.edges():
            (src, dst) = edge
            src_tank = self.tanks[int(src)]
            dst_ip = self.tanks[dst].ipv4
            logger.info(f"Using `addpeeraddress` to connect tanks {src} to {dst}")
            cmd = f"bitcoin-cli addpeeraddress {dst_ip} 18444"
            src_tank.exec(cmd=cmd, user="bitcoin")

    def docker_compose_build_up(self):
        command = ["docker-compose", "-p", self.docker_network, "up", "-d", "--build"]
        try:
            with subprocess.Popen(
                command,
                cwd=str(self.config_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            ) as process:
                for line in process.stdout:
                    logger.info(line.decode().rstrip())
        except Exception as e:
            logger.error(
                f"An error occurred while executing `{' '.join(command)}` in {self.config_dir}: {e}"
            )

    def docker_compose_up(self):
        command = ["docker-compose", "-p", self.docker_network, "up", "-d"]
        try:
            with subprocess.Popen(
                command,
                cwd=str(self.config_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            ) as process:
                for line in process.stdout:
                    logger.info(line.decode().rstrip())
        except Exception as e:
            logger.error(
                f"An error occurred while executing `{' '.join(command)}` in {self.config_dir}: {e}"
            )

    def docker_compose_down(self):
        command = ["docker-compose", "down"]
        try:
            with subprocess.Popen(
                command,
                cwd=str(self.config_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            ) as process:
                for line in process.stdout:
                    logger.info(line.decode().rstrip())
        except Exception as e:
            logger.error(
                f"An error occurred while executing `{' '.join(command)}` in {self.config_dir}: {e}"
            )

    def write_docker_compose(self, dns=True):
        compose = {
            "version": "3.8",
            "networks": {
                self.docker_network: {
                    "name": self.docker_network,
                    "ipam": {"config": [{"subnet": self.subnet}]},
                }
            },
            "volumes": {"grafana-storage": None},
            "services": {},
        }

        # Pass services object to each tank so they can add whatever they need.
        for tank in self.tanks:
            tank.add_services(compose["services"])

        # Initialize services and add them to the compose
        services = [
            Prometheus(self.docker_network, self.config_dir),
            NodeExporter(self.docker_network),
            Grafana(self.docker_network),
            Tor(self.docker_network, TEMPLATES),
            ForkObserver(self.docker_network, self.fork_observer_config),
        ]
        if dns:
            services.append(DnsSeed(self.docker_network, TEMPLATES, self.config_dir))

        for service_obj in services:
            service_name = service_obj.__class__.__name__.lower()
            compose["services"][service_name] = service_obj.get_service()

        docker_compose_path = self.config_dir / "docker-compose.yml"
        try:
            with open(docker_compose_path, "w") as file:
                yaml.dump(compose, file)
            logger.info(f"Wrote file: {docker_compose_path}")
        except Exception as e:
            logger.error(
                f"An error occurred while writing to {docker_compose_path}: {e}"
            )

    def write_prometheus_config(self):
        config = {
            "global": {"scrape_interval": "15s"},
            "scrape_configs": [
                {
                    "job_name": "prometheus",
                    "scrape_interval": "5s",
                    "static_configs": [{"targets": ["localhost:9090"]}],
                },
                {
                    "job_name": "node-exporter",
                    "scrape_interval": "5s",
                    "static_configs": [{"targets": ["node-exporter:9100"]}],
                },
                {
                    "job_name": "cadvisor",
                    "scrape_interval": "5s",
                    "static_configs": [{"targets": ["cadvisor:8080"]}],
                },
            ],
        }

        for tank in self.tanks:
            tank.add_scrapers(config["scrape_configs"])

        prometheus_path = self.config_dir / "prometheus.yml"
        try:
            with open(prometheus_path, "w") as file:
                yaml.dump(config, file)
            logger.info(f"Wrote file: {prometheus_path}")
        except Exception as e:
            logger.error(f"An error occurred while writing to {prometheus_path}: {e}")
