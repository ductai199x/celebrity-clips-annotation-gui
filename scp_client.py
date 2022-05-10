"""Client to handle connections and actions executed against a remote host."""
import logging
import os
import select
from typing import *

from paramiko import AutoAddPolicy, ProxyCommand, RSAKey, SSHClient, SSHConfig
from paramiko.auth_handler import AuthenticationException, SSHException

from scp import SCPClient, SCPException

STDOUT_TIMEOUT = 5
CONNECTION_TIMEOUT = 5


class RemoteClient:
    """Client to interact with a remote host via SSH & SCP."""

    def __init__(
        self,
        hostname: str,
        username: str,
        hostport: Union[None, int] = None,
        password: Union[None, str] = None,
        ssh_key_filepath: Union[None, str] = None,
        ssh_config_filepath: Union[None, str] = None,
        logger: Union[None, logging.Logger] = None,
    ):
        self.hostname = hostname
        self.hostport = hostport
        self.username = username
        self.password = password
        self.ssh_key_filepath = ssh_key_filepath
        self.client = None
        if logger is None:
            self.logger = logging.Logger("RemoteClientLogger", level="INFO")
        else:
            self.logger = logger

        if self.password is None and self.ssh_key_filepath is None:
            self.ssh_key_filepath = os.path.expanduser("~/.ssh/id_rsa")

        if ssh_config_filepath is not None:
            self.ssh_config = SSHConfig()
            user_config_file = os.path.expanduser(ssh_config_filepath)
            with open(user_config_file, "r", encoding="utf-8") as f:
                self.ssh_config.parse(f)

        # self._upload_ssh_key()

    def connect(self):
        """Open SSH connection to remote host."""
        try:
            self.client = SSHClient()
            self.client.load_system_host_keys()
            self.client.set_missing_host_key_policy(AutoAddPolicy())

            cfg = {
                "hostname": self.hostname,
                "port": self.hostport,
                "username": self.username,
                "password": self.password,
                "key_filename": self.ssh_key_filepath,
                "timeout": CONNECTION_TIMEOUT,
            }
            host_conf = self.ssh_config.lookup(self.hostname)
            if host_conf:
                if "proxycommand" in host_conf:
                    cfg["sock"] = ProxyCommand(host_conf["proxycommand"])
                if "user" in host_conf:
                    cfg["username"] = host_conf["user"]
                if "identityfile" in host_conf:
                    cfg["key_filename"] = host_conf["identityfile"]
                if "hostname" in host_conf:
                    cfg["hostname"] = host_conf["hostname"]
                if "port" in host_conf:
                    cfg["port"] = int(host_conf["port"])
            self.client.connect(**cfg)
        except AuthenticationException as e:
            self.logger.error(
                f"AuthenticationException occurred; did you remember to generate an SSH key? {e}"
            )
            raise e
        except Exception as e:
            self.logger.error(f"Unexpected error occurred: {e}")
            raise e

    @property
    def scp(self) -> SCPClient:
        return SCPClient(self.client.get_transport())

    def _get_ssh_key(self):
        """Fetch locally stored SSH key."""
        try:
            self.ssh_key = RSAKey.from_private_key_file(self.ssh_key_filepath)
            self.logger.info(f"Found SSH key at self {self.ssh_key_filepath}")
            return self.ssh_key
        except SSHException as e:
            self.logger.error(e)
        except Exception as e:
            self.logger.error(f"Unexpected error occurred: {e}")
            raise e

    def _upload_ssh_key(self):
        try:
            os.system(
                f"ssh-copy-id -i {self.ssh_key_filepath}.pub {self.username}@{self.hostname}>/dev/null 2>&1"
            )
            self.logger.info(f"{self.ssh_key_filepath} uploaded to {self.hostname}")
        except FileNotFoundError as error:
            self.logger.error(error)
        except Exception as e:
            self.logger.error(f"Unexpected error occurred: {e}")
            raise e

    def disconnect(self):
        """Close SSH & SCP connection."""
        if self.connection:
            self.client.close()
        if self.scp:
            self.scp.close()

    def upload(
        self,
        files: Union[str, List[str]],
        remote_path: str,
        recursive=False,
        preserve_times=False,
    ):
        """Transfer files and directories to remote host.

        Args:
            files (Union[str, List[str]]): A single path, or a list of paths to be transferred.
            recursive must be True to transfer directories.
            remote_path (str): path in which to receive the files on the remote
            host.
            recursive (bool, optional): transfer files and directories recursively. Defaults to False.
            preserve_times (bool, optional): preserve mtime and atime of transferred files
            and directories. Defaults to False.

        Raises:
            e: SCPException
        """
        try:
            self.scp.put(files, remote_path, recursive, preserve_times)
            self.logger.info(
                f"Finished uploading {len(files)} files to {remote_path} on {self.hostname}"
            )
        except SCPException as e:
            raise e

    def download(
        self,
        remote_path: str,
        local_path: str = "",
        recursive=False,
        preserve_times=False,
    ):
        """Transfer files and directories from remote host to localhost.

        Args:
            remote_path (str): path to retrieve from remote host. since this is
            evaluated by scp on the remote host, shell wildcards and
            environment variables may be used.
            local_path (str, optional): path in which to receive files locally. Defaults to ''.
            recursive (bool, optional): transfer files and directories recursively. Defaults to False.
            preserve_times (bool, optional): preserve mtime and atime of transferred files
            and directories.. Defaults to False.

        Raises:
            e: SCPException
        """
        try:
            self.scp.get(remote_path, local_path, recursive, preserve_times)
            self.logger.info(
                f"Finished downloading {remote_path} to {local_path} on {self.hostname}"
            )
        except SCPException as e:
            raise e

    def safe_exec_cmd(self, command: str) -> Tuple[str, int]:
        """Safely read the output (both stdout and stderr) of a command on a remote host

        Args:
            command (str): command to be executed on the remote host

        Returns:
            Tuple[str, int]: stdout+stderr, and exit code
        """        
        stdin, stdout, stderr = self.client.exec_command(command)

        # get the shared channel for stdout/stderr/stdin
        channel = stdout.channel

        # we do not need stdin.
        stdin.close()
        # indicate that we're not going to write to that channel anymore
        channel.shutdown_write()

        # read stdout/stderr in order to prevent read block hangs
        stdout_chunks = []
        stdout_chunks.append(stdout.channel.recv(len(stdout.channel.in_buffer)))
        # chunked read to prevent stalls
        while not channel.closed or channel.recv_ready() or channel.recv_stderr_ready():
            # stop if channel was closed prematurely, and there is no data in the buffers.
            got_chunk = False
            readq, _, _ = select.select([stdout.channel], [], [], STDOUT_TIMEOUT)
            for c in readq:
                if c.recv_ready():
                    stdout_chunks.append(stdout.channel.recv(len(c.in_buffer)))
                    got_chunk = True
                if c.recv_stderr_ready():
                    # make sure to read stderr to prevent stall
                    stderr.channel.recv_stderr(len(c.in_stderr_buffer))
                    got_chunk = True
            """
            1) make sure that there are at least 2 cycles with no data in the input buffers 
               in order to not exit too early (i.e. cat on a >200k file).
            2) if no data arrived in the last loop, check if we already received the exit code
            3) check if input buffers are empty
            4) exit the loop
            """
            if (
                not got_chunk
                and stdout.channel.exit_status_ready()
                and not stderr.channel.recv_stderr_ready()
                and not stdout.channel.recv_ready()
            ):
                # indicate that we're not going to read from this channel anymore
                stdout.channel.shutdown_read()
                # close the channel
                stdout.channel.close()
                break  # exit as remote side is finished and our bufferes are empty

        # close all the pseudofiles
        stdout.close()
        stderr.close()

        exit_code = stdout.channel.recv_exit_status()

        del stdin, stdout, stderr

        stdout = "".join([chunk.decode("utf8") for chunk in stdout_chunks])

        return stdout, exit_code

    def execute_commands(self, commands: List[str]):
        """Execute multiple commands and print their output in succession.

        Args:
            commands (List[str]): List of commands as strings.
        """
        for cmd in commands:
            stdout, exit_code = self.safe_exec_cmd(cmd)
            print(stdout)
