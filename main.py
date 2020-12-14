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

requests_cache.install_cache()

# Track element delimiter
delim_artist_mp3 = r' / '   # separates artists in the %ARTIST tag for mp3 tags
delim_mp3_separator = r' / '    # same as delim_artist_mp3, but more generally true as well.
delim_category = r'‽'   # unlikely to appear, used for CSV separation "interrobang"
delim_listens = r'///'  # separates individual listens

# Destination (preferred) datetime formatting strings
# Destination is YYYY-MM-dd_hh_mm, 24 hour clock
# %Y    Year with century as a decimal number
# %m    Month as a zero-padded decimal number
# %d    Day of the month as a decimal number [01,31]
# %H    Hour (24-hour clock) as a zero-padded decimal number
# %M    Minute as a decimal number [00,59]
dt_fmt = r'%Y-%m-%d_%H-%M'

LOCAL_TIMEZONE_NAME = 'America/Chicago'

# LASTFM API AND SESSION SETUP
API_ROOT_URL = r'http://ws.audioscrobbler.com/2.0'
API_AUTH_URL = r'http://www.last.fm/api/auth'
API_KEY = r'foo'
API_SECRET = r'bar'

USER_AGENT = 'bedevere-test'
FORMAT = 'json'

HEADERS = {
	'user-agent': USER_AGENT,
}

USER_INFO = pathlib.Path(r'USER_INFO.txt')      # two line file containing username & password


def get_network(username: str, password_hash: str, cache_file: pathlib.Path = None) -> pylast.LastFMNetwork:

	network = pylast.LastFMNetwork(
		api_key=API_KEY,
		api_secret=API_SECRET,
		username=username,
		password_hash=password_hash,
	)

	print('test if caching is enabled by default -- is_caching_enabled call: ', network.is_caching_enabled())

	if cache_file:
		network.enable_caching(cache_file)

	network.enable_rate_limit()
	return network


def request_lastfm_library(network: pylast.LastFMNetwork):
	user_library = pylast.Library(
		user=network.username,
		network=network,
	)

	return user_library


def request_tracks_from_date_range(network: pylast.LastFMNetwork, time_from: dt.datetime = None,
                                   time_to: dt.datetime = None):
	lastfm_user = network.get_user(network.username)

	date_range_tracks = lastfm_user.get_recent_tracks(
		limit=10,
		cacheable=True,
		time_from=convert_local_datetime_to_unix_timestamp(time_from),
		time_to=convert_local_datetime_to_unix_timestamp(time_to)
	)

	return date_range_tracks


def get_data_from_request():
	return 'foo', 'bar', '_'


def convert_local_datetime_to_unix_timestamp(d: dt.datetime) -> int:
	if not d.tzinfo:
		timezone = pytz.timezone(LOCAL_TIMEZONE_NAME)
		d.replace(tzinfo=timezone)

	unix_timestamp = int(d.astimezone(pytz.timezone('utc')).timestamp())
	return unix_timestamp


def replace_with_last_day_of_month(d: dt.datetime) -> dt.datetime:
	while True:
		try:
			d = d.replace(day=d.day + 1)

		except ValueError:
			return d


def datetime_range(x: List[str]) -> Tuple[dt.datetime, dt.datetime]:
	re_cmd_input = re.compile(r'(\d{4})(-(\d{2}))?(-(\d{2}))?')

	try:
		start_datestring, end_datestring = x
		y0, _, m0, _, d0 = re_cmd_input.match(start_datestring).groups()
		y0 = int(y0)
		m0 = int(m0) if m0 else 1
		d0 = int(d0) if d0 else 1
		start = dt.datetime(y0, m0, d0, 0, 0)

		y1, _, m1, _, d1 = re_cmd_input.match(end_datestring).groups()
		y1 = int(y1)

		if not m1:
			end = dt.datetime(y1, 12, 31, 23, 59)

		elif m1 and not d1:
			m1 = int(m1)
			end = replace_with_last_day_of_month(dt.datetime(y1, m1, 1, 23, 59))

		else:
			m1 = int(m1)
			d1 = int(d1)
			end = dt.datetime(y1, m1, d1, 23, 59)

	except ValueError as E:

		try:
			datestring = x if type(x) == str else x[0]
			y, _, m, _, d = re_cmd_input.match(datestring).groups()
			y = int(y)

			if not m:
				start = dt.datetime(y, 1, 1, 0, 0)
				end = dt.datetime(y, 12, 31, 23, 59)

			elif m and not d:
				m = int(m)
				start = dt.datetime(y, m, 1, 0, 0)
				end = replace_with_last_day_of_month(dt.datetime(y, m, 1, 23, 59))

			else:
				m = int(m)
				d = int(d)
				start = dt.datetime(y, m, d, 0, 0)
				end = dt.datetime(y, m, d, 23, 59)

		except AttributeError as E:
			raise E

	except AttributeError as E:
		raise Exception('The datestring entered does not fit the format')

	return start, end


def is_audio_file(x: pathlib.Path) -> bool:
	return True if x.suffix == '.mp3' or x.suffix == '.flac' else False


def get_first_artist(a) -> str:     # (a: eyed3.mp3.Mp3AudioFile) -> str:
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

	library_data = {}
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

	for track in music_library_tracks:
		track_dict = {}

		for dc in tag_data_columns:
			track_dict[dc] = track.tag.__getattribute__(dc)

		for dc in info_data_columns:
			track_dict[dc] = track.info.__getattribute__(dc)

		library_data[track.path] = track_dict

	df = pd.DataFrame(library_data).T
	df.to_csv(path_or_buf=music_library_log_file,
	          sep=delim_category,
	          header=True,
	          index=True,
	          index_label='filepath',
	          mode='w',
	          encoding='utf-8',
	          date_format=dt_fmt,
	          )

	return df


def search_for_lost_track(library_dir: pathlib.Path, lookup_tuple: Tuple[str, str, str]) -> bool:
	artist, album, title = lookup_tuple
	expected_artist_folder = library_dir.joinpath(artist)
	track_file = None

	if expected_artist_folder.is_dir():
		re_album_folder = re.compile(''.join([r'^\[(\d{4})(-(\d{2}))?(-(\d{2}))?\] ', album]), re.IGNORECASE)

		potential_album_folders = list(filter(lambda x: re_album_folder.match(x.name), expected_artist_folder.iterdir()))

		if len(potential_album_folders) == 1 and potential_album_folders[0].is_dir():
			album_folder = potential_album_folders[0]

			re_track = re.compile(''.join([r'^((\d)-)?(\d{2}) ', title]), re.IGNORECASE)
			potential_tracks = list(filter(lambda x: re_track.match(x.name), [y for y in album_folder.iterdir() if
			                                                                  is_audio_file(y)]))

			if len(potential_tracks) == 1:
				track = potential_tracks[0]
				print(lookup_tuple, 'was somehow unable to be found but was rediscovered through the normal algorithm')

				if msg_box.Confirm().show(msg=''.join(['Confirm the track: ', str(track), '?'])):
					track_file = track

	if not track_file:
		cutoff_bound = 0
		close_matches = 1

		artist_folder_names = [x.name for x in library_dir.iterdir() if x.is_dir()]
		potential_artist_matches = difflib.get_close_matches(artist, artist_folder_names, close_matches, cutoff_bound)

		if len(potential_artist_matches) > 0 and msg_box.Confirm().show(
				msg=''.join(['Correct artist folder for ', artist, ': ', potential_artist_matches[0], '?'])):
			artist_dir = library_dir.joinpath(potential_artist_matches[0])

		else:
			artist_dir = library_dir.joinpath(fd.askdirectory(initialdir=library_dir))

		album_folder_names = [x.name for x in artist_dir.iterdir() if x.is_dir()]
		potential_album_matches = difflib.get_close_matches(album, album_folder_names, close_matches, cutoff_bound)

		if len(potential_album_matches) > 0 and msg_box.Confirm().show(
				msg=''.join(['Correct album folder for ', album, ': ', potential_album_matches[0], '?'])):
			album_dir = artist_dir.joinpath(potential_album_matches[0])

		else:
			album_dir = artist_dir.joinpath(fd.askdirectory(initialdir=artist_dir))

		track_names = [x.name for x in album_dir.iterdir() if is_audio_file(x)]
		potential_title_matches = difflib.get_close_matches(title, track_names, close_matches, cutoff_bound)

		if len(potential_title_matches) > 0 and msg_box.Confirm().show(
				msg=''.join(['Correct track for ', title, ': ', potential_title_matches[0], '?'])):
			track = album_dir.joinpath(potential_title_matches[0])

		else:
			track = album_dir.joinpath(fd.askopenfilename(initialdir=album_dir))

		track_file = track

	return track_file


if __name__ == '__main__':

	parser = argparse.ArgumentParser(
		description='''Bedevere's scrobble data requester, here's how to use it.''',
		epilog='''Example: '''
	)
	parser.add_argument('-date-range', '-dr',
	                    type=str, nargs='+', metavar='D',
	                    help='''Provide a date or date range to track in YYYY[-MM][-DD] format. The range is inclusive 
                        and accounts for limited information.''')
	parser.add_argument('-library-dir',
	                    type=str, metavar='d', default=r'A:\pyprojects\music\test_library_dir',
	                    help='The location of your music library on your machine.')
	parser.add_argument('-debug-log-library',
	                    type=str, metavar='F',
	                    help='Test the log_library() function and write it to file')
	# parser.add_argument('username',
	#                     type=str, default='BedevereTheWise',
	#                     help='The LastFM username to search.')
	# parser.add_argument('-debug-search-for-lost-track',
	#                     type=str, metavar='F', nargs=2,
	#                     help='Test the search_for_lost_track() method by reading scenarios from file')
	args = parser.parse_args()

	try:
		assert 0 < len(args.date_range) <= 2

	except AssertionError:
		raise Exception('''Provide a date or date range to cover. If you provide limited information, like a year or a 
        year and month, the entirety of that duration will be included''')

	try:
		library_dir = pathlib.Path(args.library_dir)
		assert library_dir.exists()

	except AssertionError:
		raise Exception('''The library directory you gave does not exist''')

	start_datetime, end_datetime = datetime_range(args.date_range)

	if args.debug_search_for_lost_track:

		try:
			lost_tracks_file = pathlib.Path.cwd().joinpath(args.debug_search_for_lost_track[0])
			found_tracks_file = pathlib.Path.cwd().joinpath(args.debug_search_for_lost_track[1])
			assert lost_tracks_file.exists()
			assert found_tracks_file.exists()

			found_tracks = {}
			new_found_tracks = {}

			with found_tracks_file.open(mode='r', encoding='utf-8') as f:
				for line in f:
					file, artist, album, title = tuple(map(lambda x: ftfy.fix_encoding(x), line.strip().split(delim_category)))
					found_tracks[(artist, album, title)] = file

			with lost_tracks_file.open('r', encoding='utf-8') as f:

				for line in f:
					artist, album, title = tuple(map(lambda x: ftfy.fix_encoding(x), line.strip().split(delim_category)))

					if (artist, album, title) not in found_tracks:
						track_file = search_for_lost_track(library_dir, (artist, album, title))
						new_found_tracks[(artist, album, title)] = str(track_file).strip()

			with found_tracks_file.open('a', encoding='utf-8') as f:

				for key, val in new_found_tracks.items():
					f.write(delim_category.join([*key, val]) + '\n')

		except AssertionError as E:
			raise Exception('The debug file you provided does not exist: ' + str(args.debug_search_for_lost_track))

	library = load_library(library_dir)
	write_file = pathlib.Path(args.debug_log_library)
	mus_lib_df = log_library(library, write_file)

	user_info_gen = (row for row in USER_INFO.open(mode='r', encoding='utf-8'))
	local_username = next(user_info_gen).strip()
	local_password_hash = pylast.md5(next(user_info_gen).strip())

	cache_file = pathlib.Path(r'lastfm_cache.txt')

	lastfm_network = get_network(
		username=local_username,
		password_hash=local_password_hash,
		cache_file=cache_file,
	)
	tracks = request_tracks_from_date_range(
		network=lastfm_network,
		time_from=start_datetime,
		time_to=end_datetime,
	)

	for t in tracks:
		# get artist, album, title data from t
		artist, album, title = get_data_from_request()      # currently foobar values
		matching_files = mus_lib_df.loc[(mus_lib_df['artist'] == artist) &
		                                (mus_lib_df['album'] == album) &
		                                (mus_lib_df['title'] == title)]

		try:
			assert len(matching_files) == 1
			# with scrobbles loaded and access to the local file it represents,
			# we can do more time and track based metrics

			# ex: sort top artists or albums by
			#   time listened
			# ex: sort top albums by
			#   number of times listened, normalized by album track length

		except AssertionError as E:
			raise E
