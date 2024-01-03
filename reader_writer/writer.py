import math
import bitstring
from BitStream import BitStreamWriter
from reader_writer.constants import *
from gif import *
from lzw import lzw_encode
from utils import chunker
from .block_prefix import BlockPrefix


def index_from_data(image_data, color_table):
    size_of_index = math.ceil(math.log(len(color_table), 2)) + 1
    data = bitstring.BitArray()
    for color in image_data:
        data.append(f"uint:{size_of_index}={color_table.index(color)}")
    return data


def write_gif(gif_object: Gif, max_clean: bool) -> BitStreamWriter:
    gif_stream = BitStreamWriter()

    write_header(gif_stream, gif_object)
    write_logical_screen_descriptor(gif_stream, gif_object)

    if gif_object.global_color_table_size > MIN_TABLE_SIZE:
        write_global_color_table(gif_stream, gif_object.global_color_table)
    for block in gif_object.structure:
        if isinstance(block, Frame):
            if block.local_color_table_flag:
                write_image(gif_stream, block, block.local_color_table)
            else:
                write_image(gif_stream, block, gif_object.global_color_table)
        elif isinstance(block, CommentExtension):
            # not write comment block if max clean is true
            if not max_clean:
                write_comment_extension(gif_stream, block)
        elif isinstance(block, PlainTextExtension):
            write_plain_text(gif_stream, block)
        elif isinstance(block, GraphicControlExtension):
            write_graphic_control_extension(gif_stream, block)
        elif isinstance(block, ApplicationExtension):
            write_application_extension(gif_stream, block)
        else:
            raise Exception("not a gif object in structure")

    gif_stream.write_bytes(BlockPrefix.Trailer.value)
    return gif_stream


def write_header(gif_stream: BitStreamWriter, gif_object: Gif) -> None:
    version_bytes = gif_object.version.encode()
    gif_stream.write_bytes(version_bytes)


def write_logical_screen_descriptor(gif_stream: BitStreamWriter, gif_object: Gif) -> None:
    gif_stream.write_unsigned_integer(gif_object.width, GIF_WIDTH_LEN_BYTE, 'bytes')
    gif_stream.write_unsigned_integer(gif_object.height, GIF_HEIGHT_LEN_BYTE, 'bytes')

    # if global color table exist
    global_color_table_exist = gif_object.global_color_table_size > MIN_TABLE_SIZE
    gif_stream.write_bool(global_color_table_exist)

    # both not relevant
    gif_stream.write_unsigned_integer(gif_object.color_resolution, GIF_COLOR_RESOLUTION_LEN_BITS, 'bits')
    gif_stream.write_bool(gif_object.sort_flag)

    if global_color_table_exist:
        global_color_table_size_value = int(math.log2(gif_object.global_color_table_size)) - 1
        gif_stream.write_unsigned_integer(global_color_table_size_value, GIF_GLOBAL_COLOR_TABLE_SIZE_LEN_BITS, 'bits')
    else:
        gif_stream.write_unsigned_integer(DEFAULT_GLOBAL_COLOR_SIZE, GIF_GLOBAL_COLOR_TABLE_SIZE_LEN_BITS, 'bits')

    gif_stream.write_unsigned_integer(gif_object.background_color_index, GIF_BACKGROUND_COLOR_INDEX_LEN_BYTE, 'bytes')

    pixel_ratio_value = int(gif_object.pixel_aspect_ratio * NORMALIZED_VALUE - WIDER_RANGE_RATIO)
    gif_stream.write_unsigned_integer(pixel_ratio_value, GIF_PIXEL_RATIO_VALUE_LEN_BYTE, 'bytes')


def write_global_color_table(gif_stream: BitStreamWriter, global_color_table: list[bytes]) -> None:
    gif_stream.write_bytes(b''.join(global_color_table))


def write_application_extension(gif_stream: BitStreamWriter, application_ex: ApplicationExtension) -> None:
    gif_stream.write_bytes(BlockPrefix.Extension.value)
    gif_stream.write_bytes(BlockPrefix.ApplicationExtension.value)
    gif_stream.write_unsigned_integer(APPLICATION_EXTENSION_BLOCK_SIZE, APPLICATION_EXTENSION_BLOCK_SIZE_LEN_BYTE,
                                      'bytes')

    gif_stream.write_bytes(application_ex.application_name.encode())
    gif_stream.write_bytes(application_ex.identify.encode())

    # looping in chinks of 255 bytes
    for sub_block in chunker(BYTE_MAX_NUMBER, application_ex.data):
        sub_block_size = len(sub_block)
        gif_stream.write_unsigned_integer(sub_block_size, BLOCK_SIZE_LEN_BYTE, 'bytes')
        gif_stream.write_bytes(sub_block)

    gif_stream.write_bytes(BlockPrefix.Terminator.value)


def write_graphic_control_extension(gif_stream: BitStreamWriter, graphic_control_ex: GraphicControlExtension) -> None:
    gif_stream.write_bytes(BlockPrefix.Extension.value)
    gif_stream.write_bytes(BlockPrefix.GraphicControlExtension.value)

    gif_stream.write_unsigned_integer(GRAPHIC_CONTROL_EXTENSION_BLOCK_SIZE,
                                      GRAPHIC_CONTROL_EXTENSION_BLOCK_SIZE_LEN_BYTE, 'bytes')

    # write package
    gif_stream.write_unsigned_integer(graphic_control_ex.reserved, RESERVED_LEN_BIT, 'bits')
    gif_stream.write_unsigned_integer(graphic_control_ex.disposal, DISPOSAL_LEN_BIT, 'bits')
    gif_stream.write_bool(graphic_control_ex.user_input_flag)
    gif_stream.write_unsigned_integer(graphic_control_ex.transparent_color_flag, TRANSPARENT_COLOR_FLAG_LEN_BIT, 'bits')

    gif_stream.write_unsigned_integer(graphic_control_ex.delay_time, DELAY_TIME_LEN_BYTE, 'bytes')
    gif_stream.write_unsigned_integer(graphic_control_ex.transparent_index, BLOCK_TERMINATOR_LEN_BYTE, 'bytes')

    gif_stream.write_bytes(BlockPrefix.Terminator.value)


def write_image(gif_stream: BitStreamWriter, image: Frame, color_table: list[bytes]) -> None:
    # Image Descriptor
    gif_stream.write_bytes(BlockPrefix.ImageDescriptor.value)
    gif_stream.write_unsigned_integer(image.left, FRAME_LEFT_LEN_BYTE, 'bytes')
    gif_stream.write_unsigned_integer(image.top, FRAME_TOP_LEN_BYTE, 'bytes')
    gif_stream.write_unsigned_integer(image.width, FRAME_WIDTH_LEN_BYTE, 'bytes')
    gif_stream.write_unsigned_integer(image.height, FRAME_HEIGHT_LEN_BYTE, 'bytes')

    # write package
    gif_stream.write_bool(image.local_color_table_flag)
    gif_stream.write_unsigned_integer(image.interlace_flag, FRAME_INTERLACE_FLAG_LEN_BIT, 'bits')
    gif_stream.write_unsigned_integer(image.sort_flag, FRAME_SORT_FLAG_LEN_BIT, 'bits')
    gif_stream.write_unsigned_integer(image.reserved, FRAME_RESERVED_LEN_BIT, 'bits')
    gif_stream.write_unsigned_integer(image.size_of_local_color_table, SIZE_LOCAL_COLOR_TABLE_LEN_BIT, 'bits')

    # Local Color Table
    if image.local_color_table_flag:
        gif_stream.write_bytes(b''.join(image.local_color_table))

    # Image Data
    gif_stream.write_unsigned_integer(int(math.ceil(math.log2(len(color_table)))), COLOR_TABLE_FLAG_LEN_BYTE, 'bytes')

    data = index_from_data(image.raw_data, color_table)
    encoded = lzw_encode(data, len(color_table))

    if encoded:
        # looping in chunks of 255 bytes
        for sub_block in chunker(BYTE_MAX_NUMBER, encoded):
            sub_block_size = len(sub_block)
            gif_stream.write_unsigned_integer(sub_block_size, BLOCK_SIZE_LEN_BYTE, 'bytes')
            gif_stream.write_bytes(sub_block)

    gif_stream.write_bytes(BlockPrefix.Terminator.value)


def write_comment_extension(gif_stream: BitStreamWriter, comment: CommentExtension) -> None:
    gif_stream.write_bytes(BlockPrefix.Extension.value)
    gif_stream.write_bytes(BlockPrefix.CommentExtension.value)

    # looping in chinks of 255 bytes
    for sub_block in chunker(BYTE_MAX_NUMBER, comment.data):
        sub_block_size = len(sub_block)
        gif_stream.write_unsigned_integer(sub_block_size, BLOCK_SIZE_LEN_BYTE, 'bytes')
        gif_stream.write_bytes(sub_block)

    gif_stream.write_bytes(BlockPrefix.Terminator.value)


def write_plain_text(gif_stream: BitStreamWriter, plain_text: PlainTextExtension) -> None:
    gif_stream.write_bytes(BlockPrefix.Extension.value)
    gif_stream.write_bytes(BlockPrefix.PlainTextExtension.value)

    gif_stream.write_unsigned_integer(PLAIN_TEXT_EXTENSION_BLOCK_SIZE, PLAIN_TEXT_EXTENSION_BLOCK_SIZE_LEN_BYTE,
                                      'bytes')
    gif_stream.write_unsigned_integer(plain_text.left, PLAIN_TEXT_LEFT_LEN_BYTE, 'bytes')
    gif_stream.write_unsigned_integer(plain_text.top, PLAIN_TEXT_TOP_LEN_BYTE, 'bytes')
    gif_stream.write_unsigned_integer(plain_text.width, PLAIN_TEXT_WIDTH_LEN_BYTE, 'bytes')
    gif_stream.write_unsigned_integer(plain_text.height, PLAIN_TEXT_HEIGHT_LEN_BYTE, 'bytes')
    gif_stream.write_unsigned_integer(plain_text.char_width, PLAIN_TEXT_CHAR_WIDTH_LEN_BYTE, 'bytes')
    gif_stream.write_unsigned_integer(plain_text.char_height, PLAIN_TEXT_CHAR_HEIGHT_LEN_BYTE, 'bytes')
    gif_stream.write_unsigned_integer(plain_text.text_color, PLAIN_TEXT_TEXT_COLOR_LEN_BYTE, 'bytes')
    gif_stream.write_unsigned_integer(plain_text.background_color, PLAIN_TEXT_BACKGROUND_COLOR_LEN_BYTE, 'bytes')

    # looping in chunks of 255 bytes
    for sub_block in chunker(BYTE_MAX_NUMBER, plain_text.data):
        sub_block_size = len(sub_block)
        gif_stream.write_unsigned_integer(sub_block_size, BLOCK_SIZE_LEN_BYTE, 'bytes')
        gif_stream.write_bytes(sub_block)

    gif_stream.write_bytes(BlockPrefix.Terminator.value)
