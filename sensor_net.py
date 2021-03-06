import time
import enum
import serial
import logging
import binascii
import struct
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
        INT_1B_OUTPUT = 0
        INT_2B_OUTPUT = 1
        INT_1B_INPUT = 2
        INT_2B_INPUT = 3
        DIGITAL_INPUT = 4
        DIGITAL_OUTPUT = 5
        BYTE_INPUT = 6
        BYTE_OUTPUT = 7

    def __init__(self, long_addr, identifier):
        addr = struct.unpack("II", long_addr)
        self.addr = hash(addr[0] ^ addr[1])
        self.long_addr = long_addr
        self.identifier = identifier.decode()

    def __repr__(self):
        return 'Node({}:{})'.format(binascii.hexlify(self.long_addr).decode('utf-8'), self.identifier)

    def __eq__(self, other):
        if not isinstance(other, Node):
            return False
        return self.long_addr == other.long_addr and self.identifier == other.identifier

    def __hash__(self):
        return self.addr


class SensorNetwork:

    def __init__(self, serial_device, baud=9600, escaped=True):  # Use escaped for XBees in API mode 2
        self._ser = serial.Serial(serial_device, baud)
        self._xbee = ZigBee(self._ser, callback=self._handle_data, escaped=escaped)
        self._slave_nodes = {}  # Slave nodes found using self.discover()
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

    def get_node_ids(self):
        """Get IDs of all slave nodes.

        Returns:
            list of addr: List of slave node IDs.
        """
        return self._slave_nodes.keys()

    def get_nodes(self):
        """Get all slave nodes.

        Returns:
            list of Node: List of slave nodes.
        """
        return self._slave_nodes.values()

    def get_node_by_id(self, id):
        """Get a node by it's ID.

        Args:
            id: Node ID.

        Returns:
            Node: Node represented by ID.
        """
        return self._slave_nodes.get(id)

    def node_exists(self, id):
        """Test if a node exists in the slave nodes.

        Args:
            id: Node ID.

        Returns:
            bool: True if node ID exists in slave nodes, else False.
        """
        return id in self._slave_nodes

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
            elif data['rf_data'][0] == Packet.CTRL_ACK.value:
                self._message_queue.append(data)
                logger.debug('Received ACK, added to queue.')
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
                node = Node(params['source_addr_long'], params['node_identifier'])
                logging.debug("Found node at {}".format(node.addr))
                self._slave_nodes[node.addr] = node
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

    def _wait_for_response(self, node, type_, fail_type, following=None, count=None, timeout=None):
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
        if timeout is None:
            timeout = 0
        timer = time.time() + timeout
        while True:
            for msg in self._message_queue:
                if 'source_addr_long' in msg.keys() and msg['source_addr_long'] == node.long_addr:
                    # Message is from target node
                    if len(msg['rf_data']) > 0 and msg['rf_data'][0] == type_.value:
                        if following is None and count is None:
                            self._message_queue.remove(msg)
                            return msg['rf_data'][1:]
                        # Just following
                        elif count is None and len(msg['rf_data']) > len(following) and msg['rf_data'][1:len(following) + 1] == following:
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
            if timeout > 0 and time.time() > timer:
                raise ProtocolError('Did not recieve any data from node.')

    def get_node_io(self, node, timeout=None):
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
        for b in self._wait_for_response(node, Packet.IO_RESPONSE, Packet.IO_REQUEST, timeout=timeout):
            out[Node.Payload(b >> 4)] = (b & 15) + 1  # +1 to 1-index number of devices
        return out

    def get_payload_info(self, node, payload, index=0, timeout=None):
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
        data = self._wait_for_response(node, Packet.INFO_RESPONSE, Packet.INFO_REQUEST, following=bytes([(payload.value << 4) + index]), timeout=timeout)
        return data[1:]

    def get_data(self, node, payload, index=0, timeout=None):
        """Get data from node supporting data sourcing.

        Args:
            node (Node): Node to retrieve data from.
            payload (Node.Payload): Payload type to retrieve data for.
            index (int): Address of payload if node presents multiple.

        Returns:
            bytes or int or list of bool:
                If requesting an analog value, returns int of value.
                If requesting a digital output, returns list of bool containing 8 values.
                Otherwise, bytes of raw data.
        """
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
            data = self._wait_for_response(node, Packet.DATA_RESPONSE, Packet.DATA_REQUEST, following=bytes([(payload.value << 4) + index]), count=3, timeout=timeout)[1:]
            return [(int(data[0]) & 1 << i) >> i == 1 for i in reversed(range(0, 8))]
        elif payload == Node.Payload.INT_1B_OUTPUT:  # Return number represented by byte data
            data = self._wait_for_response(node, Packet.DATA_RESPONSE, Packet.DATA_REQUEST, following=bytes([(payload.value << 4) + index]), count=3, timeout=timeout)[1:]
            return int(data[0])
        elif payload == Node.Payload.INT_2B_OUTPUT:  # Return number represented by byte data
            data = self._wait_for_response(node, Packet.DATA_RESPONSE, Packet.DATA_REQUEST, following=bytes([(payload.value << 4) + index]), count=4, timeout=timeout)[1:]
            return int((data[0] << 8) + data[1])
        elif payload == Node.Payload.BYTE_OUTPUT:  # Return raw bytes
            return self._wait_for_response(node, Packet.DATA_RESPONSE, Packet.DATA_REQUEST, following=bytes([(payload.value << 4) + index]), timeout=timeout)[1:]

    def send_data(self, node, payload, data, index=0, timeout=None):
        """Send data to a node supporting data sinking.

        Args:
            node (Node): Node to send data to.
            payload (Node.Payload): Payload type of data to send.
            data: Data to be sent to device, type dependant on payload.
            index (int): Address of payload on node if multiple available.
        """
        if type(node) != Node:  # Check node is a valid Node
            raise TypeError('Invalid node.')
        if type(payload) != Node.Payload:  # Check payload is a valid Node.Payload
            raise TypeError('Invalid IO payload.')
        if type(index) != int:
            raise TypeError('Invalid index.')
        if payload not in (Node.Payload.DIGITAL_INPUT, Node.Payload.BYTE_INPUT, Node.Payload.INT_1B_INPUT, Node.Payload.INT_2B_INPUT):
            raise ValueError('Cannot send data to a source node.')
        if index < 0 or index > 15:
            raise ValueError('Index out of bounds (0-15).')
        if payload == Node.Payload.BYTE_INPUT:
            self._xbee.tx(dest_addr_long=node.long_addr, data=bytes([Packet.SET_REQUEST.value, (payload.value << 4) + index]) + data)
        elif payload == Node.Payload.INT_1B_INPUT:
            if type(data) != int:
                raise TypeError('Invalid data type for INT_1B_Input.')
            if data < 0 or data > 255:
                raise ValueError('Data out of bounds (0-255).')
            self._xbee.tx(dest_addr_long=node.long_addr, data=bytes([Packet.SET_REQUEST.value, (payload.value << 4) + index, data]))
        elif payload == Node.Payload.INT_2B_INPUT:
            if type(data) != int:
                raise TypeError('Invalid data type for INT_2B_Input.')
            if data < 0 or data > 65535:
                raise ValueError('Data out of bounds (0-65535).')
            self._xbee.tx(dest_addr_long=node.long_addr, data=bytes([Packet.SET_REQUEST.value, (payload.value << 4) + index, data >> 8, data & 255]))
        elif payload == Node.Payload.DIGITAL_INPUT:
            if type(data) not in (list, tuple) or len(data) != 8:
                raise ValueError("Data is not in correct format for specified payload type.")
            out = 0
            for i in reversed(range(0, 8)):
                if type(data[i]) != bool:
                    raise ValueError("Data is not in correct format for specified payload type.")
                if data[i] == True:
                    out += 1 << i
            print(out)
            self._xbee.tx(dest_addr_long=node.long_addr, data=bytes([Packet.SET_REQUEST.value, (payload.value << 4) + index, out]))
        logger.info('Waiting for ACK after having sent data')
        self._wait_for_response(node, Packet.CTRL_ACK, Packet.SET_REQUEST, following=bytes([Packet.SET_REQUEST.value]), timeout=timeout)

    @staticmethod
    def convert_payload(payload, data):
        if payload == Node.Payload.BYTE_INPUT:
            return bytes([data])
