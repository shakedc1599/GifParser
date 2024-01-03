import binascii
import math
import typing

import bitstring
from PIL import Image as Image_PIL

from BitStream import BitStreamReader
from reader_writer.constants import *

from gif import *
from lzw import lzw_decode
from .block_prefix import BlockPrefix


def read_gif(io: typing.BinaryIO, create_images: bool) -> Gif:
    gif_object: Gif = Gif()

    gif_stream: BitStreamReader = BitStreamReader(bitstring.ConstBitStream(io))

    decode_header(gif_stream, gif_object)
    decode_logical_screen_descriptor(gif_stream, gif_object)

    # There is no global color table if the size is 0.
    if gif_object.global_color_table_size > MIN_TABLE_SIZE:
        decode_global_color_table(gif_stream, gif_object)

    # Read the first byte to check if the next block is extension or image descriptor.
    while (prefix := BlockPrefix(gif_stream.read_bytes(BLOCK_PREFIX_LEN_BYTE))) != BlockPrefix.Trailer:
        if prefix is BlockPrefix.Extension:
            # Check which type of extension is the next block.
            extension_label: bytes = gif_stream.read_bytes(BLOCK_PREFIX_LEN_BYTE)
            prefix = BlockPrefix(extension_label)

            if prefix is BlockPrefix.ApplicationExtension:
                decode_application_extension(gif_stream, gif_object)

            elif prefix is BlockPrefix.GraphicControlExtension:
                decode_graphic_control_extension(gif_stream, gif_object)

            elif prefix is BlockPrefix.CommentExtension:
                decode_comment_extension(gif_stream, gif_object)

            elif prefix is BlockPrefix.PlainTextExtension:
                decode_plain_text(gif_stream, gif_object)

        elif prefix is BlockPrefix.ImageDescriptor:
            decode_image_descriptor(gif_stream, gif_object)

            # Check if there is a Local color table for this image.
            if gif_object.images[LAST_ELEMENT].local_color_table_flag:
                decode_local_color_table(gif_stream, gif_object)

            decode_image_data(gif_stream, gif_object, create_images)

            last_graphic_control_index = gif_object.images[LAST_ELEMENT].index_graphic_control_ex
            last_graphic_control_disposal = gif_object.graphic_control_extensions[last_graphic_control_index].disposal
            if last_graphic_control_disposal == DISPOSAL_OPTION_THREE:
                gif_object.images.append(gif_object.images[PENULTIMATE])
            elif last_graphic_control_disposal == DISPOSAL_OPTION_TWO:
                insert_background_frame(gif_object)

        elif prefix is BlockPrefix.NONE:
            raise IncorrectFileFormat("prefix is incorrect")

    return gif_object


def decode_header(gif_stream: BitStreamReader, gif_object: Gif) -> None:
    gif_object.version = gif_stream.read_decoded(VERSION_LEN_BYTE)


def decode_logical_screen_descriptor(gif_stream: BitStreamReader, gif_object: Gif) -> None:
    gif_object.width = gif_stream.read_unsigned_integer(GIF_WIDTH_LEN_BYTE, 'bytes')
    gif_object.height = gif_stream.read_unsigned_integer(GIF_HEIGHT_LEN_BYTE, 'bytes')

    global_color_table_exist = gif_stream.read_bool()

    # both not relevant
    gif_object.color_resolution = gif_stream.read_unsigned_integer(GIF_COLOR_RESOLUTION_LEN_BITS, 'bits')
    gif_object.sort_flag = gif_stream.read_bool()

    global_color_table_size_value = gif_stream.read_unsigned_integer(GIF_GLOBAL_COLOR_TABLE_SIZE_LEN_BITS, 'bits')
    if global_color_table_exist:
        gif_object.global_color_table_size = pow(2, global_color_table_size_value + 1)
    else:
        gif_object.global_color_table_size = DEFAULT_GLOBAL_COLOR_SIZE

    gif_object.background_color_index = gif_stream.read_unsigned_integer(GIF_BACKGROUND_COLOR_INDEX_LEN_BYTE, 'bytes')

    pixel_ratio_value = gif_stream.read_unsigned_integer(GIF_PIXEL_RATIO_VALUE_LEN_BYTE, 'bytes')
    gif_object.pixel_aspect_ratio = (pixel_ratio_value + WIDER_RANGE_RATIO) / NORMALIZED_VALUE


def insert_background_frame(gif_object: Gif):
    prev_image = gif_object.images[LAST_ELEMENT]
    current_image = Frame()
    current_image.index_graphic_control_ex = None

    current_image.left = prev_image.left
    current_image.top = prev_image.top
    current_image.width = prev_image.width
    current_image.height = prev_image.height

    current_image.local_color_table_flag = False
    current_image.interlace_flag = False
    current_image.sort_flag = False
    current_image.reserved = DEFAULT_RESERVED_SIZE
    current_image.size_of_local_color_table = DEFAULT_LOCAL_COLOR_TABLE_SIZE

    background_color: bytes = gif_object.global_color_table[gif_object.background_color_index]
    current_image.image_data = [background_color] * prev_image.width * prev_image.height

    gif_object.images.append(current_image)


def decode_global_color_table(gif_stream: BitStreamReader, gif_object: Gif) -> None:
    """
    Decode global color table.
    We read the number of bytes we received in the flag in Logical Screen Descriptor,
    and divided into triplets of bytes pairs, each triplet representing RGB of a color.
    """
    gif_object.global_color_table = [gif_stream.read_bytes(RGB_LEN_BYTE) for _ in range(
        int(gif_object.global_color_table_size))]


def decode_application_extension(gif_stream: BitStreamReader, gif_object: Gif) -> None:
    app_ex = ApplicationExtension()

    block_size = gif_stream.read_unsigned_integer(BLOCK_SIZE_LEN_BYTE, 'bytes')
    if block_size != APPLICATION_EXTENSION_BLOCK_SIZE:
        raise IncorrectFileFormat(
            f'application extension block size is {block_size}, and should be {APPLICATION_EXTENSION_BLOCK_SIZE}')

    app_ex.application_name = gif_stream.read_bytes(APPLICATION_NAME_LEN_BYTE).decode("utf-8")
    app_ex.identify = gif_stream.read_bytes(APPLICATION_IDENTIFY_LEN_BYTE).decode("utf-8")

    application_data = b''
    while (number_of_sub_block_bytes := gif_stream.read_unsigned_integer(BLOCK_SIZE_LEN_BYTE, 'bytes')) != END_OF_DATA:
        sub_block = gif_stream.read_bytes(number_of_sub_block_bytes)
        application_data += sub_block

    app_ex.data = application_data
    gif_object.applications_extensions.append(app_ex)
    gif_object.structure.append(app_ex)


def decode_graphic_control_extension(gif_stream: BitStreamReader, gif_object: Gif) -> None:
    graphic_control_ex = GraphicControlExtension()

    # always 4 bytes
    block_size = gif_stream.read_unsigned_integer(BLOCK_SIZE_LEN_BYTE, "bytes")
    if block_size != GRAPHIC_CONTROL_EXTENSION_BLOCK_SIZE:
        raise IncorrectFileFormat(
            f'graphic control extension size is {block_size}, but should be {GRAPHIC_CONTROL_EXTENSION_BLOCK_SIZE}')

    # flags from Packed Fields
    graphic_control_ex.reserved = gif_stream.read_unsigned_integer(RESERVED_LEN_BIT, "bits")
    graphic_control_ex.disposal = gif_stream.read_unsigned_integer(DISPOSAL_LEN_BIT, "bits")
    graphic_control_ex.user_input_flag = gif_stream.read_bool()
    graphic_control_ex.transparent_color_flag = gif_stream.read_bool()

    graphic_control_ex.delay_time = gif_stream.read_unsigned_integer(DELAY_TIME_LEN_BYTE, "bytes")
    graphic_control_ex.transparent_index = gif_stream.read_unsigned_integer(TRANSPARENT_INDEX_LEN_BYTE, "bytes")

    block_terminator = gif_stream.read_unsigned_integer(BLOCK_TERMINATOR_LEN_BYTE, "bytes")

    # Check block terminator
    if block_terminator != BLOCK_TERMINATOR_VALUE:
        raise IncorrectFileFormat(
            f'Should be block terminator({BLOCK_TERMINATOR_VALUE}) but we read {block_terminator}')

    gif_object.graphic_control_extensions.append(graphic_control_ex)
    gif_object.structure.append(graphic_control_ex)


def decode_image_descriptor(gif_stream: BitStreamReader, gif_object: Gif) -> None:
    current_image = Frame()
    if gif_object.graphic_control_extensions == []:
        current_image.index_graphic_control_ex = None
    else:
        current_image.index_graphic_control_ex = len(gif_object.graphic_control_extensions) - 1

    current_image.left = gif_stream.read_unsigned_integer(FRAME_LEFT_LEN_BYTE, 'bytes')
    current_image.top = gif_stream.read_unsigned_integer(FRAME_TOP_LEN_BYTE, 'bytes')
    current_image.width = gif_stream.read_unsigned_integer(FRAME_WIDTH_LEN_BYTE, 'bytes')
    current_image.height = gif_stream.read_unsigned_integer(FRAME_HEIGHT_LEN_BYTE, 'bytes')

    current_image.local_color_table_flag = gif_stream.read_bool()
    current_image.interlace_flag = gif_stream.read_bool()
    current_image.sort_flag = gif_stream.read_bool()
    current_image.reserved = gif_stream.read_unsigned_integer(FRAME_RESERVED_LEN_BIT, 'bits')
    current_image.size_of_local_color_table = gif_stream.read_unsigned_integer(SIZE_LOCAL_COLOR_TABLE_LEN_BIT, 'bits')

    gif_object.images.append(current_image)
    gif_object.structure.append(current_image)


def decode_local_color_table(gif_stream: BitStreamReader, gif_object: Gif) -> None:
    current_image = gif_object.images[LAST_ELEMENT]
    size_of_color_table = math.pow(2, current_image.size_of_local_color_table + 1)

    colors_array = [gif_stream.read_bytes(RGB_LEN_BYTE) for _ in range(int(size_of_color_table))]
    gif_object.local_color_tables.append(colors_array)
    current_image.local_color_table = colors_array


def decode_image_data(gif_stream: BitStreamReader, gif_object: Gif, create_images: bool) -> None:
    current_image = gif_object.images[LAST_ELEMENT]
    current_image.lzw_minimum_code_size = gif_stream.read_unsigned_integer(LZW_MINIMUM_CODE_SIZE_LEN_BYTE, 'bytes')

    assert (MINIMUM_LZW_CS <= current_image.lzw_minimum_code_size <= MAXIMUM_LZW_CS
            ), f"lzw minimum code size is out of rage (should be between {MINIMUM_LZW_CS} to {MAXIMUM_LZW_CS})"

    compressed_sub_block = b''
    while (number_of_sub_block_bytes := gif_stream.read_unsigned_integer(BLOCK_SIZE_LEN_BYTE, 'bytes')) != END_OF_DATA:
        compressed_sub_block += gif_stream.read_bytes(number_of_sub_block_bytes)
    if not compressed_sub_block:
        current_image.img = None
        return

    res, index_length = lzw_decode(compressed_sub_block, current_image.lzw_minimum_code_size)

    if current_image.local_color_table_flag:
        local_color_table = gif_object.local_color_tables[LAST_ELEMENT]
    else:
        local_color_table = gif_object.global_color_table

    for pos in range(0, len(res), index_length):
        current_index = int((res[pos:pos + index_length]), 2)

        if (current_index == gif_object.graphic_control_extensions[LAST_ELEMENT].transparent_index and
                gif_object.graphic_control_extensions[LAST_ELEMENT].transparent_color_flag):
            # if the index it transparent we put -1 and in the future we will change it to correct color
            current_image.image_data.append(TRANSPARENT_VALUE)
        else:
            current_image.image_data.append(local_color_table[current_index])
        current_image.raw_data.append(local_color_table[current_index])
    if create_images:
        create_img(gif_object, current_image.image_data)


def create_img(gif_object: Gif, image_data: list[bytes]) -> None:
    current_image = gif_object.images[LAST_ELEMENT]
    #  for all the images except the first
    image_size = current_image.width * current_image.height
    assert image_size == len(
        image_data), f"size mismatch: gif_size {image_size} does not match the length of image_information {len(image_data)}"

    curr_top = current_image.top
    curr_left = current_image.left
    curr_width = current_image.width
    curr_height = current_image.height

    if len(gif_object.images) == 1:
        if current_image.local_color_table_flag:
            background_color = gif_object.local_color_tables[LAST_ELEMENT][gif_object.background_color_index]
        else:
            background_color = gif_object.global_color_table[gif_object.background_color_index]

        new_img_data = [background_color] * gif_object.height * gif_object.width
        last_width = gif_object.width

    else:
        last_image = gif_object.images[PENULTIMATE]
        last_width = last_image.width
        new_img_data = last_image.image_data

        # fill all the TRANSPARENT_VALUE in the current Image with colors from last_image
        for i in range(curr_height):
            for j in range(curr_width):
                if current_image.image_data[i * curr_width + j] == TRANSPARENT_VALUE:
                    current_image.image_data[i * curr_width + j] = last_image.image_data[
                        (i + curr_top) * last_width + j + curr_left]

    # at first the new image data get the value of the last image. all the overlap indexes getting the current
    # image colors
    pos = 0
    for line in range(curr_top, curr_top + curr_height):
        new_img_data[
        line * last_width + curr_left: line * last_width + curr_left + curr_width] = current_image.image_data[
                                                                                     pos: pos + curr_width]
        pos += curr_width

    current_image.image_data = new_img_data

    img = Image_PIL.new('RGB', (gif_object.width, gif_object.height))
    rgb_array = ["#" + binascii.hexlify(b).decode('utf-8').upper() for b in current_image.image_data]

    # Set the pixel values of the image using the RGB array
    pixels = img.load()

    ''' 
    for each pixel - we take specific color ("#FF0000") and divide it to 3 parts("FF","00","00") of RGB.
    then convert it from hex(16) to int (255,0,0), in the end we get tuple of three numbers that represent the color
    The code iterates over each pixel in an image represented as a two-dimensional array of hex color codes.
    It then extracts the red, green, and blue color components of each pixel by converting the hex codes to integers
    and stores them as a tuple of three integers
    '''
    for row in range(gif_object.width):
        for column in range(gif_object.height):
            hex_color = rgb_array[column * gif_object.width + row]
            r, g, b = (
                int(hex_color[R_START:R_END], HEX_SIZE), int(hex_color[G_START:G_END], HEX_SIZE),
                int(hex_color[B_START:B_END], HEX_SIZE)
            )
            pixels[row, column] = (r, g, b)
    current_image.img = img


def decode_comment_extension(gif_stream: BitStreamReader, gif_object: Gif) -> None:
    """decode comment extension"""
    comment_ex = CommentExtension()
    data = b''
    # every sub block start with a bye that present the size of it.
    sub_block_size = gif_stream.read_unsigned_integer(BLOCK_SIZE_LEN_BYTE, "bytes")
    while sub_block_size != END_OF_DATA:
        data += gif_stream.read_bytes(sub_block_size)
        sub_block_size = gif_stream.read_unsigned_integer(BLOCK_SIZE_LEN_BYTE, "bytes")

    comment_ex.data = data
    gif_object.comments_extensions.append(comment_ex)
    gif_object.structure.append(comment_ex)


def decode_plain_text(gif_stream: BitStreamReader, gif_object: Gif) -> None:
    plain_text_ex = PlainTextExtension()

    # Read the block size (always 12)
    block_size = gif_stream.read_unsigned_integer(BLOCK_SIZE_LEN_BYTE, "bytes")
    if block_size != PLAIN_TEXT_EXTENSION_BLOCK_SIZE:
        raise IncorrectFileFormat(
            f'plain text extension block size should be {PLAIN_TEXT_EXTENSION_BLOCK_SIZE} not {block_size}')

    plain_text_ex.left = gif_stream.read_unsigned_integer(PLAIN_TEXT_LEFT_LEN_BYTE, "bytes")
    plain_text_ex.top = gif_stream.read_unsigned_integer(PLAIN_TEXT_TOP_LEN_BYTE, "bytes")
    plain_text_ex.width = gif_stream.read_unsigned_integer(PLAIN_TEXT_WIDTH_LEN_BYTE, "bytes")
    plain_text_ex.height = gif_stream.read_unsigned_integer(PLAIN_TEXT_HEIGHT_LEN_BYTE, "bytes")
    plain_text_ex.char_width = gif_stream.read_unsigned_integer(PLAIN_TEXT_CHAR_WIDTH_LEN_BYTE, "bytes")
    plain_text_ex.char_height = gif_stream.read_unsigned_integer(PLAIN_TEXT_CHAR_HEIGHT_LEN_BYTE, "bytes")
    plain_text_ex.text_color = gif_stream.read_unsigned_integer(PLAIN_TEXT_TEXT_COLOR_LEN_BYTE, "bytes")
    plain_text_ex.background_color = gif_stream.read_unsigned_integer(PLAIN_TEXT_BACKGROUND_COLOR_LEN_BYTE, "bytes")

    data = b''
    # every data sub block start with a bye that present the size of it.
    sub_block_size = gif_stream.read_unsigned_integer(BLOCK_SIZE_LEN_BYTE, "bytes")
    while sub_block_size != END_OF_DATA:
        data += gif_stream.read_bytes(sub_block_size)
        sub_block_size = gif_stream.read_unsigned_integer(BLOCK_SIZE_LEN_BYTE, "bytes")

    plain_text_ex.data = data
    gif_object.plain_text_extensions.append(plain_text_ex)
    gif_object.structure.append(plain_text_ex)
