"""Agent storage loss uses scratch files and stub workers only."""
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import atticus


class AgentDirectoryTests(unittest.TestCase):
    def test_directory_loss_at_scan_event_and_save_terminalizes_once(self):
        for boundary in ('scan', 'event', 'save', 'context', 'cancel', 'root', 'read', 'read-save'):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as root, \
                 patch.object(atticus, 'DIR', root), patch.object(atticus, 'pref', side_effect=lambda k, d: d), \
                 patch.object(atticus, 'close_agent_window'), patch.object(atticus, 'stop_claude'):
                events = []
                launch = Mock()
                manager = atticus.Agents(emit=lambda e: events.append(json.loads(json.dumps(e))), launch=launch)
                row = manager.new()
                row.update(status='running', brief='Fixture task', _metadataAt=float('inf'))
                manager.rows[row['id']] = row
                manager.save(row)
                worker = Mock(stdin=io.StringIO(), stdout=io.StringIO(json.dumps({'type': 'result', 'session_id': 'fixture', 'result': 'Late result'}) + '\n'), errors=None)
                manager.processes[row['id']] = worker
                manager.outstanding[row['id']] = 1
                manager.offers.add(row['id'])
                events.clear()
                original = atticus.private_json

                def lose_after_state(path, data):
                    original(path, data)
                    if Path(path).name == 'state.json': shutil.rmtree(row['directory'])

                if boundary == 'root': shutil.rmtree(root)
                elif boundary not in ('context', 'read-save'): shutil.rmtree(row['directory'])
                if boundary in ('scan', 'root'): manager.tick()
                elif boundary == 'event': manager.event(row, {'event': 'claude', 'data': {}})
                elif boundary == 'cancel': manager.command({'action': 'stop', 'id': row['id']})
                elif boundary == 'read': manager.read(row, worker)
                elif boundary == 'read-save':
                    with patch.object(atticus, 'private_json', side_effect=lose_after_state): manager.read(row, worker)
                elif boundary == 'context':
                    with patch.object(atticus, 'private_json', side_effect=lose_after_state): manager.save(row)
                else: manager.save(row)

                terminal = json.loads(json.dumps(row))
                self.assertEqual(row['status'], 'stopped' if boundary == 'cancel' else 'failed')
                self.assertIn('directory', row['result'].lower())
                self.assertNotIn(row['id'], manager.processes)
                self.assertNotIn(row['id'], manager.offers)
                # Late writes, worker revival, and stale start commands cannot revive lost work.
                manager.event(row, {'event': 'claude', 'data': {'type': 'result'}})
                manager.save(row)
                manager.finish(row, 'done', 'Late result')
                manager.send(row, 'Late followup')
                manager.revive(row)
                manager.start(row['id'])
                manager.tick()
                self.assertEqual(row, terminal)
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]['event'], 'state')
                record = Path(atticus.agent_gate_dir(row['directory'])) / 'terminal.json'
                if boundary == 'root': self.assertFalse(record.exists())
                else: self.assertEqual(json.loads(record.read_text()), terminal)
                self.assertFalse(Path(row['directory']).exists())
                launch.assert_not_called()
                # An unrelated task can still persist and be scanned.
                other = manager.new()
                other.update(status='running', _metadataAt=float('inf'))
                manager.rows[other['id']] = other
                manager.processes[other['id']] = Mock(stdin=io.StringIO(), stdout=io.StringIO(), errors=None)
                (Path(other['directory']) / 'hands-fixture').write_text('▸ Still working\n')
                manager.save(other)
                manager.tick()
                self.assertTrue((Path(other['directory']) / 'state.json').exists())
                self.assertEqual(other['steps'], ['Still working'])
                manager.close()
