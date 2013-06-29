
from __future__ import with_statement

import argparse
import contextlib
import glob
import os
import os.path
import re
import shutil
import sys

import metadata
import transcode

# Perform the following replacements on generated filename parts
FILENAME_REPLACE = [
    ('/', '-')
]

# Delete the following characters from generated filename parts
FILENAME_DELETE = '\'"?'

# Supported output formats for transcoding
TRANSCODE_FORMATS = ('mp3', 'ogg')

# Supported input formats
INPUT_FORMATS = ('mp3', 'ogg', 'flac')

# Default quality level for each transcode format
TRANSCODE_QUALITY = {
    'mp3': 1,
    'ogg': 6
}

@contextlib.contextmanager
def file_cleanup(filename):
    try:
        yield
    except:
        if os.path.exists(filename):
            os.unlink(filename)
        raise


class MusicManagerCli(object):

    def __format_output(self, args):
        return ''.join(arg.encode('utf_8') if isinstance(arg, unicode) else str(arg) for arg in args)

    def error(self, *args):
        sys.stderr.write(self.__format_output(args) + '\n')

    def info(self, *args):
        if not self.quiet:
            print self.__format_output(args)

    def debug(self, *args):
        if self.verbose:
            print self.__format_output(args)

    def get_ext(self, filename):
        ext = os.path.splitext(filename)[1].lower()
        if ext.startswith('.'):
            return ext[1:]
        else:
            return ext

    def find_files(self, directories, exts):
        exts = [ext.lower() for ext in exts]

        for directory in directories:
            for root, dirs, files in os.walk(directory):
                for f in files:
                    ext = self.get_ext(f)
                    if ext in exts:
                        yield unicode(os.path.join(root, f), 'utf_8'), ext

    def __sanitize_filename_part(self, part):
        if not part:
            return part

        for char_from, char_to in FILENAME_REPLACE:
            part = part.replace(char_from, char_to)

        return re.sub('[' + re.escape(FILENAME_DELETE) + ']', '', part)

    def __sanitize_filename_parts(self, _tags):
        tags = _tags.copy()
        for k, v in tags.items():
            if isinstance(v, basestring):
                tags[k] = self.__sanitize_filename_part(v)
        return tags

    def generate_filename(self, tags, is_various, ext='mp3'):
        fields = self.__sanitize_filename_parts(tags)
        fields['ext'] = ext
        path_parts = []

        # Artist
        if is_various:
            path_parts.append('Various Artists')
        else:
            path_parts.append('%(artist)s' % fields)

        # Album
        if fields.get('date'):
            path_parts.append('%(album)s [%(date)s]' % fields)
        else:
            path_parts.append('%(album)s' % fields)

        # Track
        if fields.get('track'):
            path_parts.append('%(track)02d - %(title)s.%(ext)s' % fields)
        else:
            path_parts.append('%(title)s.%(ext)s' % fields)

        full_name = os.path.join(*path_parts)

        return full_name

    def copy(self, source_filename, dest_filename, try_lazy=True):
        """Lazy copy. Tries creating a hard link before falling back to a proper copy"""

        if self.dry_run:
            return

        if try_lazy:
            try:
                os.link(source_filename, dest_filename)
                return
            except OSError, e:
                self.debug('Could not link ', dest_filename, ' from ', source_filename, ': ', e)
                pass

        shutil.copy2(source_filename, dest_filename)

    def delete(self, filename):
        if self.dry_run:
            return
        os.unlink(filename)

    def list_logs(self, directory):
        for f in os.listdir(directory):
            full_path = os.path.join(directory, f)
            if os.path.isfile(full_path) and full_path.endswith('.log'):
                yield full_path

    def __target_directory_prep(self, old_dir, new_dir):
        if self.dry_run:
            return

        if not os.path.exists(new_dir):
            os.makedirs(new_dir)

        # Copy log files
        for log_file in self.list_logs(old_dir):
            self.copy(log_file, new_dir, False)

        # Write a file tracking the source location of the music
        sourced_from_source = os.path.join(old_dir, 'moved_from')
        sourced_from_dest = os.path.join(new_dir, 'moved_from')

        if not os.path.exists(sourced_from_dest):
            if os.path.exists(sourced_from_source):
                self.copy(sourced_from_source, sourced_from_dest, False)
            else:
                sourced_from = open(sourced_from_dest, 'w')
                sourced_from.write(os.path.abspath(old_dir).encode('utf_8') + '\n')
                sourced_from.close()

    def __get_inputs(self, source_dirs, input_formats):
        raw_inputs = []
        various_artist_buckets = {}

        def _various_artist_key(source_file, ext, tags):
            return tags.get('album') + ';' + (tags.get('date') or '0000')

        for source_file, ext in self.find_files(source_dirs, input_formats):
            if ext == 'flac':
                tags = metadata.read_flac(source_file)
            else:
                tags = metadata.read_id3(source_file)

            if not (tags.get('artist') and tags.get('album') and tags.get('title')):
                self.error('Skipping ', source_file, ', not enough tags could be read: ', tags)
                continue

            raw_inputs.append((source_file, ext, tags))

            key = _various_artist_key(source_file, ext, tags)
            various_artist_buckets.setdefault(key, []).append(tags.get('artist'))

        inputs = []

        def _is_various_artist(artists):
            return len(set(artists)) > 1

        for source_file, ext, tags in raw_inputs:
            key = _various_artist_key(source_file, ext, tags)
            is_various = _is_various_artist(various_artist_buckets[key])
            inputs.append((source_file, ext, tags, is_various))

        return inputs

    def copy_command(self, args):
        input_formats = args.include or INPUT_FORMATS

        for source_file, source_ext, tags, is_various in self.__get_inputs(args.input, input_formats):
            dest_file = os.path.join(args.output, self.generate_filename(tags, is_various, source_ext))

            old_dir = os.path.dirname(source_file)
            new_dir = os.path.dirname(dest_file)

            # Remove existing targets with --force, otherwise skip
            if os.path.exists(dest_file):
                if args.force:
                    self.delete(dest_file)
                else:
                    self.debug('Skipping ', source_file, ', destination ', dest_file, ' already exists')
                    continue

            # Create target directory and copy over metadata
            self.__target_directory_prep(old_dir, new_dir)

            self.info('Copying ', dest_file, ' from ', source_file)

            with file_cleanup(dest_file):
                self.copy(source_file, dest_file, args.try_link)

    def copy_diff_command(self, args):
        input_dirs = args.input
        input_formats = args.include or INPUT_FORMATS

        for source_file, source_ext, tags, is_various in self.__get_inputs(input_dirs[:1], input_formats):
            search_match = None

            for search_ext in input_formats:
                search_file = os.path.join(input_dirs[1], self.generate_filename(tags, is_various, search_ext))
                if os.path.exists(search_file):
                    search_match = source_file
                    break

            if search_match:
                self.debug('Found matching input file ', search_match, ' for input ', source_file)
                continue

            dest_file = os.path.join(args.output, self.generate_filename(tags, is_various, source_ext))
            old_dir = os.path.dirname(source_file)
            new_dir = os.path.dirname(dest_file)

            # Remove existing targets with --force, otherwise skip
            if os.path.exists(dest_file):
                if args.force:
                    self.delete(dest_file)
                else:
                    self.debug('Skipping ', source_file, ', destination ', dest_file, ' already exists')
                    continue

            # Create target directory and copy over metadata
            self.__target_directory_prep(old_dir, new_dir)

            self.info('Copying ', dest_file, ' from ', source_file)

            with file_cleanup(dest_file):
                self.copy(source_file, dest_file, args.try_link)

    def copy_intersect_command(self, args):
        input_dirs = args.input
        input_formats = args.include or INPUT_FORMATS

        for source_file, source_ext, tags, is_various in self.__get_inputs(input_dirs[:1], input_formats):
            search_match = None

            for search_ext in input_formats:
                search_file = os.path.join(input_dirs[1], self.generate_filename(tags, is_various, search_ext))
                if os.path.exists(search_file):
                    search_match = source_file
                    break

            if not search_match:
                self.debug('Found no matching input file for ', source_file)
                continue

            dest_file = os.path.join(args.output, self.generate_filename(tags, is_various, source_ext))
            old_dir = os.path.dirname(source_file)
            new_dir = os.path.dirname(dest_file)

            # Remove existing targets with --force, otherwise skip
            if os.path.exists(dest_file):
                if args.force:
                    self.delete(dest_file)
                else:
                    self.debug('Skipping ', source_file, ', destination ', dest_file, ' already exists')
                    continue

            # Create target directory and copy over metadata
            self.__target_directory_prep(old_dir, new_dir)

            self.info('Copying ', dest_file, ' from ', source_file)

            with file_cleanup(dest_file):
                self.copy(source_file, dest_file, args.try_link)

    def transcode_command(self, args):
        quality = args.quality

        if quality is None:
            quality = TRANSCODE_QUALITY[args.format]

        for source_file, source_ext, tags, is_various in self.__get_inputs(args.input, ('flac',)):
            dest_ext = args.format
            dest_file = os.path.join(args.output, self.generate_filename(tags, is_various, dest_ext))

            old_dir = os.path.dirname(source_file)
            new_dir = os.path.dirname(dest_file)

            # Remove existing targets with --force, otherwise skip
            if os.path.exists(dest_file):
                if args.force:
                    self.delete(dest_file)
                else:
                    self.debug('Skipping ', source_file, ', destination ', dest_file, ' already exists')
                    continue

            # Create target directory and copy over metadata
            self.__target_directory_prep(old_dir, new_dir)

            self.info('Transcoding ', dest_file, ' from ', source_file)

            if args.dry_run:
                continue

            with file_cleanup(dest_file):
                if dest_ext == 'mp3':
                    transcode.flac_to_mp3(source_file, dest_file, quality)
                    metadata.write_id3(dest_file, tags)
                elif dest_ext == 'ogg':
                    transcode.flac_to_ogg(source_file, dest_file, quality)

    def main(self, argv):
        """
        Commands:

        - copy           copy/link from inputs to target
        - transcode      transcode from inputs to target
        - copy-diff      copy from first to target only if not present in second
        - copy-intersect copy from first to target only if present in second
        """

        parser = argparse.ArgumentParser(description='Manage your music library')
        parser.add_argument('-n', '--dry-run', action='store_true', help='dry run (do not write any files)')
        parser.add_argument('-q', '--quiet', action='store_true', help='run quietly (no output)')
        parser.add_argument('-v', '--verbose', action='store_true', help='output extra debug information')
        parser.add_argument('-f', '--force', action='store_true', help='overwrite existing destination files')

        subparsers = parser.add_subparsers()

        parser_copy = subparsers.add_parser('copy', help='copy/link from inputs to output')
        parser_copy.add_argument('-I', '--include', action='append', choices=INPUT_FORMATS, default=[], help='only copy the given formats')
        parser_copy.add_argument('-c', '--no-link', action='store_false', dest='try_link', help='always copy, never use hard links')
        parser_copy.add_argument('input', nargs='+', help='input directories')
        parser_copy.add_argument('output', help='output directory')
        parser_copy.set_defaults(func=self.copy_command)

        parser_copy_diff = subparsers.add_parser('copy-diff', help='copy from first input to output if no match is present in second input (output = first - second)')
        parser_copy_diff.add_argument('-I', '--include', action='append', choices=INPUT_FORMATS, default=[], help='only copy/compare the given formats')
        parser_copy_diff.add_argument('-c', '--no-link', action='store_false', dest='try_link', help='always copy, never use hard links')
        parser_copy_diff.add_argument('input', nargs=2, help='input directories')
        parser_copy_diff.add_argument('output', help='output directory')
        parser_copy_diff.set_defaults(func=self.copy_diff_command)

        parser_copy_intersect = subparsers.add_parser('copy-intersect', help='copy from first input to output if a match is present in second input (output = first ^ second)')
        parser_copy_intersect.add_argument('-I', '--include', action='append', choices=INPUT_FORMATS, default=[], help='only copy/compare the given formats')
        parser_copy_intersect.add_argument('-c', '--no-link', action='store_false', dest='try_link', help='always copy, never use hard links')
        parser_copy_intersect.add_argument('input', nargs=2, help='input directories')
        parser_copy_intersect.add_argument('output', help='output directory')
        parser_copy_intersect.set_defaults(func=self.copy_intersect_command)

        parser_transcode = subparsers.add_parser('transcode', help='transcode from inputs to output')
        parser_transcode.add_argument('-F', '--format', action='store', choices=TRANSCODE_FORMATS, default='mp3', help='output format to transcode to')
        parser_transcode.add_argument('-Q', '--quality', action='store', type=int, default=None, help='output quality (VBR for mp3, quality for ogg)')
        parser_transcode.add_argument('input', nargs='+', help='input directories')
        parser_transcode.add_argument('output', help='output directory')
        parser_transcode.set_defaults(func=self.transcode_command)

        parser_help = subparsers.add_parser('help', help='show help')
        parser_help.set_defaults(func=lambda args: parser.print_help())

        args = parser.parse_args(argv[1:])

        self.dry_run = args.dry_run
        self.quiet = args.quiet
        self.verbose = args.verbose

        args.func(args)

def main(argv=sys.argv):
    cli = MusicManagerCli()
    cli.main(argv)

if __name__ == '__main__':
    main()
