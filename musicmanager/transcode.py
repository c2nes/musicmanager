
from subprocess import Popen, PIPE

def flac_to_mp3(source_filename, dest_filename, quality=1):
    flac_proc = Popen(['flac', '--stdout', '--decode', '--silent', source_filename], stdout=PIPE)
    lame_proc = Popen(['lame', '--quiet', '-V', str(quality), '-', dest_filename], stdin=flac_proc.stdout)

    flac_proc.stdout.close()

    if lame_proc.wait() != 0:
        raise Exception('Process exited with non-zero status (%d)' % (lame_proc.returncode,))

def flac_to_ogg(source_filename, dest_filename, quality=6):
    oggenc_proc = Popen(['oggenc', '-q', str(quality), '--quiet', source_filename, '-o', dest_filename])

    if oggenc_proc.wait() != 0:
        raise Exception('Process exited with non-zero status (%d)' % (oggenc_proc.returncode,))
