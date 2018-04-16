import time
import enum
import serial
import logging
import binascii
from xbee import ZigBee

logger = logging.getLogger(__name__)


class ProtocolError(Exception):
    """Sensor Network protocol exception. Usually raised on NACK."""
    pass


class Packet(enum.Enum):
    """Data packet type."""
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


class Node:
    """Xbee Zigbee node."""

    class Payload(enum.Enum):
        """Payload data type."""
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

    def __init__(self, serial_device, baud=9600, escaped=True):  # Use escaped for XBees in API mode 2
        self._ser = serial.Serial(serial_device, baud)
        self._xbee = ZigBee(self._ser, callback=self._handle_data, escaped=escaped)
        self._slave_nodes = []  # Slave nodes found using self.discover()
        self._message_queue = []  # Queued data messages incoming

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
        """Internal function to handle data responses from XBee API."""
        if 'rf_data' in data.keys():
            if data['rf_data'][0] == Packet.IO_RESPONSE.value:
                self._message_queue.append(data)
                logger.debug('Received IO_RESPONSE, added to queue.')
            elif data['rf_data'][0] == Packet.INFO_RESPONSE.value:
                self._message_queue.append(data)
                logger.debug('Received INFO_RESPONSE, added to queue.')
            elif data['rf_data'][0] == Packet.DATA_RESPONSE.value:
                self._message_queue.append(data)
                logger.debug('Received DATA_RESPONSE, added to queue.')
            elif data['rf_data'][0] == Packet.CTRL_NACK.value:
                self._message_queue.append(data)
                logger.debug('Received NACK, added to queue.')
            else:
                print('Unknown data: {}'.format(data['rf_data']))
        elif 'id' in data.keys() and data['id'] == 'tx_status':  # Every transmission returns a tx_status packet
            if data['deliver_status'] != b'\x00':
                logger.error('Transmission was not delivered!')
                logger.error(data)
        elif 'command' in data.keys():
            command = data['command'].decode('utf-8')
            if command == 'ND':  # XBee node discovery AT command
                params = data['parameter']
                self._slave_nodes.append(Node(params['source_addr_long'], params['node_identifier']))
            else:
                logger.error('Unsupported command: {}'.format(command))
        else:
            logger.error('Received unknown packet:')
            logger.error(data)

    def stop(self):
        """Stop radio listener & handler."""
        logger.info('Stopping...')
        self._xbee.halt()
        self._ser.close()

    def _wait_for_response(self, node, type_, fail_type, following=None, count=None):
        """Internal function to wait until data arrives meeting specific constraints.

        Args:
            node (Node): Node to wait for data from (using long_addr).
            type_ (Packet): Packet type required
            fail_type (Packet): Packet type transimitted before wait called.
            following (bytes): Byte sequence required following type_ byte.
            count (int): Total number of bytes in packet required (including type byte).

        Returns:
            bytes: Data bytes after type byte.
        """
        while True:
            for msg in self._message_queue:
                if 'source_addr_long' in msg.keys() and msg['source_addr_long'] == node.long_addr:
                    # Message is from target node
                    if len(msg['rf_data']) > 0 and msg['rf_data'][0] == type_.value:
                        if following is None and count is None:
                            self._message_queue.remove(msg)
                            return msg['rf_data'][1:]
                        # Just following
                        elif count is None and len(msg['rf_data']) > 1 + len(following) and msg['rf_data'][1:len(following) + 1] == following:
                            self._message_queue.remove(msg)
                            return msg['rf_data'][1:]
                        # Just count
                        elif following is None and len(msg['rf_data']) == count:
                            self._message_queue.remove(msg)
                            return msg['rf_data'][1:]
                        # Following AND count
                        elif len(msg['rf_data']) == count and len(msg['rf_data']) > 1 + len(following) and msg['rf_data'][1:len(following) + 1] == following:
                            self._message_queue.remove(msg)
                            return msg['rf_data'][1:]
                    # Check for NACK of same type
                    if len(msg['rf_data']) == 2 and msg['rf_data'][0] == Packet.CTRL_NACK.value and msg['rf_data'][1] == fail_type.value:
                        self._message_queue.remove(msg)
                        raise ProtocolError("Node returned NACK, did you ask for something which doesn't exist?")

    def get_node_io(self, node):
        """Get IO presented by node.

        Args:
            node (Node): Node to inspect.

        Returns:
            dict of Packet to int: Packet IO type mapped to quantity.
        """
        if type(node) != Node:  # Check node is a Node
            raise TypeError('Invalid node.')
        self._xbee.tx(dest_addr_long=node.long_addr, data=bytes([Packet.IO_REQUEST.value]))
        logger.info('Waiting for IO_RESPONSE')
        out = {}
        # Loop over each byte as each represents a device
        for b in self._wait_for_response(node, Packet.IO_RESPONSE, Packet.IO_REQUEST):
            out[Node.Payload(b >> 4)] = (b & 15) + 1  # +1 to 1-index number of devices
        return out

    def get_payload_info(self, node, payload, index=0):
        """Get information about payload presented by node.

        Args:
            node (Node): Node to inspect.
            payload (Node.Payload): Payload type to inspect.
            index (int): Address of payload if node presents multiple.

        Returns:
            bytes: Raw bytes sent from node upon querying for information about payload
        """
        if type(node) != Node:  # Check node is a valid Node
            raise TypeError('Invalid node.')
        if type(payload) != Node.Payload:  # Check payload is a valid Node.Payload
            raise TypeError('Invalid IO payload.')
        if type(index) != int:
            raise TypeError('Invalid index.')
        if index < 0 or index > 15:
            raise ValueError('Index out of bounds (0-15).')
        self._xbee.tx(dest_addr_long=node.long_addr, data=bytes([Packet.INFO_REQUEST.value, (payload.value << 4) + index]))
        logger.info('Waiting for INFO_RESPONSE')
        data = self._wait_for_response(node, Packet.INFO_RESPONSE, Packet.INFO_REQUEST, following=bytes([(payload.value << 4) + index]))
        return data[1:]

    def get_data(self, node, payload, index=0):
        if type(node) != Node:  # Check node is a valid Node
            raise TypeError('Invalid node.')
        if type(payload) != Node.Payload:  # Check payload is a valid Node.Payload
            raise TypeError('Invalid IO payload.')
        if type(index) != int:
            raise TypeError('Invalid index.')
        if payload in (Node.Payload.DIGITAL_INPUT, Node.Payload.BYTE_INPUT):
            raise ValueError('Cannot get data out of a sink node.')
        if index < 0 or index > 15:
            raise ValueError('Index out of bounds (0-15).')
        self._xbee.tx(dest_addr_long=node.long_addr, data=bytes([Packet.DATA_REQUEST.value, (payload.value << 4) + index]))
        logger.info('Waiting for DATA_RESPONSE')
        if payload == Node.Payload.DIGITAL_OUTPUT:  # Return tuple of True/False values representing data
            data = self._wait_for_response(node, Packet.DATA_RESPONSE, Packet.DATA_REQUEST, following=bytes([(payload.value << 4) + index]), count=3)[1:]
            return [(int(data[0]) & 1 << i) >> i == 1 for i in reversed(range(0, 8))]
        elif payload == Node.Payload.ANALOGUE_1BYTE:
            data = self._wait_for_response(node, Packet.DATA_RESPONSE, Packet.DATA_REQUEST, following=bytes([(payload.value << 4) + index]), count=3)[1:]
            return int(data)
        elif payload == Node.Payload.ANALOGUE_2BYTE:  # Return number represented by byte data
            data = self._wait_for_response(node, Packet.DATA_RESPONSE, Packet.DATA_REQUEST, following=bytes([(payload.value << 4) + index]), count=4)[1:]
            return int((data[0] << 8) + data[1])
        elif payload == Node.Payload.BYTE_OUTPUT:  # Return raw bytes
            return self._wait_for_response(node, Packet.DATA_RESPONSE, Packet.DATA_REQUEST, following=bytes([(payload.value << 4) + index]))[1:]
