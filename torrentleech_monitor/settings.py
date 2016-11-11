import os

# E-Mail settings.

# GMail account to send from.
GMAIL_USERNAME = 'myuser@gmail.com'
GMAIL_PASSWORD = 'mypassword'
# Add all relevant E-Mail addresses to this list.
EMAILS_LIST = ['example@email.com']
# The update message subject.
SUBJECT = 'Your daily TV update!'
# The update message intro.
MESSAGE = 'Hi,\r\nYour daily TV update is here.\r\nEnjoy!'

# TorrentLeech settings.

# TorrentLeech account details to download with.
TORRENTLEECH_USERNAME = 'username'
TORRENTLEECH_PASSWORD = 'password'

# General settings.

# If True, E-Mail reports will be sent.
SHOULD_SEND_REPORT = True
# If True, new episode torrents will be downloaded from TorrentLeech.
SHOULD_DOWNLOAD_720_TORRENTS = True
SHOULD_DOWNLOAD_1080_TORRENTS = True
# Torrents for episodes older than this days number will not be downloaded.
MAXIMUM_TORRENT_DAYS = 2
# Minimal free space we should keep (in MBs).
MINIMUM_FREE_SPACE = 3 * 1024
# The directory to save downloaded torrent files in.
TORRENTS_DIRECTORY = r'C:\Temp\Torrents' if os.name == 'nt' else '/tmp/torrents'
# Skip shows with these statuses.
STATUSES_BLACK_LIST = ['ended']
# Log file path. If None, no log file will be created.
LOG_FILE_PATH = None
# JSON file path. If None, JSON will be created next to the script file.
JSON_FILE_PATH = None
