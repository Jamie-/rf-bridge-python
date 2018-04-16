# DEVELOPMENT TESTING #

import logging
from sensor_net import SensorNetwork, Node

logging.basicConfig(format='%(asctime)s[%(levelname)8s][%(module)s] %(message)s', datefmt='[%m/%d/%Y][%I:%M:%S %p]')
logger = logging.getLogger(__name__)

sn = SensorNetwork('/dev/ttyUSB0')
sn.discover(5)
print("Nodes connected: " + str(sn._slave_nodes))
idx = 0
for node in sn._slave_nodes:
    payloads = sn.get_node_io(node)
    for payload in payloads.keys():
        print('Node {} has - {}: {}'.format(idx, payload.name, str(payloads[payload])))
        payload_info = sn.get_payload_info(node, payload)
        print("Payload reports it is: {}".format(payload_info.decode('utf-8')))
        payload_data = sn.get_data(node, payload)
        print('Data: {} ({})'.format(str(payload_data), type(payload_data).__name__))
    idx += 1
sn.stop()
