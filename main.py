import argparse
from reader_writer.constants import *
from reader_writer import read_gif, write_gif
from gif import Gif


def main(filename: str, output_path:  str, show_image: bool = False, max_clean: bool = False):
    with open(filename, "rb") as gif_file:
        gif: Gif = read_gif(gif_file, True)
        print("decoded")

    if show_image:
        print(f"showing images (first {NUMBER_OF_IMAGE_TO_SHOW})")
        for image in gif.images[:NUMBER_OF_IMAGE_TO_SHOW]:
            image.img.show()

    res = write_gif(gif, max_clean)
    with open(output_path, "wb") as f:
        res.to_file(f)
    print("saved")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='GIF Processing')
    parser.add_argument('filename', type=str, help='Path to the origin GIF file')
    parser.add_argument('output_path', type=str, help='Path where the new GIF will be written')
    parser.add_argument('--show_image', action='store_true', help=f'Display {NUMBER_OF_IMAGE_TO_SHOW} images')
    parser.add_argument('--max_clean', action='store_true', help='Perform full cleanup to the GIF')
    args = parser.parse_args()

    main(args.filename, args.output_path, args.show_image, args.max_clean)

