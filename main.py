import argparse
import re
import pathlib
import datetime as dt
import eyed3
from typing import List, Tuple
import msg_box
import difflib
import tkinter.filedialog as fd
import ftfy
import pandas as pd
import requests
import hashlib
import json
import requests_cache
import pylast
import pytz
import logging
import numpy as np
import sys

# logging.basicConfig(level=logging.DEBUG)

# Track element delimiter
delim_artist_mp3 = r' / '  # separates artists in the %ARTIST tag for mp3 tags
delim_mp3_separator = r' / '  # same as delim_artist_mp3, but more generally true as well.
delim_category = '\t'
delim_listens = r'///'  # separates individual listens

# Destination (preferred) datetime formatting strings
# Destination is YYYY-MM-dd_hh_mm, 24 hour clock
# %Y    Year with century as a decimal number
# %m    Month as a zero-padded decimal number
# %d    Day of the month as a decimal number [01,31]
# %H    Hour (24-hour clock) as a zero-padded decimal number
# %M    Minute as a decimal number [00,59]
# %S    Second as a zero-padded decimal number [00,59]
dt_fmt = r'%Y-%m-%d_%H-%M'

LOCAL_TIMEZONE_NAME = 'America/Chicago'

# LASTFM API AND SESSION SETUP
API_KEY_FILE = pathlib.Path(r'KEY_FILE.txt')
user_info_gen = (row for row in API_KEY_FILE.open(mode='r', encoding='utf-8'))
API_KEY = next(user_info_gen).strip()
API_SECRET = next(user_info_gen).strip()

API_ROOT_URL = r'http://ws.audioscrobbler.com/2.0'
API_AUTH_URL = r'http://www.last.fm/api/auth'

USER_AGENT = 'bedevere-test'
FORMAT = 'json'

HEADERS = {
	'user-agent': USER_AGENT,
}

USER_INFO = pathlib.Path(r'USER_INFO.txt')  # two line file containing username & password


def get_network(username: str, password_hash: str, cache_file: str = None) -> pylast.LastFMNetwork:
	network = pylast.LastFMNetwork(
		api_key=API_KEY,
		api_secret=API_SECRET,
		username=username,
		password_hash=password_hash,
	)

	if cache_file or True:      # temporarily enable caching
		network.enable_caching()    # (cache_file)

	network.enable_rate_limit()
	return network


def request_lastfm_library(network: pylast.LastFMNetwork):
	user_library = pylast.Library(
		user=network.username,
		network=network,
	)

	return user_library


def request_tracks_from_date_range(network: pylast.LastFMNetwork, time_from: dt.datetime = None,
                                   time_to: dt.datetime = None, limit: int = None):
	lastfm_user = network.get_user(network.username)

	# lastfm_user = network.get_user('Nohadon')
	# lastfm_user = network.get_user('oisailing')
	# lastfm_user = network.get_user('erAc103')

	time_from_timestamp = convert_local_datetime_to_unix_timestamp(time_from)
	time_to_timestamp = convert_local_datetime_to_unix_timestamp(time_to)

	print('range start:', time_from_timestamp)
	print('range end:', time_to_timestamp)


	date_range_tracks = lastfm_user.get_recent_tracks(
		limit=limit,
		cacheable=True,
		time_from=convert_local_datetime_to_unix_timestamp(time_from),
		time_to=convert_local_datetime_to_unix_timestamp(time_to)
	)

	return date_range_tracks


def convert_local_datetime_to_unix_timestamp(d: dt.datetime) -> int:
	if not d.tzinfo:
		timezone = pytz.timezone(LOCAL_TIMEZONE_NAME)
		d.replace(tzinfo=timezone)

	unix_timestamp = int(d.astimezone(pytz.timezone('utc')).timestamp())
	return unix_timestamp


def convert_timestamp_to_local_datetime(t: int) -> dt.datetime:
	timezone = pytz.timezone(LOCAL_TIMEZONE_NAME)
	d = dt.datetime.fromtimestamp(t, timezone)
	return d


def replace_with_last_day_of_month(d: dt.datetime) -> dt.datetime:
	while True:
		try:
			d = d.replace(day=d.day + 1)

		except ValueError:
			return d


def datetime_range(x: List[str]) -> Tuple[dt.datetime, dt.datetime]:
	re_cmd_input = re.compile(r'(\d{4})(-(\d{2}))?(-(\d{2}))?(_(\d{2}))?(-(\d{2}))?(-(\d{2}))?')

	try:
		start_datestring, end_datestring = x
		y0, _, m0, _, d0, _, H0, _, M0, _, S0 = re_cmd_input.match(start_datestring).groups()
		y0 = int(y0)
		m0 = int(m0) if m0 else 1
		d0 = int(d0) if d0 else 1
		H0 = int(H0) if H0 else 0
		M0 = int(M0) if M0 else 0
		S0 = int(S0) if S0 else 0
		start = dt.datetime(y0, m0, d0, H0, M0, S0)

		y1, _, m1, _, d1, _, H1, _, M1, _, S1 = re_cmd_input.match(end_datestring).groups()
		y1 = int(y1)
		m1 = int(m1) if m1 else 12
		# not d1
		H1 = int(H1) if H1 else 23
		M1 = int(M1) if M1 else 59
		S1 = int(S1) if S1 else 59

		if d1:
			d1 = int(d1)
			end = dt.datetime(y1, m1, d1, H1, M1, S1)

		else:
			end = replace_with_last_day_of_month(dt.datetime(y1, m1, 1, H1, M1, S1))

	except ValueError as E:

		try:
			datestring = x if type(x) == str else x[0]
			y, _, m, _, d, _, H, _, M, _, S = re_cmd_input.match(datestring).groups()
			y = int(y)

			if not m:
				start = dt.datetime(y, 1, 1, 0, 0, 0)
				end = dt.datetime(y, 12, 31, 23, 59, 59)

			elif not d:
				m = int(m)
				start = dt.datetime(y, m, 1, 0, 0, 0)
				end = replace_with_last_day_of_month(dt.datetime(y, m, 1, 23, 59, 59))

			else:
				m = int(m)
				d = int(d)
				start = dt.datetime(y, m, d, 0, 0, 0)
				end = dt.datetime(y, m, d, 23, 59, 59)

		except AttributeError as E:
			raise E

	except AttributeError as E:
		raise Exception('The datestring entered does not fit the format')

	return start, end


def is_audio_file(x: pathlib.Path) -> bool:
	return True if x.suffix == '.mp3' else False    # or x.suffix == '.flac' else False


def get_first_artist(a) -> str:  # (a: eyed3.mp3.Mp3AudioFile) -> str:
	return a.tag.artist.split(delim_mp3_separator)[0]


def load_library(music_library_dir: pathlib.Path) -> list:
	music_library_tracks = []

	artist_folders = [x for x in music_library_dir.iterdir() if x.is_dir()]
	artist_folders = list(artist_folders)

	for artist_folder in artist_folders:
		album_folders = [x for x in artist_folder.iterdir() if x.is_dir()]

		for album_folder in album_folders:
			album_tracks = [eyed3.load(x) for x in album_folder.iterdir() if is_audio_file(x)]

			for track in album_tracks:
				music_library_tracks.append(track)

	return music_library_tracks


def log_library(music_library_tracks: list, music_library_log_file: pathlib.Path):
	tag_data_columns = [
		'album',
		'album_artist',
		'artist',
		'title',
		'disc_num',
		'original_artist',
		'release_date',
		'title',
		'track_num',
	]
	info_data_columns = [
		'bit_rate',
		'time_secs',
	]

	library_data = []

	for track in music_library_tracks:
		track_dict = {'filepath': track.path}

		for dc in tag_data_columns:
			try:
				track_dict[dc] = track.tag.__getattribute__(dc)
			except AttributeError:
				track_dict[dc] = None

		for dc in info_data_columns:
			try:
				track_dict[dc] = track.info.__getattribute__(dc)
			except AttributeError:
				track_dict[dc] = None

		library_data.append(track_dict)

	df_lib_data = pd.DataFrame(library_data)
	df_lib_data.to_csv(path_or_buf=music_library_log_file,
	                   sep=delim_category,
	                   header=True,
	                   mode='w',
	                   encoding='utf-8',
	                   date_format=dt_fmt,
	                   )

	return df_lib_data


def load_from_csv(csv_filepath: pathlib.Path) -> pd.DataFrame:
	csv_df = pd.read_csv(
		filepath_or_buffer=csv_filepath,
		sep=delim_category,
		encoding='utf-8'
	)

	return csv_df


def equal_except_case(s1: str, s2: str) -> bool:
	return s1.lower() == s2.lower()


def search_for_lost_track(library_dir: pathlib.Path, lookup_tuple: Tuple[str, str, str],
                          local_artist_corrections: List[tuple] = None,
                          local_album_corrections: List[tuple] = None,
                          local_title_corrections: List[tuple] = None) -> Tuple[pathlib.Path, tuple, tuple, tuple]:
	artist, album, title = lookup_tuple
	expected_artist_folder = library_dir.joinpath(artist)
	track_file = None

	if expected_artist_folder.is_dir():
		re_album_folder = re.compile(''.join([r'^\[(\d{4})(-(\d{2}))?(-(\d{2}))?\] ', album]))

		potential_album_folders = list(
			filter(lambda x: re_album_folder.match(x.name), expected_artist_folder.iterdir()))

		if len(potential_album_folders) == 1 and potential_album_folders[0].is_dir():
			album_folder = potential_album_folders[0]

			re_track = re.compile(''.join([r'^((\d)-)?(\d{2}) ', title]))
			potential_tracks = list(filter(lambda x: re_track.match(x.name), [y for y in album_folder.iterdir() if
			                                                                  is_audio_file(y)]))

			if len(potential_tracks) == 1:
				track = potential_tracks[0]
				print(lookup_tuple, 'was somehow unable to be found but was rediscovered through the normal algorithm')

				if True:  # msg_box.Confirm().show(msg=''.join(['Confirm the track: ', str(track), '?'])):
					track_file = track

	# if not track_file:
	cutoff_bound = 0
	close_matches = 500

	artist_folder_names = [x.name for x in library_dir.iterdir() if x.is_dir()]
	potential_artist_matches = difflib.get_close_matches(artist, artist_folder_names, close_matches, cutoff_bound)

	artist_match_found = False
	artist_dir = None

	for artist_match in potential_artist_matches:
		if (artist, artist_match) in local_artist_corrections:
			artist_dir = library_dir.joinpath(artist_match)
			artist_correction = None
			artist_match_found = True
			break

	if not artist_match_found:
		print(artist, album, title)
		if equal_except_case(artist, potential_artist_matches[0]):
			artist_dir = library_dir.joinpath(potential_artist_matches[0])
			artist_correction = (artist, potential_artist_matches[0])

		elif len(potential_artist_matches) > 0 and msg_box.Confirm().show(
				msg=''.join(['Correct artist folder for ', artist, ': ', potential_artist_matches[0], '?'])):
			artist_dir = library_dir.joinpath(potential_artist_matches[0])
			artist_correction = (artist, potential_artist_matches[0])

		else:
			artist_dir = library_dir.joinpath(fd.askdirectory(initialdir=library_dir))
			artist_correction = (artist, artist_dir.stem)

	album_folders = [x.name for x in artist_dir.iterdir() if x.is_dir()]
	potential_album_matches = difflib.get_close_matches(album, album_folders, close_matches, cutoff_bound)

	album_match_found = False
	album_dir = None

	for album_match in potential_album_matches:
		if (album, album_match) in local_album_corrections:
			album_dir = artist_dir.joinpath(album_match)
			album_correction = None
			album_match_found = True
			break

	if not album_match_found:

		if equal_except_case(album, potential_album_matches[0]):
			album_dir = artist_dir.joinpath(potential_album_matches[0])
			album_correction = (album, potential_album_matches[0])

		elif len(potential_album_matches) > 0 and msg_box.Confirm().show(
				msg=''.join(['Correct album folder for ', album, ': ', potential_album_matches[0], '?'])):
			album_dir = artist_dir.joinpath(potential_album_matches[0])
			album_correction = (album, potential_album_matches[0])

		else:
			album_dir = artist_dir.joinpath(fd.askdirectory(initialdir=artist_dir))
			album_correction = (album, album_dir.stem)

	track_names = [x.name for x in album_dir.iterdir() if is_audio_file(x)]
	potential_title_matches = difflib.get_close_matches(title, track_names, close_matches, cutoff_bound)

	track_match_found = False
	track = None

	for title_match in potential_title_matches:
		if (title, title_match) in local_title_corrections:
			track = album_dir.joinpath(title_match)
			track_correction = None
			track_match_found = True
			break

	if not track_match_found:
		re_track_name_per_title = re.compile(''.join([r'^((\d)-)?(\d{2}) ', title]), re.IGNORECASE)

		if re_track_name_per_title.match(potential_title_matches[0]) or equal_except_case(title, potential_title_matches[0]):
			track = album_dir.joinpath(potential_title_matches[0])
			track_correction = (title, potential_title_matches[0])

		elif len(potential_title_matches) > 0 and msg_box.Confirm().show(
				msg=''.join(['Correct track for ', title, ': ', potential_title_matches[0], '?'])):
			track = album_dir.joinpath(potential_title_matches[0])
			track_correction = (title, potential_title_matches[0])

		else:
			track = album_dir.joinpath(fd.askopenfilename(initialdir=album_dir))
			track_correction = (title, track.stem)

	track_file = track

	return track_file, artist_correction, album_correction, track_correction


if __name__ == '__main__':

	parser = argparse.ArgumentParser(
		description='''Bedevere's scrobble data requester, here's how to use it.''',
		epilog='''Example: '''
	)
	parser.add_argument('-date-range', '-dr',
	                    type=str, nargs='+', metavar='D',
	                    help='''Provide a date or date range to track in YYYY[-MM][-DD][_hh][-mm][-ss] format. The range
	                    is inclusive and accounts for limited information.''')
	parser.add_argument('-library-dir',
	                    type=str, metavar='d', default=r'A:\music\M',
	                    help='The location of your music library on your machine.')
	parser.add_argument('-library-log',
	                    type=str, metavar='F', default=r'main-config\music_library.csv',
	                    help='The csv file where you want to store your music library information.')
	parser.add_argument('--rebuild-library-log',
	                    action='store_true',
	                    help="Add this flag to manually rebuild the library log and exit afterward."
	                    )
	parser.add_argument('-lost-and-found-log',
	                    type=str, metavar='F', default=r'A:\pyprojects\music\lastfm_stats\main-config\lost_and_found_log.csv',
	                    help='Where to store tracks in your library that are not automatically found from scrobble data')
	parser.add_argument('-ignore-list',
	                    type=str, metavar='F', default=r'main-config\ignore_list.csv',
	                    help='''The location of an ignore list file, which can automatically ignore files not in your 
	                    local library''')
	parser.add_argument('--clean-logs',
	                    action='store_true',
	                    help="Enable to remove duplicate lines in the log csvs, this currently causes problems with the"
	                         "logic, I should find a way to fix that of course."
	                    )
	# parser.add_argument('username',
	#                     type=str, default='BedevereTheWise',
	#                     help='The LastFM username to search.')
	# parser.add_argument('password',
	#                     type=str,
	#                     help='The password to the LastFM account username provided.')
	args = parser.parse_args()

	# try:
	# 	assert 0 < len(args.date_range) <= 2
	start_datetime, end_datetime = datetime_range(args.date_range)
	print('range start:', start_datetime)
	print('range end:', end_datetime)
	#
	# except AssertionError:
	# 	raise Exception('''Provide a date or date range to cover. If you provide limited information, like a year or a
    #     year and month, the entirety of that duration will be included''')

	try:
		library_dir = pathlib.Path(args.library_dir)
		assert library_dir.exists()

	except AssertionError:
		raise Exception('''The library directory you gave does not exist''')

	library_file = pathlib.Path(args.library_log)

	if args.rebuild_library_log or not library_file.exists():
		print('starting library load')
		library = load_library(library_dir)
		mus_lib_df = log_library(library, library_file)
		print('finished library load')
		sys.exit(0)

	else:
		mus_lib_df = load_from_csv(pathlib.Path(args.library_log))

	mus_lib_df['artist'] = [x.split(r' / ')[0] for x in mus_lib_df['artist']]
	mus_lib_df['play_count'] = 0
	mus_lib_df['time_played'] = 0

	lost_and_found_file = pathlib.Path(args.lost_and_found_log)

	if lost_and_found_already_existed := lost_and_found_file.exists():
		lost_and_found_df = load_from_csv(lost_and_found_file)

		if args.clean_logs:
			pass

	else:
		lost_and_found_df = pd.DataFrame()

	ignore_list_file = pathlib.Path(args.ignore_list)

	if ignore_list_already_existed := ignore_list_file.exists():
		ignore_list_df = load_from_csv(ignore_list_file)

	else:
		ignore_list_df = pd.DataFrame()

	lost_and_found_track_data = []
	ignore_list_data = []

	user_info_gen = (row for row in USER_INFO.open(mode='r', encoding='utf-8'))
	local_username = next(user_info_gen).strip()
	local_password = next(user_info_gen).strip()

	try:
		int(local_password, 16)
		local_password_hash = local_password

	except ValueError:
		local_password_hash = pylast.md5(local_password)
		del local_password

	cache_file = r'lastfm_cache'

	lastfm_network = get_network(
		username=local_username,
		password_hash=local_password_hash,
		# cache_file=cache_file,
	)

	# returns a list of pylast.PlayedTrack, each of which has a sub-attribute, pylastPlayedTrack.track which has most of
	# the useful information we're after.

	tracks = request_tracks_from_date_range(
		network=lastfm_network,
		time_from=start_datetime,
		time_to=end_datetime,
		limit=None
	)
	number_of_scrobbles = len(tracks)
	print('scrobble count:', number_of_scrobbles)

	listens_dict = {}
	session_artist_corrections = []
	session_album_corrections = []
	session_title_corrections = []

	for t in sorted(tracks, key=lambda tt: [str(tt.track.artist), str(tt.album), str(tt.track.title)]):
		artist = str(t.track.artist)
		album = str(t.album)
		title = str(t.track.title)
		utc_timestamp = int(t.timestamp)

		matching_rows = mus_lib_df.loc[(mus_lib_df['artist'] == artist) &
		                               (mus_lib_df['album'] == album) &
		                               (mus_lib_df['title'] == title)]

		try:
			assert len(matching_rows) == 1
			match_index = matching_rows.index.values[0]

		except (AssertionError, AttributeError) as E:

			try:
				if not lost_and_found_df.empty:
					matching_rows = lost_and_found_df.loc[(lost_and_found_df['artist'] == artist) &
					                                      (lost_and_found_df['album'] == album) &
					                                      (lost_and_found_df['title'] == title)]

				assert len(matching_rows) == 1
				filepath = matching_rows['filepath'].values[0]
				match_index = mus_lib_df.loc[mus_lib_df['filepath'] == filepath].index.values[0]

			except (AssertionError, AttributeError) as E:

				# check ignore list before wasting user input
				if not ignore_list_df.empty:
					if not ignore_list_df.loc[(ignore_list_df['artist'] == artist) &
					                          (ignore_list_df['album'] == album) &
					                          (ignore_list_df['title'] == title)].empty:
						continue

				try:
					assert album
					potential_track_filepath, artist_correction, album_correction, title_correction = search_for_lost_track(library_dir, (artist, album, title), session_artist_corrections, session_album_corrections, session_title_corrections)

				except Exception as E:
					print(artist, album, title, ' was not found, either on purpose or accidentally -- skipping this track and adding to the ignore list')
					ignore_list_data.append({'artist': artist, 'album': album, 'title': title})
					continue

				potential_track_filename = str(potential_track_filepath)

				requires_user_confirm = artist_correction or album_correction

				if requires_user_confirm:
					if msg_box.Confirm().show(msg=''.join(['Unable to find the track: \n',
				                                                                 '\n'.join([artist, album, title]),
				                                                                 '\n is this the right file:\n',
											                                     potential_track_filename]),
				                                                    options=('Yes', 'No, find it')):
						filepath_parts = potential_track_filepath.parts
						filepath = str(pathlib.Path(r'A:\music').joinpath(*filepath_parts[2:]))

						if artist_correction:
							session_artist_corrections.append(artist_correction)

						if album_correction:
							session_album_corrections.append(album_correction)

						if title_correction:
							session_title_corrections.append(title_correction)

					else:
						filename = fd.askopenfilename()
						filepath = pathlib.Path(filename)
						filepath_parts = filepath.parts
						filepath = str(pathlib.Path(r'A:\music').joinpath(*filepath_parts[2:]))

				else:
					filepath_parts = potential_track_filepath.parts
					filepath = str(pathlib.Path(r'A:\music').joinpath(*filepath_parts[2:]))

					if artist_correction:
						session_artist_corrections.append(artist_correction)

					if album_correction:
						session_album_corrections.append(album_correction)

					if title_correction:
						session_title_corrections.append(title_correction)

				track_dict = {
					'filepath': filepath,
					'album': album,
					'artist': artist,
					'title': title,
				}
				track_tup = (filepath, album, artist, title)

				lost_and_found_track_data.append(track_tup)
				match_index = mus_lib_df.loc[mus_lib_df['filepath'] == filepath].index.values[0]


		# now that we have matched the scrobble data to a matching file / pandas dataframe row, increment time stats
		try:
			assert match_index
		except AssertionError as exc:
			if not match_index == 0:
				continue


		mus_lib_df.loc[match_index, 'play_count'] += 1
		mus_lib_df.loc[match_index, 'time_played'] += mus_lib_df.loc[match_index, 'time_secs']

	# filter down to only tracks in the time range.
	listens_df = mus_lib_df.loc[mus_lib_df['play_count'] > 0]

	# artists (for now) are entirely unique
	# albums must be attached to an artist, there are several albums titled exactly the same
	# tracks must be attached to an artist and an album, plenty of examples of every ambiguous case (My Favorite Things)
	artist_list = list(set(listens_df['artist'].values))

	album_name_list = list(set(listens_df['album'].values))
	album_list = []

	for album_name in album_name_list:
		album_name_df = listens_df.loc[listens_df['album'] == album_name]

		for index in album_name_df.index:
			album_artist = album_name_df.loc[index, 'album_artist']
			album_tuple = (album_artist, album_name)
			album_list.append(album_tuple)

	try:
		album_list = sorted(list(set(album_list)))
	except TypeError:
		album_list = album_list

	title_name_list = list(set(listens_df['title'].values))
	title_list = []

	for title_name in title_name_list:
		title_name_df = listens_df.loc[listens_df['title'] == title_name]

		for index in title_name_df.index:
			title_artist = title_name_df.loc[index, 'artist']
			title_album = title_name_df.loc[index, 'album']
			title_tuple = (title_artist, title_album, title_name)
			title_list.append(title_tuple)

	try:
		title_list = sorted(list(set(title_list)))  # losing some unique track information, I don't care right now
	except TypeError:
		title_list = title_list

	dt_fmt_write = r'%Y-%m-%d_%H-%M-%S'
	out_dir = pathlib.Path.cwd().joinpath('--'.join(['output', dt.datetime.now().strftime(dt_fmt_write),
	                                                 start_datetime.strftime(dt_fmt_write),
	                                                 end_datetime.strftime(dt_fmt_write)]))
	out_dir.mkdir()

	title_stats_file = out_dir.joinpath(r'track_stats.csv')
	title_stats_df = pd.DataFrame()

	for artist, album, title in title_list:
		title_stats_df = title_stats_df.append(listens_df.loc[(listens_df['artist'] == artist) &
		                                                      (listens_df['album'] == album) &
		                                                      (listens_df['title'] == title)],
		                                       ignore_index=True)

	title_stats_df.to_csv(path_or_buf=title_stats_file,
	                      sep=delim_category,
	                      header=True,
	                      index=False,
	                      mode='w',
	                      encoding='utf-8',
	                      date_format=dt_fmt,
	                      )

	artist_stats_file = out_dir.joinpath(r'artist_stats.csv')
	artist_stats_df = pd.DataFrame(columns=['artist', 'play_count', 'time_played'])

	for artist in artist_list:
		artist_df = listens_df.loc[listens_df['artist'] == artist]
		artist_stats_df = artist_stats_df.append({'artist': artist,
		                                          'play_count': artist_df['play_count'].sum(),
		                                          'time_played': artist_df['time_played'].sum()
		                                          },
		                                         ignore_index=True
		                                         )

	artist_stats_df.to_csv(path_or_buf=artist_stats_file,
	                       sep=delim_category,
	                       header=True,
	                       index=False,
	                       mode='w',
	                       encoding='utf-8',
	                       date_format=dt_fmt,
	                       )

	album_stats_file = out_dir.joinpath(r'album_stats.csv')
	album_stats_df = pd.DataFrame(columns=['artist', 'album', 'play_count', 'time_played'])

	for artist, album in album_list:
		album_df = listens_df.loc[(listens_df['artist'] == artist) & (listens_df['album'] == album)]
		album_stats_df = album_stats_df.append({'artist': artist,
		                                        'album': album,
		                                        'play_count': album_df['play_count'].sum(),
		                                        'time_played': album_df['time_played'].sum()
		                                        },
		                                       ignore_index=True
		                                       )

	album_stats_df.to_csv(path_or_buf=album_stats_file,
	                      sep=delim_category,
	                      header=True,
	                      index=False,
	                      mode='w',
	                      encoding='utf-8',
	                      date_format=dt_fmt,
	                      )

	lost_and_found_track_data = list(set(lost_and_found_track_data))

	lost_and_found_track_dicts = []

	for filepath, album, artist, title in lost_and_found_track_data:
		lost_and_found_track_dicts.append({
			'filepath': filepath,
			'album': album,
			'artist': artist,
			'title': title,
		})

	if lost_and_found_track_dicts:
		df = pd.DataFrame(lost_and_found_track_dicts)

		while True:
			try:
				if lost_and_found_already_existed:
					header = False
					mode = 'a'
				else:
					header = True
					mode = 'w'

				df.to_csv(path_or_buf=lost_and_found_file,
				          sep=delim_category,
				          header=header,
				          mode=mode,
				          encoding='utf-8',
				          date_format=dt_fmt,
				          )
				break

			except PermissionError as E:
				print('this will only work in debug mode but close the file you dumbo')

	if ignore_list_data:
		df = pd.DataFrame(ignore_list_data)

		while True:

			try:
				if ignore_list_already_existed:
					header = False
					mode = 'a'

				else:
					header = True
					mode = 'w'

				df.to_csv(path_or_buf=ignore_list_file,
				          sep=delim_category,
				          header=header,
				          mode=mode,
				          encoding='utf-8',
				          date_format=dt_fmt,
				          )

				break

			except PermissionError as E:
				print('this will only work in debug mode but close the file you dumbo')
