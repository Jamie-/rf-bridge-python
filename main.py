# DEVELOPMENT TESTING #

import logging
from sensor_net import SensorNetwork, Node

logging.basicConfig(format='%(asctime)s[%(levelname)8s][%(module)s] %(message)s', datefmt='[%m/%d/%Y][%I:%M:%S %p]')
logger = logging.getLogger(__name__)

sn = SensorNetwork('/dev/ttyUSB0')
sn.discover(5)
print(sn._slave_nodes)
sn.stop()
