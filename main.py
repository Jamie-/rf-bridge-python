# DEVELOPMENT TESTING #

import logging
from sensor_net import SensorNetwork, Node

logging.basicConfig(format='%(asctime)s[%(levelname)8s][%(module)s] %(message)s', datefmt='[%m/%d/%Y][%I:%M:%S %p]')
logger = logging.getLogger(__name__)

sn = SensorNetwork('/dev/ttyUSB0')
sn.discover(5)
print("Nodes connected: " + str(sn._slave_nodes))
if len(sn._slave_nodes) > 0:
    devices = sn.get_node_io(sn._slave_nodes[0])
    for device in devices.keys():
        print('Node 0 has - {}: {}'.format(device.name, str(devices[device])))
    if Node.Device.ANALOGUE_2BYTE in devices.keys():
        device_info = sn.get_device_info(sn._slave_nodes[0], Node.Device.ANALOGUE_2BYTE)
        print("Device reports it is: {}".format(device_info.decode('utf-8')))
        device_data = sn.get_data(sn._slave_nodes[0], Node.Device.ANALOGUE_2BYTE)
        print(int((device_data[0] << 8) + device_data[1]))  # Unpack data
sn.stop()
