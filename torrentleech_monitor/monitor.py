import datetime
import smtplib
import sys
import os
import shutil

from bs4 import BeautifulSoup
from guessit import guessit
import logbook
import tvdb_api
import requests
import ujson

from torrentleech_monitor.settings import LOG_FILE_PATH, JSON_FILE_PATH, GMAIL_USERNAME, GMAIL_PASSWORD, EMAILS_LIST, \
    SUBJECT, MESSAGE, STATUSES_BLACK_LIST, SHOULD_SEND_REPORT, SHOULD_DOWNLOAD_720_TORRENTS, \
    SHOULD_DOWNLOAD_1080_TORRENTS, TORRENTLEECH_USERNAME, TORRENTLEECH_PASSWORD, TORRENTS_DIRECTORY, \
    MAXIMUM_TORRENT_DAYS, MINIMUM_FREE_SPACE, SORT_BY_SEEDERS
from torrentleech_monitor.shows import SHOWS_LIST

NOT_FOUND_STATUS = 'not found'
TORRENTLEECH_BASE_URL = 'https://www.torrentleech.org'
QUALITIES_LIST = ['720p', '1080p']

logger = logbook.Logger('TorrentleechMonitor')


def _get_log_handlers():
    """
    Initializes all relevant log handlers.

    :return: A list of log handlers.
    """
    handlers = [
        logbook.NullHandler(),
        logbook.StreamHandler(sys.stdout, level=logbook.INFO, bubble=True),
    ]
    if LOG_FILE_PATH:
        handlers.append(logbook.RotatingFileHandler(
            LOG_FILE_PATH, level=logbook.DEBUG, backup_count=1, max_size=5 * 1024 * 1024, bubble=True))
    return handlers


def load_last_state(file_path):
    """
    Load last state from local JSON file.

    :param file_path: The JSON file path.
    :return: The map between show names and their last season and episode.
    """
    logger.info('Loading last state from: {}'.format(file_path))
    if not os.path.isfile(file_path):
        logger.info('File doesn\'t exist! Starting from scratch...')
        return dict()
    return ujson.load(open(file_path, 'r', encoding='UTF-8'))


def uglify_show_name(show_name):
    """
    Returns an uglified string for the given show name.
    """
    return show_name.lower().replace('\'', '').replace('.', ' ').replace('  ', ' ').replace('!', '').\
        replace(':', ' ').strip()


def sort_by_seeders(download_links, seeders):
    return [l[0] for l in sorted(list(zip(download_links, seeders)), reverse=True, key=lambda x: x[1])]


def _get_torrents(show_name, season_number, episode_number, session):
    """
    Search Torrentleech for relevant torrents for the given episode.

    :param show_name: The show to search for.
    :param season_number: The season to search for.
    :param episode_number: The episode to search for.
    :param session: The current Torrentleech session.
    :return: A map between each quality and its details (size and URL).
    """
    torrents_map = dict()
    logger.info('Searching torrents for {} - s{:02d}e{:02d}'.format(show_name, season_number, episode_number))
    # slugify a bit - URLs and guessit get sensitive about this stuff.
    show_name = uglify_show_name(show_name)
    for quality in QUALITIES_LIST:
        search_url = TORRENTLEECH_BASE_URL + \
                     '/torrents/browse/index/query/{}+s{:02d}e{:02d}+{}/facets/category%253ATV'.format(
                        show_name.replace(' ', '%20'), season_number, episode_number, quality)
        response = session.get(search_url)
        if response.status_code == 200:
            # Scrape that shit!
            parsed_response = BeautifulSoup(response.content, 'html.parser')
            table = parsed_response.find(id='torrenttable')
            if table:
                results_list = [t.find('a')['href'] for t in table.find_all('td', 'quickdownload')]
                sizes_list = [t.string for t in table.find_all('td') if t.string and
                              ('GB' in t.string or 'MB' in t.string)]
                seeders_list = [int(t.get_text()) for t in table.find_all('td', 'seeders')]
                if SORT_BY_SEEDERS:
                    results_list = sort_by_seeders(results_list, seeders_list)
                for index, result in enumerate(results_list):
                    file_name = result.split('/')[-1]
                    logger.debug('Found possible torrent: {}'.format(file_name))
                    # Verify with guessit.
                    guess = guessit(file_name)
                    if uglify_show_name(guess.get('title')) == show_name and guess.get('season') == season_number and \
                            guess.get('episode') == episode_number and guess.get('screen_size') == quality:
                        # Calculate file size.
                        file_size_parts = sizes_list[index].split(' ')
                        file_size = float(file_size_parts[0]) * (1 if file_size_parts[1] == 'MB' else 1000)
                        # Add to map and move on to next quality.
                        torrents_map[quality] = {
                            'size': file_size,
                            'url': result,
                            'downloaded': False
                        }
                        logger.info('Found torrent for {} quality (size: {})'.format(quality, file_size))
                        break
                    else:
                        logger.info('Guess info didn\'t match: {}'.format(guess))
            else:
                logger.info('Found nothing for URL: {}'.format(search_url))
    return torrents_map


def _get_last_available_episode(show, show_name, torrentleech_show_name, show_last_state, session):
    """
    Find the latest relevant (aired and available) episode for the given show.

    :param show: The TVDB show object.
    :param show_name: The show name.
    :param torrentleech_show_name: The show name in Torrentleech.
    :param show_last_state: The last state JSON saved for the given show.
    :param session: The current Torrentleech session.
    :return: A JSON with the following details: season_number, episode_number, air_date and torrent_urls,
    or None, if the show is not yet available.
    """
    last_state_episode = None
    if show_last_state:
        last_state_episode = show_last_state['last_episode_info']
    today = datetime.datetime.now()
    # Get last episode information.
    last_season_number = sorted(show.keys())[-1]
    last_season = show[last_season_number]
    last_episode_number = sorted(last_season.keys())[-1]
    # If nothing has changed since the last time we checked, return the same JSON.
    if last_state_episode and last_state_episode['season'] == last_season_number and \
            last_state_episode['episode'] == last_episode_number:
        logger.info('{} - no change since last state'.format(show_name))
        return last_state_episode
    # Try to find the newest available episode.
    torrents_map = dict()
    last_episode = last_season[last_episode_number]
    last_episode_air_time = last_episode['firstaired']
    if last_episode_air_time:
        last_episode_air_time = datetime.datetime.strptime(last_episode_air_time, '%Y-%m-%d')
        if last_episode_air_time <= today:
            torrents_map = _get_torrents(torrentleech_show_name, last_season_number, last_episode_number, session)
    # Go back until finding the last aired episode.
    while not last_episode_air_time or last_episode_air_time > today or len(torrents_map) == 0:
        last_episode_number -= 1
        # If reached beginning of season, go back one season and start from its last episode.
        if last_episode_number <= 0:
            last_season_number -= 1
            # If no season was yet aired, stop.
            if last_season_number == 0:
                return None
            last_season = show[last_season_number]
            last_episode_number = sorted(last_season.keys())[-1]
        # If nothing has changed since the last time we checked, return the same JSON.
        if last_state_episode and last_state_episode['season'] == last_season_number and \
                last_state_episode['episode'] == last_episode_number:
            logger.info('{} - no change since last state'.format(show_name))
            return last_state_episode
        # Try to find the newest available episode.
        try:
            last_episode = last_season[last_episode_number]
            last_episode_air_time = last_episode['firstaired']
            if last_episode_air_time:
                last_episode_air_time = datetime.datetime.strptime(last_episode_air_time, '%Y-%m-%d')
                if last_episode_air_time <= today:
                    torrents_map = _get_torrents(torrentleech_show_name, last_season_number, last_episode_number,
                                                 session)
        except tvdb_api.tvdb_episodenotfound:
            last_episode_air_time = None
            logger.info('Episode {} in season {} not found. Skipping...'.format(
                last_episode_number, last_season_number))
    # Return the new state JSON for the given show.
    return {
        'season': last_season_number,
        'episode': last_episode_number,
        'air_date': last_episode_air_time.strftime('%Y-%m-%d'),
        'torrents': torrents_map
    }


def check_shows(last_state, session):
    """
    Check all shows and create a map of new available episodes.

    :param last_state: A map between each show and the last reported episode for it.
    :param session: The current Torrentleech session.
    :return: A map between each show and its last aired episode (and season), which is available for download.
    """
    statuses_black_list = [status.lower() for status in STATUSES_BLACK_LIST]
    last_episodes_map = dict()
    try:
        logger.info('Connecting to TVDB...')
        tv = tvdb_api.Tvdb()
        for show_name in SHOWS_LIST:
            if isinstance(show_name, tuple):
                show_name, torrentleech_show_name = [n.lower() for n in show_name]
            else:
                show_name = show_name.lower()
                torrentleech_show_name = show_name
            logger.info('Checking show: {}'.format(show_name))
            try:
                # Load show information.
                show = tv[show_name]
                status = show.data['status'].lower()
                show_last_state = last_state.get(show_name)
                # No need to check anything if status is black-listed.
                if status not in statuses_black_list:
                    last_episode_info = _get_last_available_episode(show, show_name, torrentleech_show_name,
                                                                    show_last_state, session)
                    if last_episode_info:
                        logger.info('{} last available episode is: S{:02d}E{:02d} (aired: {})'.format(
                            show_name, last_episode_info['season'], last_episode_info['episode'],
                            last_episode_info['air_date']))
                    else:
                        logger.info('No available episodes yet for {}...'.format(show_name))
                else:
                    logger.info('{} status is black-listed ({}). Skipping...'.format(show_name, status))
                    continue
                # Update last episodes map.
                last_episodes_map[show_name] = {
                    'status': status,
                    'last_episode_info': last_episode_info
                }
            except tvdb_api.tvdb_shownotfound:
                logger.error('Couldn\'t find show: {}. Skipping...'.format(show_name))
                last_episodes_map[show_name] = {
                    'status': NOT_FOUND_STATUS,
                    'last_episode_info': None
                }
    except tvdb_api.tvdb_error:
        logger.exception('Couldn\'t connect to TVDB')
    return last_episodes_map


def report(last_episodes_map):
    """
    Send E-Mail report about new episodes.

    :param last_episodes_map: The last episodes map.
    """
    logger.info('Creating E-Mail report...')
    # Create message text.
    new_episodes_text = ''
    for show_name in sorted(last_episodes_map.keys()):
        is_new = False
        show_info = last_episodes_map[show_name]
        episode_info = show_info['last_episode_info']
        if episode_info is not None:
            torrents_map = episode_info.get('torrents')
            if torrents_map:
                for quality, torrent_info in torrents_map.items():
                    if not torrent_info.get('downloaded'):
                        # Add show header line.
                        if not is_new:
                            is_new = True
                            new_episodes_text += '{}:\r\n'.format(show_name)
                        # Add episode line.
                        air_date = episode_info['air_date']
                        if air_date:
                            air_date = datetime.datetime.strptime(air_date, '%Y-%m-%d').strftime('%d.%m.%Y')
                        new_episodes_text += '\tSeason {} - Episode {}, {} ({})\r\n'.format(
                            episode_info['season'], episode_info['episode'], quality, air_date)
                if is_new:
                    new_episodes_text += '\r\n'
        if not is_new:
            logger.info('No new episodes for show {}'.format(show_name))
    # Stop if there's nothing to report.
    if not new_episodes_text:
        logger.info('Nothing to report - No mail was sent.')
        return
    # Connect to the GMail server.
    server = None
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.ehlo()
        server.starttls()
        server.login(GMAIL_USERNAME, GMAIL_PASSWORD)
        for to_address in EMAILS_LIST:
            message = '\r\n'.join([
                'From: {}'.format(GMAIL_USERNAME),
                'To: {}'.format(to_address),
                'Subject: {}'.format(SUBJECT),
                '',
                MESSAGE,
                '',
                new_episodes_text
            ])
            server.sendmail(GMAIL_USERNAME, to_address, message)
            logger.info('Report sent to: {}'.format(to_address))
    except Exception:
        logger.exception('Something went wrong when connecting to the GMail server.')
    finally:
        if server is not None:
            server.close()


def download(last_episodes_map, session):
    """
    Download new episode torrents.

    :param last_episodes_map: The last episodes map.
    :param session: The current Torrentleech session.
    """
    logger.info('Searching for new torrents to download...')
    now = datetime.datetime.now()
    qualities_list = []
    if SHOULD_DOWNLOAD_720_TORRENTS:
        qualities_list.append('720p')
    if SHOULD_DOWNLOAD_1080_TORRENTS:
        qualities_list.append('1080p')
    if len(qualities_list) == 0:
        return
    for show_name, show_info in last_episodes_map.items():
        episode_info = show_info['last_episode_info']
        if episode_info is not None:
            logger.info('Checking show: {} (Season - {}, Episode - {}, Date - {})'.format(
                show_name, episode_info['season'], episode_info['episode'], episode_info['air_date']))
            torrents_map = episode_info.get('torrents')
            if torrents_map:
                for quality in qualities_list:
                    torrent_info = torrents_map.get(quality)
                    if torrent_info is not None:
                        if torrent_info['downloaded']:
                            logger.info('Torrent already downloaded for quality {}'.format(quality))
                        # If episode is still relevant (aired before less than MAXIMUM_TORRENT_DAYS).
                        elif (now - datetime.datetime.strptime(episode_info['air_date'], '%Y-%m-%d')).days <= \
                                MAXIMUM_TORRENT_DAYS:
                            # Check free space.
                            free_space = shutil.disk_usage(TORRENTS_DIRECTORY).free / 1000 / 1000 - \
                                         MINIMUM_FREE_SPACE
                            file_size = torrent_info['size']
                            logger.debug('File size: {}. Free space: {}'.format(file_size, free_space))
                            if file_size >= free_space:
                                logger.info('Not enough free space ({}). Stopping!'.format(free_space))
                            else:
                                # Download it!
                                url = torrent_info['url']
                                torrent_response = session.get(url)
                                if torrent_response.status_code == 200 and torrent_response.content:
                                    # Success! Save the new torrent file and update the state.
                                    file_name = url.split(TORRENTLEECH_BASE_URL)[1].split('/')[-1]
                                    logger.info('Found torrent! File name: {}'.format(file_name))
                                    result_path = os.path.join(TORRENTS_DIRECTORY, file_name + '.torrent')
                                    open(result_path, 'wb').write(torrent_response.content)
                                    torrent_info['downloaded'] = True
                        else:
                            logger.info('Relevant time for episode ({}) has already passed. '
                                        'Marking as downloaded...'.format(quality))
                            torrent_info['downloaded'] = True


def main():
    """
    Scans TVDB and downloads new episodes from Torrentleech.
    """
    with logbook.NestedSetup(_get_log_handlers()).applicationbound():
        file_path = JSON_FILE_PATH or os.path.join(os.path.dirname(os.path.realpath(__file__)), 'last_state.json')
        last_state = load_last_state(file_path)
        # Login to TorrentLeech.
        with requests.session() as session:
            session.post(TORRENTLEECH_BASE_URL + '/user/account/login/', data={
                'username': TORRENTLEECH_USERNAME,
                'password': TORRENTLEECH_PASSWORD,
                'remember_me': 'on',
                'login': 'submit'
            })
            last_episodes_map = check_shows(last_state, session)
            if SHOULD_SEND_REPORT:
                report(last_episodes_map)
            if SHOULD_DOWNLOAD_720_TORRENTS or SHOULD_DOWNLOAD_1080_TORRENTS:
                download(last_episodes_map, session)
        # Update state file.
        ujson.dump(last_episodes_map, open(file_path, 'w', encoding='UTF-8'))
        logger.info('All done!')


if __name__ == '__main__':
    main()
