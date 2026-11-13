"""Spotify actions use fake lookup, AppleScript, and accessibility layers only."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import atticus


class SpotifyTests(unittest.TestCase):
    def test_lookup_prefers_cached_playlist_and_falls_back_to_web(self):
        cached = ('spotify:playlist:cached', 'Road trip')
        with patch.object(atticus, 'playlist', return_value=cached), patch.object(atticus, 'get') as get:
            self.assertEqual(atticus.spotify_item('road trip'), cached)
            get.assert_not_called()

        track = 'A' * 22
        page = f'https://open.spotify.com/track/{track}'
        with patch.object(atticus, 'playlist', return_value=None), \
             patch.object(atticus, 'get', side_effect=[page, json.dumps({'title': 'Fixture song'})]):
            self.assertEqual(atticus.spotify_item('fixture song'), (f'spotify:track:{track}', 'Fixture song'))

    def test_real_ddg_result_title_needs_no_oembed(self):
        page = Path(__file__).with_name('fixtures').joinpath('spotify-ddg.html').read_text()
        with patch.object(atticus, 'playlist', return_value=None), \
             patch.object(atticus, 'get', return_value=page) as get:
            uri, title = atticus.spotify_item('piano sonatas')
        self.assertTrue(uri.startswith('spotify:playlist:'))
        self.assertIn('Piano Sonatas', title)
        self.assertEqual(get.call_count, 1)
        self.assertIn('html.duckduckgo.com', get.call_args.args[0])

    def test_web_lookup_rejects_a_weak_title_before_playing(self):
        track = 'W' * 22
        page = f'https://open.spotify.com/track/{track}'
        with patch.object(atticus, 'playlist', return_value=None), \
             patch.object(atticus, 'get', side_effect=[page, json.dumps({'title': 'Unrelated public playlist'})] * 2), \
             patch.object(atticus.subprocess, 'run') as run:
            self.assertIsNone(atticus.play('fixture playlist'))
        run.assert_not_called()

    def test_broad_play_accepts_reordered_query_words_but_queue_stays_exact(self):
        page = 'https://open.spotify.com/playlist/' + 'D' * 22
        responses = [page, json.dumps({'title': 'Keys Ambient Collection'})]
        with patch.object(atticus, 'playlist', return_value=None), \
             patch.object(atticus, 'get', side_effect=responses):
            self.assertEqual(atticus.spotify_item('ambient keys'),
                             ('spotify:playlist:' + 'D' * 22, 'Keys Ambient Collection'))
        with patch.object(atticus, 'playlist', return_value=None), \
             patch.object(atticus, 'get', side_effect=responses * 2), \
             patch.object(atticus.subprocess, 'run') as run:
            self.assertIn('No matching Spotify result', atticus.queue('ambient keys'))
        run.assert_not_called()

    def test_lookup_tries_later_results_and_engine_after_request_failure(self):
        page = ''.join(f'<a href="https://open.spotify.com/track/{c * 22}">{title}</a>'
                       for c, title in (('E', 'Other song'), ('F', 'Fixture song')))
        with patch.object(atticus, 'playlist', return_value=None), \
             patch.object(atticus, 'get', side_effect=[OSError('offline'), page]) as get:
            self.assertEqual(atticus.spotify_item('fixture song'), ('spotify:track:' + 'F' * 22, 'Fixture song'))
        self.assertEqual(get.call_count, 2)

    def test_oembed_429_is_not_retried_for_more_candidates_or_engines(self):
        page = ' '.join('https://open.spotify.com/track/' + c * 22 for c in 'LM')
        error = urllib.error.HTTPError('https://open.spotify.com/oembed', 429, 'limited', {}, None)
        self.addCleanup(error.close)
        with patch.object(atticus, 'playlist', return_value=None), \
             patch.object(atticus, 'get', side_effect=[page, error, page]) as get:
            with self.assertRaisesRegex(RuntimeError, 'HTTP 429'):
                atticus.spotify_item('fixture song')
        self.assertEqual(get.call_count, 3)
        self.assertEqual(sum('/oembed?' in call.args[0] for call in get.call_args_list), 1)

    def test_page_titles_are_tried_before_any_metadata_request(self):
        page = ('https://open.spotify.com/track/' + 'R' * 22 +
                '<a href="https://open.spotify.com/track/' + 'S' * 22 + '">Fixture song</a>')
        with patch.object(atticus, 'playlist', return_value=None), \
             patch.object(atticus, 'get', return_value=page) as get:
            self.assertEqual(atticus.spotify_item('fixture song'), ('spotify:track:' + 'S' * 22, 'Fixture song'))
        get.assert_called_once()

    def test_titled_candidate_can_resolve_after_oembed_is_rate_limited(self):
        page = 'https://open.spotify.com/track/' + 'P' * 22
        fallback = '<a href="https://open.spotify.com/track/' + 'Q' * 22 + '"><b>Fixture</b> song</a>'
        error = urllib.error.HTTPError('https://open.spotify.com/oembed', 429, 'limited', {}, None)
        self.addCleanup(error.close)
        with patch.object(atticus, 'playlist', return_value=None), \
             patch.object(atticus, 'get', side_effect=[page, error, fallback]) as get:
            self.assertEqual(atticus.spotify_item('fixture song'), ('spotify:track:' + 'Q' * 22, 'Fixture song'))
        self.assertEqual(get.call_count, 3)

    def test_oembed_fallback_is_used_once_and_only_without_a_page_title(self):
        page = 'https://open.spotify.com/track/' + 'N' * 22
        with patch.object(atticus, 'playlist', return_value=None), \
             patch.object(atticus, 'get', side_effect=[page, json.dumps({'title': 'Fixture song'})]) as get:
            self.assertEqual(atticus.spotify_item('fixture song'), ('spotify:track:' + 'N' * 22, 'Fixture song'))
        self.assertEqual(get.call_count, 2)

    def test_search_failures_are_errors_and_never_reach_playback(self):
        for error in (urllib.error.HTTPError('https://example.invalid', 429, 'limited', {}, None),
                      OSError('offline'), ValueError('bad response')):
            if isinstance(error, urllib.error.HTTPError):
                self.addCleanup(error.close)
            for action in (atticus.play, atticus.queue):
                with self.subTest(error=type(error).__name__, action=action.__name__), \
                     patch.object(atticus, 'playlist', return_value=None), \
                     patch.object(atticus, 'get', side_effect=error) as get, \
                     patch.object(atticus.subprocess, 'run') as run:
                    if action is atticus.play:
                        with self.assertRaises(RuntimeError) as raised:
                            action('fixture')
                        reply = str(raised.exception)
                    else:
                        reply = action('fixture')
                self.assertIn('Could not search Spotify', reply)
                if isinstance(error, urllib.error.HTTPError):
                    self.assertIn('HTTP 429', reply)
                self.assertNotIn('nothing found', reply.lower())
                self.assertEqual(get.call_count, 2)
                run.assert_not_called()

    def test_fallback_does_not_hide_an_earlier_http_error(self):
        error = urllib.error.HTTPError('https://example.invalid', 429, 'limited', {}, None)
        self.addCleanup(error.close)
        with patch.object(atticus, 'playlist', return_value=None), \
             patch.object(atticus, 'get', side_effect=[error, '<html>unavailable</html>']):
            with self.assertRaisesRegex(RuntimeError, 'HTTP 429'):
                atticus.play('fixture')

    def test_exhausted_search_offers_encoded_direct_search_without_actions(self):
        name = 'Fixture / song? # & café'
        error = urllib.error.HTTPError('https://example.invalid', 429, 'limited', {}, None)
        self.addCleanup(error.close)
        for response in (error, TimeoutError('timed out'), '<html>challenge</html>'):
            with self.subTest(response=type(response).__name__), \
                 patch.object(atticus, 'playlist', return_value=None), \
                 patch.object(atticus, 'get', side_effect=[response, response]) as get, \
                 patch.object(atticus.subprocess, 'run') as run:
                with self.assertRaises(RuntimeError) as raised:
                    atticus.spotify_item(name)
                reply = str(raised.exception)
                self.assertIn('web search', reply)
                self.assertIn('https://open.spotify.com/search/Fixture%20%2F%20song%3F%20%23%20%26%20caf%C3%A9', reply)
                self.assertIn('Playback has not started', reply)
                self.assertEqual(get.call_count, 2)
                run.assert_not_called()

    def test_unusable_search_and_metadata_are_not_zero_results(self):
        page = 'https://open.spotify.com/track/' + 'I' * 22
        for responses in (['<html>challenge</html>'] * 2,
                          [page, '{bad json'] * 2,
                          [page, json.dumps({'title': None})] * 2):
            with self.subTest(responses=responses), patch.object(atticus, 'playlist', return_value=None), \
                 patch.object(atticus, 'get', side_effect=responses):
                with self.assertRaisesRegex(RuntimeError, 'Could not search Spotify'):
                    atticus.spotify_item('fixture')

    def test_automation_denial_is_reported_once_without_retry(self):
        item = ('spotify:track:' + 'J' * 22, 'Fixture song')
        with patch.object(atticus, 'spotify_item', return_value=item), patch.object(atticus, 'osa', return_value='Editor'), \
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'Not authorized (-1743)')) as run:
            reply = atticus.play('fixture')
        self.assertIn('macOS denied', reply)
        self.assertNotIn('nothing found', reply.lower())
        run.assert_called_once()

    def test_play_does_not_blame_permission_for_other_errors(self):
        item = ('spotify:track:' + 'K' * 22, 'Fixture song')
        for result in (subprocess.TimeoutExpired('osascript', 30), OSError('missing executable'),
                       subprocess.CompletedProcess([], 1, '', 'Application unavailable (-600)'),
                       subprocess.CompletedProcess([], 0, 'paused', '')):
            with self.subTest(result=result), patch.object(atticus, 'spotify_item', return_value=item), \
                 patch.object(atticus, 'osa', return_value='Editor'), patch.object(atticus.subprocess, 'run') as run:
                if isinstance(result, Exception): run.side_effect = result
                else: run.return_value = result
                reply = atticus.play('fixture')
            self.assertIn('Could not start', reply)
            self.assertNotIn('Automation', reply)

    def test_play_uses_shared_lookup_and_keeps_spotify_behind(self):
        item = ('spotify:track:' + 'B' * 22, 'Fixture song')
        with patch.object(atticus, 'spotify_item', return_value=item) as lookup, \
             patch.object(atticus, 'osa', return_value='Editor'), \
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'playing', '')) as run, \
             patch.object(atticus, 'preview_app') as preview, patch.object(atticus, 'wants_focus', return_value=False), \
             patch.object(atticus, 'keep_behind') as behind:
            self.assertEqual(atticus.play('fixture'), 'Playing Fixture song on Spotify.')
        lookup.assert_called_once_with('fixture', True)
        self.assertEqual(run.call_args.args[0][-1], item[0])
        preview.assert_called_once_with('Spotify', 'play')
        behind.assert_called_once_with('Editor', 'Spotify')

    def test_play_reply_names_spotify_once(self):
        item = ('spotify:playlist:' + 'C' * 22, 'Top 100 Pop Tracks on Spotify')
        with patch.object(atticus, 'spotify_item', return_value=item), patch.object(atticus, 'osa', return_value='Editor'), \
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'playing', '')), \
             patch.object(atticus, 'preview_app'), patch.object(atticus, 'keep_behind'):
            self.assertEqual(atticus.play('my playlist'), 'Playing Top 100 Pop Tracks on Spotify.')
        self.assertEqual(atticus.label('Bash', {'command': f'{atticus.PLAY} "hits on spotify"'}), 'Playing hits on spotify')

    def test_play_reports_rejected_or_unverified_spotify_commands(self):
        item = ('spotify:track:' + 'G' * 22, 'Fixture song')
        for result in (subprocess.CompletedProcess([], 1, '', 'denied'),
                       subprocess.CompletedProcess([], 0, 'paused', '')):
            with self.subTest(result=result), patch.object(atticus, 'spotify_item', return_value=item), \
                 patch.object(atticus, 'osa', return_value='Editor'), patch.object(atticus.subprocess, 'run', return_value=result), \
                 patch.object(atticus, 'preview_app') as preview, patch.object(atticus, 'keep_behind') as behind:
                reply = atticus.play('fixture')
            self.assertIn('Could not start Fixture song', reply)
            preview.assert_not_called()
            behind.assert_not_called()

    def test_queue_uses_discovered_ax_labels_and_verifies_the_toast(self):
        item = ('spotify:track:' + 'C' * 22, 'Fixture song')
        page = {'texts': ['Fixture song'], 'nodes': [{'role': 'AXButton', 'label': 'More options for Fixture song'}]}
        menu = {'texts': [], 'nodes': [{'role': 'AXMenuItem', 'label': 'Add to queue'}]}
        toast = {'texts': ['Fixture song', 'Added to queue'], 'nodes': []}
        actions = [('Clicked More options', True), ('Clicked Add to queue\nAdded to queue', True)]
        with patch.object(atticus, 'spotify_item', return_value=item), \
             patch.object(atticus, 'osa', return_value='Editor'), \
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run, \
             patch.object(atticus, 'preview_app'), patch.object(atticus, 'hands_map', return_value=page), \
             patch.object(atticus, 'cached_hands', side_effect=[menu, toast]), \
             patch.object(atticus, 'hands', side_effect=actions) as hands, \
             patch.object(atticus, 'keep_behind') as behind:
            self.assertEqual(atticus.queue('fixture'), 'Added Fixture song to your Spotify queue.')
        run.assert_called_once_with(['open', '-g', item[0]], capture_output=True)
        self.assertEqual(hands.call_args_list[0].args, ('click', 'More options for Fixture song', 'near', 'Fixture song'))
        self.assertEqual(hands.call_args_list[1].args, ('click', 'Add to queue'))
        self.assertEqual(behind.call_count, 3)

    def test_queue_waits_for_the_requested_track_before_opening_its_menu(self):
        item = ('spotify:track:' + 'F' * 22, 'Requested fixture')
        old_page = {'texts': ['Different track'], 'nodes': [{'role': 'AXButton', 'label': 'More options'}]}
        with patch.object(atticus, 'spotify_item', return_value=item), patch.object(atticus, 'osa', return_value='Editor'), \
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(atticus, 'preview_app'), patch.object(atticus, 'hands_map', return_value=old_page), \
             patch.object(atticus, 'hands') as hands, patch.object(atticus, 'keep_behind'), patch.object(atticus.time, 'sleep'):
            reply = atticus.queue('requested')
        self.assertIn('could not find its More options control', reply)
        hands.assert_not_called()

    def test_queue_identity_requires_an_exact_title_and_matching_control(self):
        wrong = {'texts': ['Homecoming'], 'nodes': [{'label': 'More options for Homecoming'}]}
        with patch.object(atticus, 'hands_map', return_value=wrong), patch.object(atticus.time, 'sleep'):
            self.assertEqual(atticus._spotify_wait_control(('more', 'option'), 'Home'), (None, None))
        self.assertIsNone(atticus._spotify_control({**wrong, 'texts': ['Home']}, ('more', 'option'), 'Home'))
        self.assertFalse(atticus._spotify_verified('Added to queue', wrong, 'Home', action=True))
        self.assertFalse(atticus._spotify_verified('Added to queue', {'texts': ['Home']}, 'Homecoming', action=True))
        self.assertTrue(atticus._spotify_verified('Added to queue', {'texts': ['Up']}, 'Up', action=True))

    def test_queue_can_verify_the_track_in_the_queue_view(self):
        item = ('spotify:track:' + 'D' * 22, 'Another fixture')
        page = {'texts': ['Another fixture'], 'nodes': [{'role': 'AXButton', 'label': 'More options'}]}
        menu = {'texts': [], 'nodes': [{'role': 'AXMenuItem', 'label': 'Add to queue'}]}
        queue_button = {'texts': [], 'nodes': [{'role': 'AXButton', 'label': 'Queue'}]}
        queue_view = {'texts': ['Another fixture'], 'nodes': []}
        with patch.object(atticus, 'spotify_item', return_value=item), patch.object(atticus, 'osa', return_value='Editor'), \
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(atticus, 'preview_app'), patch.object(atticus, 'hands_map', return_value=page), \
             patch.object(atticus, 'cached_hands', side_effect=[menu, queue_button, queue_view]), \
             patch.object(atticus, 'hands', side_effect=[('More', True), ('Added', True), ('Queue opened', True)]) as hands, \
             patch.object(atticus, 'keep_behind'):
            self.assertEqual(atticus.queue('another'), 'Added Another fixture to your Spotify queue.')
        self.assertEqual(hands.call_args_list[-1].args, ('click', 'Queue'))

    def test_queue_does_not_claim_success_when_spotify_exposes_no_verification(self):
        item = ('spotify:track:' + 'E' * 22, 'Unverified fixture')
        page = {'texts': ['Unverified fixture'], 'nodes': [{'role': 'AXButton', 'label': 'More options'}]}
        menu = {'texts': [], 'nodes': [{'role': 'AXMenuItem', 'label': 'Add to queue'}]}
        with patch.object(atticus, 'spotify_item', return_value=item), patch.object(atticus, 'osa', return_value='Editor'), \
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(atticus, 'preview_app'), patch.object(atticus, 'hands_map', return_value=page), \
             patch.object(atticus, 'cached_hands', side_effect=[menu, {'texts': ['Unverified fixture'], 'nodes': []}]), \
             patch.object(atticus, 'hands', side_effect=[('More', True), ('Added', True)]) as hands, \
             patch.object(atticus, 'keep_behind'), patch.object(atticus.time, 'sleep'):
            reply = atticus.queue('unverified')
        self.assertIn('could not verify it', reply)
        self.assertIn('do not retry blindly', reply)
        self.assertEqual(hands.call_count, 2)

    def test_queue_explains_the_album_and_playlist_limit_without_opening_spotify(self):
        for kind in ('album', 'playlist', 'artist'):
            with self.subTest(kind=kind), patch.object(atticus, 'spotify_item', return_value=(f'spotify:{kind}:id', 'Fixture')), \
                 patch.object(atticus.subprocess, 'run') as run, patch.object(atticus, 'hands') as hands:
                reply = atticus.queue('fixture')
            self.assertIn(f'tracks in that {kind}', reply)
            self.assertIn('Name one song', reply)
            run.assert_not_called()
            hands.assert_not_called()

    def test_fast_play_falls_through_when_lookup_fails(self):
        for error in (RuntimeError('lookup unavailable'), OSError('offline')):
            with self.subTest(error=type(error).__name__), \
                 patch.object(atticus, 'pref', side_effect=lambda _, default: default), \
                 patch.object(atticus, 'skills', return_value={}), patch.object(atticus, 'fast_hands', return_value=None), \
                 patch.object(atticus, 'spotify_item', side_effect=error) as lookup, \
                 patch.object(atticus.subprocess, 'run') as run:
                self.assertIsNone(atticus.fast('play fixture song on spotify'))
                self.assertEqual(atticus.fast.cmds, [])
                lookup.assert_called_once_with('fixture song', True)
                run.assert_not_called()

    def test_play_cli_preserves_lookup_error(self):
        with patch.object(atticus, 'spotify_item', side_effect=RuntimeError('Could not search Spotify: HTTP 429.')), \
             patch('sys.argv', ['atticus.py', '--play', 'Fixture', 'song']), \
             patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.main()
        self.assertEqual(out.getvalue().strip(), 'Could not search Spotify: HTTP 429.')

    def test_unambiguous_queue_requests_run_without_ai(self):
        with patch.object(atticus, 'pref', side_effect=lambda _, default: default), \
             patch.object(atticus, 'skills', return_value={}), patch.object(atticus, 'fast_hands', return_value=None), \
             patch.object(atticus, 'queue', return_value='Added Fixture song to your Spotify queue.') as queue, \
             patch.dict(atticus.os.environ, {'ATTICUS_LIVE': '1'}):
            for request in ('add Fixture song to my queue', 'queue Fixture song next'):
                with self.subTest(request=request):
                    self.assertEqual(atticus.fast(request), 'Added Fixture song to your Spotify queue.')
                    queue.assert_called_with('fixture song')
            queue.reset_mock()
            self.assertIsNone(atticus.fast('add it to my queue'))
            queue.assert_not_called()

    def test_queue_cli_and_step_label(self):
        with patch.object(atticus, 'queue', return_value='Added Fixture song to your Spotify queue.') as queue, \
             patch('sys.argv', ['atticus.py', '--queue', 'Fixture', 'song']), \
             patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.main()
        queue.assert_called_once_with('Fixture song')
        self.assertEqual(out.getvalue().strip(), 'Added Fixture song to your Spotify queue.')
        self.assertEqual(atticus.label('Bash', {'command': f'{atticus.QUEUE} "Fixture song"'}),
                         'Adding Fixture song to the queue')
        self.assertIn(atticus.QUEUE, atticus.SYSTEM)


if __name__ == '__main__':
    unittest.main()
