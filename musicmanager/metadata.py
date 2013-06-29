
import re

from mutagen.id3 import ID3, TIT2, TRCK, TPE1, TALB, TDRC, ID3TimeStamp
from mutagen.mp3 import MP3
from mutagen.flac import FLAC, FLACNoHeaderError

def __normalize_tags(tags):
    if tags.get('track'):
        tags['track'] = int(tags['track'].partition('/')[0])

    if tags.get('date'):
        date = tags['date']
        if len(date) > 4:
            match = re.search(r'\d{4}', date)
            if match:
                tags['date'] = match.group()

    for tag in tags:
        if isinstance(tags[tag], basestring):
            tags[tag] = tags[tag].strip()

    return tags


def __first_key(search_dict, *keys):
    for key in keys:
        if search_dict.get(key):
            return search_dict[key]
    return None

def read_id3(filename):
    audio = ID3(filename)

    tags = {
        'filename' : filename,
        'artist' : audio.get('TPE1'),
        'album' : audio.get('TALB'),
        'track' : audio.get('TRCK'),
        'title' : audio.get('TIT2'),
        'date' : __first_key(audio, 'TDRC', 'TYER', 'TDAT', 'TIME', 'TRDA')
    }

    # Cast all the mutagen tags to unicode
    for tag, value in tags.items():
        if value:
            tags[tag] = unicode(value)

    return __normalize_tags(tags)

def read_flac(filename):
    try:
        audio = FLAC(filename)
    except FLACNoHeaderError:
        return {}

    tags = {
        'filename' : filename,
        'artist' : audio.get('artist'),
        'album' : audio.get('album'),
        'track' : audio.get('tracknumber') or audio.get('track'),
        'title' : audio.get('title'),
        'date' : audio.get('date') or audio.get('year'),
    }

    # Mutagen returns lists for each tag so we have to pull out the actual string
    for tag in tags:
        if tags[tag]:
            tags[tag] = tags[tag][0]

    tags['channels'] = audio.info.channels

    return __normalize_tags(tags)

def write_id3(filename, tags):
    audio = MP3(filename)

    if audio.tags:
        raise Exception('File already has ID3 tags present')

    audio.add_tags()
    audio.tags.add(TPE1(3, tags['artist']))
    audio.tags.add(TALB(3, tags['album']))
    audio.tags.add(TIT2(3, tags['title']))

    if tags.get('track'):
        audio.tags.add(TRCK(0, unicode(tags['track'])))

    if tags.get('date'):
        audio.tags.add(TDRC(0, tags['date']))

    audio.save()
