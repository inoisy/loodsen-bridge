"""Шлюзы Time без сети: белый список, кэш при недоступности моста."""
import importlib.machinery
import importlib.util
import io
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name, file):
    loader = importlib.machinery.SourceFileLoader(name, str(HERE / file))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec); loader.exec_module(mod)
    return mod


class Resp(io.BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): return False


class Fake:
    def __init__(self, *answers): self.answers, self.seen = list(answers), []

    def open(self, req, timeout):
        self.seen.append((req.get_method(), req.full_url))
        a = self.answers.pop(0)
        if isinstance(a, BaseException): raise a
        status, body = a
        if status != 200: raise urllib.error.HTTPError(req.full_url, status, 'x', {}, io.BytesIO(body))
        return Resp(body)


class ServerGateway(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ['TIME_GW_CACHE'] = str(Path(self.tmp.name) / 'c.sqlite')
        self.m = load('time_gw', 'time-gw')

    def tearDown(self): self.tmp.cleanup()

    def gw(self, *answers):
        self.fake = Fake(*answers)
        return self.m.Gateway(cache=self.m.Cache(Path(self.tmp.name) / 'c.sqlite'), opener=self.fake)

    def test_чтение_идёт_в_мост(self):
        g = self.gw((200, b'{"data":{}}'))
        st, _, _, src = g.handle('POST', '/bff/timesheet', b'{"view":"EMPLOYEE"}', 'application/json')
        self.assertEqual((st, src), (200, 'upstream'))
        self.assertEqual(self.fake.seen[0], ('POST', 'http://127.0.0.1:18447/bff/timesheet'))

    def test_вне_белого_списка_403_без_похода(self):
        g = self.gw()
        for method, path in (('POST', '/bff/timesheet/save'), ('DELETE', '/bff/timesheet'), ('GET', '/legacy/api/tasks'),
                             ('POST', '/bff/scope'), ('GET', '/bff/timesheet/filter/../../admin')):
            self.assertEqual(g.handle(method, path, b'', '')[0], 403, path)
        self.assertEqual(self.fake.seen, [])

    def test_core_logs_идёт_в_мост_как_есть(self):
        g = self.gw((200, b'{"items":[]}'))
        st, _, _, src = g.handle('GET', '/core/logs?dateFrom=2026-10-01&dateTo=2026-10-31&offset=0&limit=500', b'', '')
        self.assertEqual((st, src), (200, 'upstream'))
        self.assertEqual(self.fake.seen[0], ('GET', 'http://127.0.0.1:18447/core/logs?dateFrom=2026-10-01&dateTo=2026-10-31&offset=0&limit=500'))

    def test_core_только_чтение_списка(self):
        g = self.gw()
        for method, path in (('PUT', '/core/logs/7c1e0d6a-1b8a-5f3c-9d2e-3a4b5c6d7e8f'), ('GET', '/core/logs/x'),
                             ('POST', '/core/logs'), ('GET', '/core/actuator/health'), ('GET', '/core/../bff/scope')):
            self.assertEqual(g.handle(method, path, b'', '')[0], 403, path)
        self.assertEqual(self.fake.seen, [])

    def test_мост_лёг_отдаём_кэш_с_пометкой(self):
        g = self.gw((200, b'{"d":1}'), urllib.error.URLError('down'))
        g.handle('GET', '/bff/scope', b'', '')
        st, h, body, src = g.handle('GET', '/bff/scope', b'', '')
        self.assertEqual((st, body, src), (200, b'{"d":1}', 'stale')); self.assertIn('X-Time-Gw-Stale', h)

    def test_без_кэша_503_и_ошибка_time_не_кэшируется(self):
        g = self.gw((500, b'boom'), (400, b'{"error":"bad"}'), urllib.error.URLError('down'))
        self.assertEqual(g.handle('GET', '/bff/timesheet/column', b'', '')[0], 503)
        self.assertEqual(g.handle('POST', '/bff/timesheet', b'x', '')[0], 400)
        self.assertEqual(g.handle('POST', '/bff/timesheet', b'x', '')[0], 503)


class MacAllowList(unittest.TestCase):
    def test_тот_же_белый_список(self):
        mac = load('time_gw_mac', 'time-gw-mac')
        self.assertTrue(mac.allowed('POST', '/bff/timesheet'))
        self.assertTrue(mac.allowed('GET', '/bff/timesheet/filter/projects'))
        self.assertFalse(mac.allowed('POST', '/bff/timesheet/save'))
        self.assertFalse(mac.allowed('DELETE', '/bff/timesheet'))
        self.assertTrue(mac.allowed('GET', '/core/logs?dateFrom=2026-10-01&dateTo=2026-10-31'))
        self.assertFalse(mac.allowed('PUT', '/core/logs/x'))

    def test_core_уходит_в_core_time(self):
        mac = load('time_gw_mac', 'time-gw-mac')
        self.assertEqual(mac.upstream_url('/core/logs?dateFrom=2026-10-01&offset=0'),
                         'https://<internal-host>/logs?dateFrom=2026-10-01&offset=0')
        self.assertEqual(mac.upstream_url('/bff/scope'), 'https://<internal-host>/bff/scope')

    def test_core_от_сервиса_bff_от_евгения(self):
        import http.client, threading, io
        from http.server import ThreadingHTTPServer
        mac = load('time_gw_mac', 'time-gw-mac')
        class Tok:
            def __init__(self, v): self.v = v
            def get(self, fresh=False): return self.v
        seen = []
        class Resp(io.BytesIO):
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False
        real = mac.urllib.request.urlopen
        mac.urllib.request.urlopen = lambda req, timeout=None: (seen.append((req.full_url, req.get_header('Authorization'))), Resp(b'{}'))[1]
        try:
            srv = ThreadingHTTPServer(('127.0.0.1', 0), mac.make_handler(Tok('user'), Tok('svc')))
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            for path in ('/core/logs?dateFrom=2026-10-01', '/bff/scope'):
                c = http.client.HTTPConnection('127.0.0.1', srv.server_address[1]); c.request('GET', path); c.getresponse().read()
            srv.shutdown()
        finally:
            mac.urllib.request.urlopen = real
        self.assertEqual(seen, [('https://<internal-host>/logs?dateFrom=2026-10-01', 'Bearer svc'),
                                ('https://<internal-host>/bff/scope', 'Bearer user')])


if __name__ == '__main__':
    unittest.main()
