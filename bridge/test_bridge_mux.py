"""Мосты от нескольких людей: слоты, authorized_keys, выбор живого слота и переключение."""
import asyncio
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEY_A = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
KEY_B = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB'


def load(tmp):
    os.environ['BRIDGE_MUX_CONFIG'] = str(tmp / 'mux.json')
    os.environ['BRIDGE_AUTH_KEYS'] = str(tmp / 'authorized_keys')
    os.environ['BRIDGE_MUX_PROBE_TIMEOUT'] = '1'
    loader = importlib.machinery.SourceFileLoader('bridge_mux', str(HERE / 'bridge-mux'))
    spec = importlib.util.spec_from_loader('bridge_mux', loader)
    mod = importlib.util.module_from_spec(spec); loader.exec_module(mod)
    return mod


class Users(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.m = load(self.tmp)

    def test_слоты_выдаются_по_порядку_и_освобождаются(self):
        cfg = {'users': []}
        self.assertEqual(self.m.add_user(cfg, 'ilya', KEY_A, ['sphere'])['slot'], 1)
        self.assertEqual(self.m.add_user(cfg, 'petr', KEY_B + ' petr@mac', ['sphere'])['slot'], 2)
        self.m.remove_user(cfg, 'ilya')
        self.assertEqual(self.m.add_user(cfg, 'anna', KEY_A, ['git01'])['slot'], 1)
        self.assertEqual(cfg['users'][0]['key'], KEY_B, 'комментарий ключа не хранится')

    def test_дубли_и_мусор_отбиваются(self):
        cfg = {'users': []}
        self.m.add_user(cfg, 'ilya', KEY_A, ['sphere'])
        for name, key, svc in [('ilya', KEY_B, ['sphere']), ('petr', KEY_A, ['sphere']),
                               ('Petr', KEY_B, ['sphere']), ('petr', 'ключ', ['sphere']), ('petr', KEY_B, ['ftp'])]:
            with self.assertRaises(ValueError): self.m.add_user(cfg, name, key, svc)

    def test_ключ_слушает_только_свой_слот_на_loopback(self):
        line = self.m.auth_line({'name': 'petr', 'slot': 2, 'key': KEY_B, 'services': ['sphere', 'git01']})
        self.assertEqual(line, 'restrict,port-forwarding,permitlisten="127.0.0.1:20243",permitlisten="127.0.0.1:20222",'
                               f'command="/usr/sbin/nologin" {KEY_B} bridge:petr')

    def test_cli_add_пишет_конфиг_и_authorized_keys(self):
        (self.tmp / 'k.pub').write_text(KEY_A + ' ilya@mac\n')
        self.assertEqual(self.m.main(['user', 'add', 'ilya', str(self.tmp / 'k.pub')]), 0)
        cfg = json.loads((self.tmp / 'mux.json').read_text())
        self.assertEqual(cfg['users'][0]['services'], ['sphere', 'kc', 'git01', 'dev'])
        keys = (self.tmp / 'authorized_keys').read_text().splitlines()
        self.assertEqual(len(keys), 2); self.assertTrue(keys[1].endswith('bridge:ilya'))

    def test_клиент_пробрасывает_свои_порты(self):
        user = {'name': 'petr', 'slot': 2, 'key': KEY_B, 'services': ['sphere', 'dev']}
        cmd = self.m.render_client(user, 'ssh', '~/.ssh/k')
        self.assertIn('-R 127.0.0.1:20243:<sphere-host>:443 -R 127.0.0.1:20250:<internal-ip>:443', cmd)
        self.assertIn('%h/.ssh/k', self.m.render_client(user, 'systemd', '~/.ssh/k'))
        self.assertIn('"$HOME"/.ssh/k', self.m.render_client(user, 'plist', '~/.ssh/k'))
        win = self.m.render_client(user, 'windows', '~/.ssh/id_rsa')
        self.assertIn('& ssh -N -i "$env:USERPROFILE\\.ssh\\id_rsa" -o', win)
        self.assertIn('-R 127.0.0.1:20243:<sphere-host>:443', win)

    def test_старый_клиент_держит_18443_сам(self):
        cfg = {'users': []}
        self.m.add_user(cfg, 'ilya', KEY_A, ['sphere', 'git01']); self.m.add_user(cfg, 'petr', KEY_B, ['sphere'])
        self.m.set_legacy(cfg, 'ilya', True)
        ilya = cfg['users'][0]
        self.assertEqual(ilya['services'], ['sphere'])
        self.assertIn('permitlisten="127.0.0.1:18443",permitlisten="192.168.200.1:18443"', self.m.auth_line(ilya))
        self.assertEqual(self.m.candidates(cfg, 'sphere', {20243: True}), [20243, 18443])
        with self.assertRaises(ValueError): self.m.set_legacy(cfg, 'petr', True)
        self.m.set_legacy(cfg, 'ilya', False)
        self.assertNotIn('legacy', ilya); self.assertIn('127.0.0.1:20143', self.m.auth_line(ilya))

    def test_живые_слоты_первыми_в_порядке_приоритета(self):
        cfg = {'users': [{'name': 'a', 'slot': 1, 'services': ['sphere']},
                         {'name': 'b', 'slot': 2, 'services': ['sphere']},
                         {'name': 'c', 'slot': 3, 'services': ['git01']}]}
        self.assertEqual(self.m.candidates(cfg, 'sphere', {20243: True}), [20243, 20143])
        self.assertEqual(self.m.candidates(cfg, 'sphere', {}), [20143, 20243])
        self.assertEqual(self.m.active(cfg, {20243: True, 20322: True})['sphere'], 'b')
        self.assertIsNone(self.m.active(cfg, {})['kc'])


class Failover(unittest.IsolatedAsyncioTestCase):
    """Мёртвый слот: порт закрыт или слушает, но молчит (уснувшая машина за живым sshd)."""

    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.m = load(self.tmp)
        self.m.BASE = 31000
        self.m.SERVICES = {'git01': dict(offset=22, listen=['127.0.0.1:31022'], target='x:22', probe=('ssh', None))}
        self.servers = []

    async def asyncTearDown(self):
        for s in self.servers: s.close()

    async def upstream(self, port, banner):
        async def h(r, w):
            if banner: w.write(banner); await w.drain()
            await asyncio.sleep(5)
        self.servers.append(await asyncio.start_server(h, '127.0.0.1', port))

    def config(self, *users):
        (self.tmp / 'mux.json').write_text(json.dumps(
            {'users': [{'name': n, 'slot': s, 'key': KEY_A, 'services': ['git01']} for n, s in users]}))

    async def banner_via_mux(self, mux):
        r, w = await asyncio.open_connection('127.0.0.1', 31022)
        data = await asyncio.wait_for(r.read(8), 3); w.close()
        return data

    async def test_подвисший_первый_слот_пропускается(self):
        await self.upstream(31122, None)                  # слот 1: sshd слушает, машина молчит
        await self.upstream(31222, b'SSH-2.0-petr')       # слот 2 жив
        self.config(('ilya', 1), ('petr', 2))
        mux = self.m.Mux(self.tmp / 'mux.json'); mux.healthy = await self.m.probe_all(mux.cfg)
        self.assertEqual(mux.healthy, {31122: False, 31222: True})
        self.servers.append(await asyncio.start_server(lambda r, w: mux.handle('git01', r, w), '127.0.0.1', 31022))
        self.assertEqual(await self.banner_via_mux(mux), b'SSH-2.0-')

    async def test_закрытый_порт_слота_пропускается_без_пробы(self):
        await self.upstream(31222, b'SSH-2.0-petr')
        self.config(('ilya', 1), ('petr', 2))             # у слота 1 никто не слушает
        mux = self.m.Mux(self.tmp / 'mux.json')           # пробы ещё не было
        self.servers.append(await asyncio.start_server(lambda r, w: mux.handle('git01', r, w), '127.0.0.1', 31022))
        self.assertEqual(await self.banner_via_mux(mux), b'SSH-2.0-')
        self.assertFalse(mux.healthy[31122])


if __name__ == '__main__':
    unittest.main()
