# DEVELOPMENT TESTING #

from sensor_net import SensorNetwork, Node

sn = SensorNetwork('/dev/ttyUSB0')
sn.discover(5)
print(sn._slave_nodes)
sn.stop()
