import time
import enum
import serial
import logging
import binascii
from xbee import ZigBee

logger = logging.getLogger(__name__)


class ProtocolError(Exception):
    pass


class Node:
    """Xbee Zigbee node"""

    class Type(enum.Enum):
        ANALOGUE_1BYTE = 0
        ANALOGUE_2BYTE = 1
        DIGITAL_INPUT = 2
        DIGITAL_OUTPUT = 3
        BYTE_INPUT = 4
        BYTE_OUTPUT = 5

    def __init__(self, long_addr, identifier):
        self.long_addr = long_addr
        self.identifier = identifier

    def __repr__(self):
        return 'Node({}:{})'.format(binascii.hexlify(self.long_addr).decode('utf-8'), self.identifier.decode('utf-8'))


class SensorNetwork:
    DATA_REQUEST = 16
    DATA_RESPONSE = 17
    IO_REQUEST = 18
    IO_RESPONSE = 19
    INFO_REQUEST = 20
    INFO_RESPONSE = 21
    SET_REQUEST = 22
    DATA_ALERT = 23
    CTRL_NACK = 254
    CTRL_ACK = 255

    def __init__(self, serial_device, baud=9600, escaped=True):
        self._ser = serial.Serial(serial_device, baud)
        self._xbee = ZigBee(self._ser, callback=self._handle_data, escaped=escaped)
        self._slave_nodes = []
        self._message_queue = []

    def discover(self, timeout=0):
        """Initiate a node discovery.

        Args:
            timeout (int): Seconds before function returns.
        """
        logger.debug('Starting node discovery...')
        self._xbee.at(command='ND')
        if timeout > 0:
            time.sleep(timeout)

    def _handle_data(self, data):
        if 'rf_data' in data.keys():
            if data['rf_data'][0] == self.IO_RESPONSE:
                self._message_queue.append(data)
                logger.debug('Received IO_RESPONSE, added to queue.')
            elif data['rf_data'][0] == self.INFO_RESPONSE:
                self._message_queue.append(data)
                logger.debug('Received INFO_RESPONSE, added to queue.')
            elif data['rf_data'][0] == self.CTRL_NACK:
                self._message_queue.append(data)
                logger.debug('Received NACK, added to queue.')
            else:
                print('Unknown data: {}'.format(data['rf_data']))
        elif 'id' in data.keys() and data['id'] == 'tx_status':
            if data['deliver_status'] != b'\x00':
                logger.error('Transmission was not delivered!')
                logger.error(data)
        elif 'command' in data.keys():
            command = data['command'].decode('utf-8')
            if command == 'ND':
                # Discovery command
                params = data['parameter']
                self._slave_nodes.append(Node(params['source_addr_long'], params['node_identifier']))
            else:
                logger.error('Unsupported command: {}'.format(command))
        else:
            logger.error('Received unknown packet:')
            logger.error(data)

    def stop(self):
        logger.info('Stopping...')
        self._xbee.halt()
        self._ser.close()

    def _wait_for_response(self, node, type_, fail_type, following=None):
        while True:
            for msg in self._message_queue:
                if 'source_addr_long' in msg.keys() and msg['source_addr_long'] == node.long_addr:
                    # Message is from target node
                    if len(msg['rf_data']) > 0 and msg['rf_data'][0] == type_:
                        if following is None:
                            self._message_queue.remove(msg)
                            return msg['rf_data'][1:]
                        elif len(msg) > 1 + len(following) and msg['rf_data'][1:len(following) + 1] == following:
                            self._message_queue.remove(msg)
                            return msg['rf_data'][1:]
                    # Check for NACK of same type
                    if len(msg['rf_data']) == 2 and msg['rf_data'][0] == self.CTRL_NACK and msg['rf_data'][1] == fail_type:
                        self._message_queue.remove(msg)
                        raise ProtocolError("Node returned NACK, did you ask for something which doesn't exist?")

    def get_node_io(self, node):
        if type(node) != Node:  # Check node is a Node
            raise TypeError('Invalid node.')
        self._xbee.tx(dest_addr_long=node.long_addr, data=bytes([self.IO_REQUEST]))
        logger.info('Waiting for IO_RESPONSE')
        out = {}
        for b in self._wait_for_response(node, self.IO_RESPONSE, self.IO_REQUEST):  # Loop over each byte as each respresents a device type
            out[Node.Type(b >> 4).name] = (b & 15) + 1  # +1 to 1-index number of devices
        return out

    def get_device_info(self, node, type_, index=0):
        if type(node) != Node:  # Check node is a valid Node
            raise TypeError('Invalid node.')
        if type(type_) != Node.Type:  # Check type_ is a valid Node.Type
            raise TypeError('Invalid IO type.')
        if type(index) != int:
            raise TypeError('Invalid index.')
        if index < 0 or index > 15:
            raise ValueError('Index out of bounds (0-15).')
        self._xbee.tx(dest_addr_long=node.long_addr, data=bytes([self.INFO_REQUEST, (type_.value << 4) + index]))
        logger.info('Waiting for INFO_RESPONSE')
        data = self._wait_for_response(node, self.INFO_RESPONSE, self.INFO_REQUEST, following=bytes([(type_.value << 4) + index]))
        return data[1:]
