#!/usr/bin/env python

import glob
import os
import os.path
import re
import shutil
import subprocess
import sys
import tempfile

from mutagen.id3 import ID3, TIT2, TRCK, TPE1, TALB, TDRC, ID3TimeStamp
from mutagen.mp3 import MP3
from mutagen.flac import FLAC

# Lame VBR quality setting (0 is highest quality, 9 is smallest file)
QUALITY=1
VERBOSE=False

# Perform the following replacements on generated filename parts
FILENAME_REPLACE = (
    ('/', '-')
)

# Delete the following characters from generated filename parts
FILENAME_DELETE = '\'"?'

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
    for tag, value in tags.items():
        if value:
            tags[tag] = unicode(value)

    return tags

def tags_flac(filename):
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

def write_tags(filename, tags):
    audio = MP3(filename)
    audio.add_tags()

    audio.tags.add(TPE1(3, tags['artist']))
    audio.tags.add(TALB(3, tags['album']))
    audio.tags.add(TIT2(3, tags['title']))

    if tags.get('track'):
        audio.tags.add(TRCK(0, unicode(tags['track'])))

    if tags.get('date'):
        audio.tags.add(TDRC(0, tags['date']))

    audio.save()

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

    for tag in tags_copy:
        if isinstance(tags_copy[tag], basestring):
            tags_copy[tag] = tags_copy[tag].strip()

    return tags_copy

def sanitize_filename_part(part):
    for char_from, char_to in FILENAME_REPLACE:
        part = part.replace(char_from, char_to)
    return re.sub('[' + re.escape(FILENAME_DELETE) + ']', '', part)

def generate_filename(tags, is_various):
    artist = 'Various Artists' if is_various else sanitize_filename_part(tags.get('artist'))
    album = sanitize_filename_part(tags.get('album'))
    title = sanitize_filename_part(tags.get('title'))
    date = sanitize_filename_part(tags.get('date'))
    track = sanitize_filename_part(tags.get('track'))

    dir_name = os.path.join(artist, album)

    if date:
        dir_name = dir_name + ' [' + date + ']'

    if track:
        file_name = '%02d - %s.mp3' % (track, title)
    else:
        file_name = title + '.mp3'

    full_name = os.path.join(dir_name, file_name)

    # Remove some funky characters
    return full_name

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

def encode_mp3(source_wav_filename, dest_filename):
    get_output('lame', '-V', str(QUALITY), '--quiet', source_wav_filename, dest_filename)

def transcode_flac(source_filename, dest_filename):
    decoded = decode_flac(source_filename)

    try:
        encode_mp3(decoded, dest_filename)
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
        tags = tags_flac(source_file)
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
            transcode_flac(source_file, dest_file)
            write_tags(dest_file, tags)
        else:
            print 'Copying', dest_file, 'from', source_file
            copy(source_file, dest_file)
    except:
        if os.path.exists(dest_file):
            os.unlink(dest_file)
        raise
