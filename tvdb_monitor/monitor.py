import datetime
import smtplib
import sys
import os

import logbook
import tvdb_api
from tvdb_exceptions import tvdb_error, tvdb_shownotfound
import ujson

from tvdb_monitor.settings import LOG_FILE_PATH, JSON_FILE_PATH, GMAIL_USERNAME, GMAIL_PASSWORD, EMAILS_LIST, \
    SUBJECT, MESSAGE, STATUSES_BLACK_LIST
from tvdb_monitor.shows import SHOWS_LIST

NOT_FOUND_STATUS = 'not found'

logger = logbook.Logger('TVDBMonitor')


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


def check_shows(last_state):
    """
    Check all shows and create a map of episode updates.

    :param last_state: A map between each show and the last reported episode for it.
    :return: A map between each show and its new episodes since the last check.
    """
    new_episodes_map = dict()
    try:
        logger.info('Connecting to TVDB...')
        tv = tvdb_api.Tvdb()
        for show_name in SHOWS_LIST:
            show_name = show_name.lower()
            logger.info('Checking show: {}'.format(show_name))
            try:
                # Load show information.
                show = tv[show_name]
                status = show.data['status'].lower()
                last_season_number = sorted(show.keys())[-1]
                last_season = show[last_season_number]
                # Verify last season by checking the first episodes's air time.
                today = datetime.datetime.now()
                while last_season_number > 1 and (
                        not last_season[1].get('firstaired') or
                        datetime.datetime.strptime(last_season[1]['firstaired'], '%Y-%m-%d') > today):
                    last_season_number -= 1
                    last_season = show[last_season_number]
                last_episode_number = sorted(last_season.keys())[-1]
                last_episode = last_season[last_episode_number]
                # Verify last episode by checking its air time.
                while last_episode_number > 1 and (
                        not last_episode.get('firstaired') or
                        datetime.datetime.strptime(last_episode['firstaired'], '%Y-%m-%d') > today):
                    last_episode_number -= 1
                    last_episode = last_season[last_episode_number]
                # If we've never seen this show before, assume last state is the last episode.
                show_last_state = last_state.get(show_name)
                if show_last_state is None:
                    new_episodes_list = [{
                        'season': last_season_number,
                        'episode': last_episode_number,
                        'date': last_episode['firstaired']
                    }]
                else:
                    # Create the new episodes list (ordered chronologically).
                    new_episodes_list = []
                    season_last_state = show_last_state['season']
                    episode_last_state = show_last_state['episode']
                    # Check new episodes in last state season.
                    last_season = show[season_last_state]
                    for new_episode_number in range(episode_last_state + 1, last_episode_number + 1):
                        new_episodes_list.append({
                            'season': season_last_state,
                            'episode': new_episode_number,
                            'date': last_season[new_episode_number].get('firstaired')
                        })
                    # Check new seasons since last state.
                    for new_season_number in range(season_last_state + 1, last_season_number + 1):
                        new_season = show[new_season_number]
                        for new_episode_number in range(1, len(new_season.keys()) + 1):
                            new_episodes_list.append({
                                'season': new_season_number,
                                'episode': new_episode_number,
                                'date': new_season[new_episode_number].get('firstaired')
                            })
                # Update new episodes map.
                new_episodes_map[show_name] = {
                    'status': status,
                    'new_episodes': new_episodes_list
                }
            except tvdb_shownotfound:
                logger.error('Couldn\'t find show: {}. Skipping...'.format(show_name))
                new_episodes_map[show_name] = {
                    'status': NOT_FOUND_STATUS,
                    'new_episodes': []
                }
    except tvdb_error:
        logger.exception('Couldn\'t connect to TVDB')
    return new_episodes_map


def update_state(last_state, new_episodes_map, file_path):
    """
    Save the new JSON state file.

    :param last_state: A map between each show and the last reported episode for it.
    :param new_episodes_map: The new episodes map to extract current state from.
    :param file_path: The JSON file path.
    """
    logger.info('Updating state file: {}'.format(file_path))
    new_state = dict()
    for show_name, show_info in new_episodes_map.items():
        new_episodes_list = show_info.get('new_episodes')
        # If something changed.
        if new_episodes_list:
            last_episode = new_episodes_list[-1]
            new_state[show_name] = {
                'status': show_info['status'],
                'season': last_episode['season'],
                'episode': last_episode['episode'],
                'date': last_episode['date']
            }
        else:
            # Copy last state.
            new_state[show_name] = last_state[show_name]
    ujson.dump(new_state, open(file_path, 'w', encoding='UTF-8'))


def report(new_episodes_map):
    """
    Send E-Mail report about new episodes.

    :param new_episodes_map: The new episodes map.
    """
    logger.info('Creating E-Mail report...')
    statuses_black_list = [status.lower() for status in STATUSES_BLACK_LIST]
    # Create message text.
    new_episodes_text = ''
    for show_name in sorted(new_episodes_map.keys()):
        show_info = new_episodes_map[show_name]
        status = show_info['status']
        if status in statuses_black_list:
            logger.info('Show {} status is black-listed ({}). Skipping...'.format(show_name, status))
            continue
        episodes_list = show_info['new_episodes']
        if len(episodes_list) == 0:
            logger.info('No new episodes for show {}'.format(show_name))
            continue
        new_episodes_text += '{}:\r\n'.format(show_name)
        for episode in episodes_list:
            air_date = episode['date']
            if air_date:
                air_date = datetime.datetime.strptime(air_date, '%Y-%m-%d').strftime('%d.%m.%Y')
            new_episodes_text += '\tSeason {} - Episode {} ({})\r\n'.format(
                episode['season'], episode['episode'], air_date)
        new_episodes_text += '\r\n'
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


def main():
    """
    Scans TVDB and reports updates.
    """
    with logbook.NestedSetup(_get_log_handlers()).applicationbound():
        file_path = JSON_FILE_PATH or os.path.join(os.path.dirname(os.path.realpath(__file__)), 'last_state.json')
        last_state = load_last_state(file_path)
        new_episodes_map = check_shows(last_state)
        update_state(last_state, new_episodes_map, file_path)
        report(new_episodes_map)
        logger.info('All done!')


if __name__ == '__main__':
    main()
