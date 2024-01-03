import math
from reader_writer.constants import *
from bitstring import BitArray, ConstBitStream


def initialize_code_table(color_table_size: int) -> dict[str, int]:
    # init table with dict, clear code and eof
    return {str(i): i for i in range(color_table_size + EOI_AND_CC)}


def prepend_uint_to_bitarray(bit_array: BitArray, value: int, code_size: int):
    """
    insert value to bit_array at the start, padding to code size if needed
    @param bit_array:
    @param value:
    @param code_size:
    @return:
    """
    bit_array.prepend(f"uint:{code_size}={value}")


def update_writing_size(table_size: int, code_size: int):
    """
    check if we need to increase the writing window if the table size +1 is representing binary more than the
    current writing window size
    :param table_size:
    :param code_size:
    :return: writing_size:
    """
    if table_size >= int(math.pow(2, code_size)) + 1:
        return code_size + 1
    return code_size


def get_next_element(stream: ConstBitStream, reading_size: int):
    """
    the next element represent in as string number. the riding size is constant
    :param stream:
    :param reading_size:
    :return: element
    """
    element = stream.read(f"uint{reading_size}")
    return str(element)


def lzw_encode(uncompressed_data: BitArray, color_table_size: int):
    """
    using lzw algorithm for compress data ang gif images
    the table code look like this:


        ______|______
      '0'     |  0
      '1'     |  1
      '2'     |  2
      '3'     |  3
      ...
      '0','0',| 298

    :param uncompressed_data:
    :param color_table_size:
    :return: compress_data:
    """
    # change data to be ConstBitStream object for reading
    # we got  1,1,1,1,1,2,2,.. that represent by '0x2492924.."
    stream = ConstBitStream(uncompressed_data)

    # the window size riding is the log of the size table plus 1
    # color table size +1 => it's for the end_of_information_code and clear_code,
    # (color table size +1) + 1 => it's for situations that the number isn't pow of two then we need added a bit for
    # riding the numbers (in our example = 3).
    # notice the reading size in constant - not change
    reading_size = math.ceil(math.log2(color_table_size)) + 1

    table = initialize_code_table(color_table_size)

    # if the next item in the table will need to be writen with more bit change now the writing size
    # because we're adding more indexes to the table, and now we need more bits to represent the numbers
    writing_size = update_writing_size(len(table), reading_size)

    # add the start of reading (in our example = 4)
    clear_code = table[str(len(table) - EOI_AND_CC)]
    #  add the enf of reading (in our example = 5)
    end_of_information_code = table[str(len(table) - 1)]
    compress_data = BitArray()
    #  add clear code according the reading size (in our example = 4)

    prepend_uint_to_bitarray(compress_data, clear_code, writing_size)

    length = stream.length

    # the first item
    previous_element = get_next_element(stream, reading_size)

    while stream.pos != length:
        # reading the next item
        current_element = get_next_element(stream, reading_size)
        previous_and_current = previous_element + "," + current_element

        # if it is in the table continue
        if previous_and_current in table:
            previous_element = previous_and_current
        elif len(table) == RESET_SIZE:
            prepend_uint_to_bitarray(compress_data, table[previous_element], MAX_WRITING_SIZE)
            prepend_uint_to_bitarray(compress_data, clear_code, MAX_WRITING_SIZE)
            table = initialize_code_table(color_table_size)
            writing_size = update_writing_size(len(table), reading_size)
            previous_element = current_element
        else:
            # add the new concat to the table
            table[previous_and_current] = len(table)

            # write the compressed value to the output
            prepend_uint_to_bitarray(compress_data, table[previous_element], writing_size)

            # checking if to change the writing size
            writing_size = update_writing_size(len(table), writing_size)
            previous_element = current_element

    # add the last element to the output
    prepend_uint_to_bitarray(compress_data, table[previous_element], writing_size)

    # add the end to the output - for inform that is the end ot the data
    prepend_uint_to_bitarray(compress_data, end_of_information_code, writing_size)

    # fill zeros to be represented by 8 bits and flip the data
    prepend_uint_to_bitarray(compress_data, ZERO, BYTE_LEN - compress_data.length % BYTE_LEN)

    # reversing data (in place)
    compress_data.byteswap()
    return compress_data.bytes
