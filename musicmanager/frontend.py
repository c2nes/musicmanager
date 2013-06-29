
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

# Lame VBR quality setting (0 is highest quality, 9 is smallest file)
QUALITY=1
VERBOSE=False

# Perform the following replacements on generated filename parts
FILENAME_REPLACE = [
    ('/', '-')
]

# Delete the following characters from generated filename parts
FILENAME_DELETE = '\'"?'

def error(*args):
    sys.stderr.write(''.join(map(str, args)) + '\n')

def info(*args):
    print ''.join(arg.encode('utf_8') if isinstance(arg, unicode) else str(arg) for arg in args)

def exit(n=0):
    sys.exit(n)

def get_ext(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext.startswith('.'):
        return ext[1:]
    else:
        return ext

def find_files(directories, *exts):
    exts = [ext.lower() for ext in exts]

    for directory in directories:
        for root, dirs, files in os.walk(directory):
            for f in files:
                if get_ext(f) in exts:
                    yield unicode(os.path.join(root, f), 'utf_8')

@contextlib.contextmanager
def file_cleanup(filename):
    try:
        yield
    except:
        if os.path.exists(filename):
            os.unlink(filename)
        raise

def sanitize_filename_part(part):
    if not part:
        return part

    for char_from, char_to in FILENAME_REPLACE:
        part = part.replace(char_from, char_to)
    return re.sub('[' + re.escape(FILENAME_DELETE) + ']', '', part)

def generate_filename(tags, is_various, ext='mp3'):
    artist = 'Various Artists' if is_various else sanitize_filename_part(tags.get('artist'))
    album = sanitize_filename_part(tags.get('album'))
    title = sanitize_filename_part(tags.get('title'))
    date = sanitize_filename_part(tags.get('date'))
    track = tags.get('track')

    dir_name = os.path.join(artist, album)

    if date:
        dir_name = dir_name + ' [' + date + ']'

    if track:
        file_name = '%02d - %s.%s' % (track, title, ext)
    else:
        file_name = title + '.' + ext

    full_name = os.path.join(dir_name, file_name)

    # Remove some funky characters
    return full_name

def copy(source_filename, dest_filename, try_lazy=True):
    """Lazy copy. Tries creating a hard link before falling back to a proper copy"""

    if try_lazy:
        try:
            os.link(source_filename, dest_filename)
            return
        except OSError:
            pass

    shutil.copy2(source_filename, dest_filename)

def list_logs(directory):
    for f in os.listdir(directory):
        full_path = os.path.join(directory, f)
        if os.path.isfile(full_path) and full_path.endswith('.log'):
            yield full_path

def target_directory_prep(old_dir, new_dir, dry_run):
    if not os.path.exists(new_dir) and not dry_run:
        os.makedirs(new_dir)

    # Copy log files
    if not dry_run:
        for log_file in list_logs(old_dir):
            copy(log_file, new_dir, False)

    # Write a file tracking the source location of the music
    sourced_from_source = os.path.join(old_dir, 'moved_from')
    sourced_from_dest = os.path.join(new_dir, 'moved_from')

    if not os.path.exists(sourced_from_dest) and not dry_run:
        if os.path.exists(sourced_from_source):
            copy(sourced_from_source, sourced_from_dest, False)
        else:
            sourced_from = open(sourced_from_dest, 'w')
            sourced_from.write(os.path.abspath(old_dir).encode('utf_8') + '\n')
            sourced_from.close()

def main(argv=sys.argv):
    parser = argparse.ArgumentParser(description='Manage your music library')
    parser.add_argument('-n', '--dry-run', action='store_true', help='dry run (do not write any files)')
    parser.add_argument('-f', '--flac-only', action='store_true', help='only find and process FLAC files')
    parser.add_argument('-T', '--no-transcode', action='store_true', help='copy/organize, but do not transcode')
    parser.add_argument('-c', '--copy-only', action='store_true', help='always copy, never use hard links')
    parser.add_argument('--force', action='store_true', help='overwrite existing destination files')
    parser.add_argument('--delete', action='store_true', help='remove existing destination files with corresponding input files')
    parser.add_argument('input', nargs='+', help='input directories')
    parser.add_argument('output', help='output directory')
    args = parser.parse_args(argv[1:])

    source_dirs, dest_dir = args.input, args.output

    input_exts = ('flac',) if args.flac_only else ('flac', 'mp3')

    inputs = []

    for source_file in find_files(source_dirs, *input_exts):
        ext = get_ext(source_file)

        if ext == 'flac':
            tags = metadata.read_flac(source_file)
        else:
            tags = metadata.read_id3(source_file)

        if not (tags.get('artist') and tags.get('album') and tags.get('title')):
            error('Skipping ', source_file, ', not enough tags could be read: ', tags)
            continue

        inputs.append((source_file, ext, tags))

    by_directory_album = {}

    for source_file, ext, tags in inputs:
        key = (tags.get('date') or '0000') + ':' + tags['album']

        if key in by_directory_album:
            by_directory_album[key].add(tags['artist'])
        else:
            by_directory_album[key] = set([tags['artist']])

    for key in by_directory_album:
        by_directory_album[key] = (len(by_directory_album[key]) > 1)

    for source_file, source_ext, tags in inputs:
        is_various = by_directory_album[(tags.get('date') or '0000') + ':' + tags['album']]

        dest_ext = source_ext if args.no_transcode or tags.get('channels', 2) > 2 else 'mp3'
        dest_file = os.path.join(dest_dir, generate_filename(tags, is_various, dest_ext))

        old_dir = os.path.dirname(source_file)
        new_dir = os.path.dirname(dest_file)

        # If we're running in delete mode, remove the target file if it exists
        if args.delete:
            if os.path.exists(dest_file):
                info('Deleting ', dest_file)
                if not args.dry_run:
                    os.unlink(dest_file)
            elif VERBOSE:
                info('Skipping ', source_file, ', target file does not exist')
            continue

        # Remove existing targets with --force, otherwise skip
        if os.path.exists(dest_file):
            if args.force:
                os.unlink(dest_file)
            else:
                if VERBOSE:
                    info('Skipping %s, destination %s already exists' % (source_file, dest_file))
                continue

        # Create target directory and copy over metadata
        target_directory_prep(old_dir, new_dir, args.dry_run)

        with file_cleanup(dest_file):
            if source_ext == 'flac' and dest_ext == 'mp3':
                info('Transcoding ', dest_file, ' from ', source_file)
                if not args.dry_run:
                    transcode.flac_to_mp3(source_file, dest_file, quality=QUALITY)
                    metadata.write_id3(dest_file, tags)
            else:
                info('Copying ', dest_file, ' from ', source_file)
                if not args.dry_run:
                    copy(source_file, dest_file, not args.copy_only)
