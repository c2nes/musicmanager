#!/usr/bin/env python

import glob
import os
import os.path
import re
import shutil
import subprocess
import sys
import tempfile

from mutagen.id3 import ID3
from mutagen.flac import FLAC

# LAME VBR quality setting (0 is highest quality, 9 is smallest file)
QUALITY=1
VERBOSE=False

def error(*args):
    sys.stderr.write(''.join(map(str, args)) + '\n')

def exit(n=0):
    sys.exit(n)

def get_ext(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext.startswith('.'):
        return ext[1:]
    else:
        return ext

def find_files(directory, *exts):
    exts = [ext.lower() for ext in exts]
    for root, dirs, files in os.walk(directory):
        for f in files:
            if get_ext(f) in exts:
                yield unicode(os.path.join(root, f), 'utf8')

def get_output(command, *args):
    proc = subprocess.Popen([command] + list(args), bufsize=-1,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)

    stdout_data, stderr_data = proc.communicate()

    if proc.returncode != 0:
        raise Exception(stderr_data)

    return unicode(stdout_data, 'utf_8')

def tags_id3(filename):
    audio = ID3(filename)
    year_tags = ('TYER', 'TDAT', 'TDRC', 'TIME', 'TRDA')

    tags = {
        'filename' : filename,
        'artist' : audio.get('TPE1'),
        'album' : audio.get('TALB'),
        'track' : audio.get('TRCK'),
        'title' : audio.get('TIT2'),
        'date' : None
    }

    for year_tag in year_tags:
        year = audio.get(year_tag)

        if year:
            tags['date'] = year
            break

    # Cast all the mutagen tags to unicode
    for tag in tags:
        if tags[tag]:
            tags[tag] = unicode(tags[tag])

    return tags

def tags_metaflac(filename):
    audio = FLAC(filename)

    tags = {
        'filename' : filename,
        'artist' : audio.get('artist'),
        'album' : audio.get('album'),
        'track' : audio.get('tracknumber') or audio.get('track'),
        'title' : audio.get('title'),
        'date' : audio.get('date') or audio.get('year')
    }

    # Mutagen returns lists for each tag so we have to pull out the actual string
    for tag in tags:
        if tags[tag]:
            tags[tag] = tags[tag][0]

    return tags

def normalize_tags(tags):
    tags_copy = tags.copy()

    if tags_copy.get('track'):
        track = tags_copy['track']

        if '/' in track:
            track = track.partition('/')[0]

        tags_copy['track'] = int(track)

    if tags_copy.get('date'):
        date = tags_copy['date']
        if len(date) > 4:
            match = re.search(r'\d{4}', date)
            if match:
                tags_copy['date'] = match.group()

    return tags_copy

def generate_filename(tags, is_various):
    artist = 'Various Artists' if is_various else tags.get('artist').replace('/', '-')
    album = tags.get('album').replace('/', '-')
    title = tags.get('title').replace('/', '-')
    date = tags.get('date')
    track = tags.get('track')

    dir_name = os.path.join(artist, album)

    if date:
        dir_name = dir_name + ' [' + date + ']'

    if track:
        file_name = '%02d - %s.mp3' % (track, title)
    else:
        file_name = title + '.mp3'

    full_name = os.path.join(dir_name, file_name)

    # Remove some funky characters
    return re.sub(r'''['"?]''', '', full_name)

def maketemp(suffix=''):
    handle, filename = tempfile.mkstemp(suffix)

    # We just want the filename
    os.close(handle)

    return filename

def decode_flac(filename):
    try:
        decoded_filename = maketemp('.wav')
        get_output('flac', '--decode', '--silent', '-fo', decoded_filename, filename)
        return decoded_filename
    except:
        os.unlink(decoded_filename)
        raise

def encode_mp3(source_wav_filename, dest_filename, tags):
    args = ['--id3v2-only', '-V', str(QUALITY), '--quiet',
            '--tt', tags.get('title'),
            '--ta', tags.get('artist'),
            '--tl', tags.get('album')]

    if tags.get('date'):
        args.extend(['--ty', tags.get('date')])

    if tags.get('track'):
        args.extend(['--tn', str(tags.get('track'))])

    args.append(source_wav_filename)
    args.append(dest_filename)

    get_output('lame', *args)

def transcode_flac(source_filename, dest_filename, tags):
    decoded = decode_flac(source_filename)

    try:
        encode_mp3(decoded, dest_filename, tags)
    finally:
        os.unlink(decoded)

def copy(source_filename, dest_filename):
    """ Lazy copy. Tries creating a hard link before falling back to a proper copy """

    try:
        os.link(source_filename, dest_filename)
    except OSError:
        shutil.copy2(source_filename, dest_filename)

if len(sys.argv) != 3:
    error("Missing argument")
    error("usage: ", sys.argv[0], " <source dir> <destination dir>")
    exit(1)

source_dir, dest_dir = sys.argv[1:]

inputs = []

for source_file in find_files(source_dir, 'flac', 'mp3'):
    ext = get_ext(source_file)

    if ext == 'flac':
        tags = tags_metaflac(source_file)
    else:
        tags = tags_id3(source_file)

    if not (tags.get('artist') and tags.get('album') and tags.get('title')):
        error('Skipping ', source_file, ', not enough tags could be read: ', tags)
        continue

    tags = normalize_tags(tags)
    inputs.append((source_file, ext, tags))

by_directory_album = {}

for source_file, ext, tags in inputs:
    key = os.path.dirname(source_file) + ':' + tags['album']

    if key in by_directory_album:
        by_directory_album[key].add(tags['artist'])
    else:
        by_directory_album[key] = set([tags['artist']])

for key in by_directory_album:
    by_directory_album[key] = (len(by_directory_album[key]) > 1)

for source_file, ext, tags in inputs:
    is_various = by_directory_album[os.path.dirname(source_file) + ':' + tags['album']]
    dest_file = os.path.join(dest_dir, generate_filename(tags, is_various))

    if os.path.exists(dest_file):
        if VERBOSE:
            print 'Skipping %s, destination %s already exists' % (source_file, dest_file)
        continue

    old_dir = os.path.dirname(source_file)
    new_dir = os.path.dirname(dest_file)

    if not os.path.exists(new_dir):
        os.makedirs(new_dir)

    # Copy log files
    for log_file in glob.iglob(os.path.join(old_dir, '*.log')):
        copy(log_file, new_dir)

    # Write a file tracking the source location of the music
    sourced_from_source = os.path.join(old_dir, 'moved_from')
    sourced_from_dest = os.path.join(new_dir, 'moved_from')

    if not os.path.exists(sourced_from_dest):
        if os.path.exists(sourced_from_source):
            copy(sourced_from_source, sourced_from_dest)
        else:
            sourced_from = open(sourced_from_dest, 'w')
            sourced_from.write(old_dir.encode('utf_8'))
            sourced_from.close()

    try:
        if ext == 'flac':
            print 'Transcoding', dest_file, 'from', source_file
            transcode_flac(source_file, dest_file, tags)
        else:
            print 'Copying', dest_file, 'from', source_file
            copy(source_file, dest_file)
    except:
        if os.path.exists(dest_file):
            os.unlink(dest_file)
        raise
