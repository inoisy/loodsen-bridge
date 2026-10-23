"""Шлюз Сферы без сети: белый список, batch, кэш при недоступности, ключи профилей."""
import importlib.machinery
import importlib.util
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(tmp):
    os.environ['SPHERE_GW_KEYS'] = str(tmp / 'keys')
    os.environ['SPHERE_GW_API_KEYS'] = str(tmp / 'api')
    os.environ['SPHERE_GW_CACHE'] = str(tmp / 'cache.sqlite')
    os.environ['SPHERE_UPSTREAM'] = 'https://sphere.test:18443'
    loader = importlib.machinery.SourceFileLoader('sphere_gw', str(HERE / 'sphere-gw'))
    spec = importlib.util.spec_from_loader('sphere_gw', loader)
    mod = importlib.util.module_from_spec(spec); loader.exec_module(mod)
    return mod


class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


class Fake:
    """Подмена opener: отвечает по очереди заданными ответами и запоминает запросы."""
    def __init__(self, *answers): self.answers, self.seen, self.reqs = list(answers), [], []

    def open(self, req, timeout):
        self.seen.append((req.full_url, req.data)); self.reqs.append(req)
        a = self.answers.pop(0)
        if isinstance(a, BaseException): raise a
        status, body = a
        if status != 200: raise urllib.error.HTTPError(req.full_url, status, 'x', {}, io.BytesIO(body))
        return Resp(body)


class Gateway(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); t = Path(self.tmp.name)
        self.m = load(t)
        (t / 'keys').mkdir(); (t / 'keys' / 'rp').write_text('https://<sphere-host>/rest/42/SECRET/\n')
        self.m.MIN_INTERVAL = 0

    def tearDown(self): self.tmp.cleanup()

    def gw(self, *answers):
        self.fake = Fake(*answers)
        return self.m.Gateway(cache=self.m.Cache(Path(self.tmp.name) / 'c.sqlite'), pacer=self.m.Pacer(0), opener=self.fake)

    def test_чтение_идёт_в_сферу_через_мост_с_ключом_профиля(self):
        g = self.gw((200, b'{"result": [1]}'))
        st, h, body, src, *_ = g.handle('/rest/rp/gw/user.get', b'{"start": 0}', 'application/json')
        self.assertEqual((st, src, body), (200, 'upstream', b'{"result": [1]}'))
        self.assertEqual(self.fake.seen[0], ('https://sphere.test:18443/rest/42/SECRET/user.get.json', b'{"start": 0}'))

    def test_суффикс_json_как_у_mcp(self):
        g = self.gw((200, b'{"result": {}}'))
        self.assertEqual(g.handle('/rest/rp/gw/tasks.task.get.json', b'taskId=1', 'application/x-www-form-urlencoded')[0], 200)
        self.assertTrue(self.fake.seen[0][0].endswith('/tasks.task.get.json'))

    def test_свой_api_get_с_учёткой_профиля_и_кэшем(self):
        (Path(self.tmp.name) / 'api').mkdir(); (Path(self.tmp.name) / 'api' / 'rp').write_text('Multica_test:pw\n')
        g = self.gw((200, b'{"total": 1, "items": []}'), OSError('мост лёг'))
        st, h, body, src, *_ = g.handle('/api/rp/v1/resources/cards/?userId=425', b'', '', 'GET')
        self.assertEqual((st, src), (200, 'upstream'))
        req = self.fake.reqs[0]
        self.assertEqual((req.full_url, req.get_method()), ('https://sphere.test:18443/api/v1/resources/cards/?userId=425', 'GET'))
        self.assertEqual(req.get_header('Authorization'), 'Basic TXVsdGljYV90ZXN0OnB3')
        st, h, body, src, *_ = g.handle('/api/rp/v1/resources/cards/?userId=425', b'', '', 'GET')
        self.assertEqual((st, src, body), (200, 'stale', b'{"total": 1, "items": []}'))
        self.assertIn('X-Sphere-Gw-Stale', h)

    def test_свой_api_только_get_и_только_ручки_из_списка(self):
        (Path(self.tmp.name) / 'api').mkdir(); (Path(self.tmp.name) / 'api' / 'rp').write_text('u:p')
        g = self.gw()
        for path, verb in (('/api/rp/v1/resources/cards/', 'POST'), ('/api/rp/v1/import/users/', 'GET'),
                           ('/api/rp/v1/resources/absences/', 'POST'), ('/api/rp/v1/resources/rates/', 'GET')):
            st, _, body, src, *_ = g.handle(path, b'', '', verb)
            self.assertEqual((st, src, json.loads(body)['error']), (403, 'denied', 'READ_ONLY'), path)
        self.assertEqual(g.handle('/api/tasks/v1/resources/cards/', b'', '', 'GET')[0], 503)
        self.assertEqual(self.fake.seen, [])

    def test_описание_полей_пользователя_читается(self):
        g = self.gw((200, b'{"result": {}}'), (200, b'{"result": []}'))
        for method in ('user.fields', 'user.userfield.list'):
            self.assertEqual(g.handle(f'/rest/rp/gw/{method}', b'', '')[0], 200, method)

    def test_запись_отбивается_без_похода_в_сферу(self):
        g = self.gw()
        for method in ('task.commentitem.add', 'tasks.task.update', 'department.add', 'sonet_group.create',
                       'user.userfield.add', 'user.userfield.update'):
            st, _, body, src, *_ = g.handle(f'/rest/rp/gw/{method}', b'', '')
            self.assertEqual((st, src), (403, 'denied'), method)
            self.assertEqual(json.loads(body)['error'], 'READ_ONLY')
        self.assertEqual(self.fake.seen, [])

    def test_batch_проверяет_каждую_подкоманду(self):
        ok = 'cmd%5Bt%5D=tasks.task.get%3FtaskId%3D1&cmd%5Bc%5D=task.commentitem.getlist%3FTASKID%3D1'
        bad = ok + '&cmd%5Bx%5D=task.commentitem.add%3FTASKID%3D1'
        g = self.gw((200, b'{"result": {"result": {}}}'))
        self.assertEqual(g.handle('/rest/rp/gw/batch', ok.encode(), 'application/x-www-form-urlencoded')[0], 200)
        st, _, body, *_ = g.handle('/rest/rp/gw/batch', bad.encode(), 'application/x-www-form-urlencoded')
        self.assertEqual(st, 403); self.assertIn('task.commentitem.add', json.loads(body)['error_description'])
        st, *_ = g.handle('/rest/rp/gw/batch', json.dumps({'cmd': {'a': 'tasks.task.update?taskId=1'}}).encode(), 'application/json')
        self.assertEqual(st, 403)

    def test_мост_упал_отдаём_последний_ответ_с_пометкой(self):
        g = self.gw((200, b'{"result": ["fresh"]}'), urllib.error.URLError('connection refused'))
        g.handle('/rest/rp/gw/department.get', b'{"START": 0}', 'application/json')
        st, h, body, src, *_ = g.handle('/rest/rp/gw/department.get', b'{"START": 0}', 'application/json')
        self.assertEqual((st, src, body), (200, 'stale', b'{"result": ["fresh"]}'))
        self.assertIn('X-Sphere-Gw-Stale', h)

    def test_другая_страница_из_кэша_не_подменяется(self):
        g = self.gw((200, b'{"result": [1]}'), urllib.error.URLError('down'))
        g.handle('/rest/rp/gw/user.get', b'{"start": 0}', 'application/json')
        st, _, body, src, *_ = g.handle('/rest/rp/gw/user.get', b'{"start": 50}', 'application/json')
        self.assertEqual((st, src), (503, 'error')); self.assertEqual(json.loads(body)['error'], 'SPHERE_UNAVAILABLE')

    def test_5xx_и_429_тоже_берут_кэш(self):
        g = self.gw((200, b'{"result": 1}'), (502, b'bad gateway'), (429, b'{"error":"QUERY_LIMIT_EXCEEDED"}'))
        g.handle('/rest/rp/gw/user.get', b'', '')
        self.assertEqual(g.handle('/rest/rp/gw/user.get', b'', '')[3], 'stale')
        self.assertEqual(g.handle('/rest/rp/gw/user.get', b'', '')[3], 'stale')

    def test_ошибка_битрикса_уходит_клиенту_и_не_кэшируется(self):
        g = self.gw((401, b'{"error":"INVALID_CREDENTIALS"}'), (200, b'{"error":"ACCESS_DENIED"}'), urllib.error.URLError('down'))
        self.assertEqual(g.handle('/rest/rp/gw/user.get', b'', '')[0], 401)
        g.handle('/rest/rp/gw/department.get', b'', '')  # 200 с error — не кэш
        self.assertEqual(g.handle('/rest/rp/gw/department.get', b'', '')[0], 503)

    def test_нет_ключа_и_кривой_профиль(self):
        g = self.gw()
        self.assertEqual(json.loads(g.handle('/rest/tasks/gw/user.get', b'', '')[2])['error'], 'NO_KEY')
        self.assertEqual(g.handle('/rest/../gw/user.get', b'', '')[0], 503)
        self.assertEqual(g.handle('/rest/rp/user.get', b'', '')[0], 404)
        self.assertEqual(self.fake.seen, [])

    def test_ключ_в_файле_может_быть_путём_или_полным_адресом(self):
        (Path(self.tmp.name) / 'keys' / 'p2').write_text('/rest/7/abc/')
        (Path(self.tmp.name) / 'keys' / 'p3').write_text('https://evil.example/other')
        self.assertEqual(self.m.webhook_path('p2'), '/rest/7/abc/')
        self.assertIsNone(self.m.webhook_path('p3'))

    def test_вход_приложения_идёт_с_токеном_пользователя_без_ключа_и_кэша(self):
        g = self.gw((200, b'{"result": {"ID": "7"}}'), (0, None))
        st, h, body, src, *_ = g.handle('/rest/app/user.current', b'auth=tok123', 'application/x-www-form-urlencoded')
        self.assertEqual((st, src, body), (200, 'upstream', b'{"result": {"ID": "7"}}'))
        self.assertEqual(self.fake.seen[0], ('https://sphere.test:18443/rest/user.current.json', b'auth=tok123'))
        self.fake.answers = [urllib.error.URLError('down')]
        st, *_ = g.handle('/rest/app/user.current', b'auth=tok123', 'application/x-www-form-urlencoded')
        self.assertEqual(st, 503)  # чужой токен в кэш не кладём — второй ответ не из кэша

    def test_вход_приложения_только_app_info_и_user_current(self):
        g = self.gw()
        for method in ('user.get', 'tasks.task.list', 'batch', 'user.update'):
            st, h, body, src, *_ = g.handle(f'/rest/app/{method}', b'auth=tok123', 'application/x-www-form-urlencoded')
            self.assertEqual((st, src), (403, 'denied'), method)
        st, *_ = g.handle('/rest/app/app.info', b'', 'application/x-www-form-urlencoded')
        self.assertEqual(st, 400)  # без токена пользователя в Сферу не ходим
        self.assertEqual(self.fake.seen, [])

    def test_ошибка_токена_уходит_клиенту(self):
        g = self.gw((401, b'{"error": "expired_token"}'))
        st, h, body, src, *_ = g.handle('/rest/app/app.info', b'auth=old', 'application/x-www-form-urlencoded')
        self.assertEqual((st, body), (401, b'{"error": "expired_token"}'))

if __name__ == '__main__':
    unittest.main()
