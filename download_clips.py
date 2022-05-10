from scp_client import RemoteClient

remote_client = RemoteClient(
    hostname="lab04", 
    username="tai", 
    password=None, 
    ssh_key_filepath=None, 
    ssh_config_filepath="~/.ssh/config")
remote_client.connect()
remote_client.download(
    remote_path="/media/nas2/Tai/4-deepfake-data/output",
    local_path="./clips/",
    recursive=True,
    preserve_times=True
)