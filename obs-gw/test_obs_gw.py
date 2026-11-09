"""Шлюзы наблюдаемости без сети: белый список Grafana, фильтр проектов Sentry, 503 без моста."""
import importlib.machinery, importlib.util, io, json, unittest, urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name, file):
    loader = importlib.machinery.SourceFileLoader(name, str(HERE / file))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec); loader.exec_module(mod)
    return mod


mac = load('obs_gw_mac', 'obs-gw-mac')
srv = load('obs_gw', 'obs-gw')


class Grafana(unittest.TestCase):
    def test_loki_prom_allowed(self):
        self.assertTrue(mac.grafana_target('/grafana/prod/loki/query_range').endswith('/uid/<datasource-uid>/loki/api/v1/query_range'))
        self.assertTrue(mac.grafana_target('/grafana/stage/loki/label/namespace/values'))
        self.assertTrue(mac.grafana_target('/grafana/prod/prom/query').endswith('/uid/<datasource-uid>/api/v1/query'))
        self.assertTrue(mac.grafana_target('/grafana/prod/api/search'))
        self.assertTrue(mac.grafana_target('/grafana/prod/api/dashboards/uid/abc-1'))
        self.assertTrue(mac.grafana_target('/grafana/prod/api/v1/provisioning/alert-rules'))

    def test_denied(self):
        for p in ['/grafana/prod/loki/delete', '/grafana/prod/api/admin/users', '/grafana/prod/api/users',
                  '/grafana/dev/loki/query', '/grafana/prod/api/dashboards/db', '/grafana/prod/api/serviceaccounts',
                  '/grafana/prod/api/datasources/proxy/uid/x/api/v1/admin/tsdb/delete_series',
                  '/grafana/prod/prom/admin/tsdb/snapshot']:
            self.assertIsNone(mac.grafana_target(p), p)

    def test_clean(self):
        self.assertEqual(mac.clean('/grafana/prod/%2e%2e/api/users')[0], None)
        self.assertEqual(mac.clean('/sentry/api/0/projects/?x=1'), ('/sentry/api/0/projects/', 'x=1'))


class Sentry(unittest.TestCase):
    def setUp(self):
        self.calls = []
        projects = [{'id': 12, 'slug': 'project-a'}, {'id': 3, 'slug': 'project-a'}, {'id': 99, 'slug': 'hr-secret'}]
        issues = {'1': 'project-a', '2': 'hr-secret'}

        def fetch(pq):
            self.calls.append(pq)
            if pq == '/api/0/projects/': return 200, json.dumps(projects).encode()
            iid = pq.split('/')[4]
            if iid in issues: return 200, json.dumps({'project': {'slug': issues[iid]}}).encode()
            return 404, b'{}'
        self.s = mac.Sentry(fetch)

    def test_project_paths(self):
        self.assertEqual(self.s.check('GET', '/api/0/projects/company/project-a/issues/', ''), 'pass')
        self.assertEqual(self.s.check('GET', '/api/0/projects/company/project-a/', ''), 'pass')
        self.assertEqual(self.s.check('GET', '/api/0/projects/company/hr-secret/issues/', ''), 'deny')
        self.assertEqual(self.s.check('GET', '/api/0/projects/company/project-a/keys/', ''), 'deny')
        self.assertEqual(self.s.check('GET', '/api/0/projects/', ''), 'filter')

    def test_issue_by_project(self):
        self.assertEqual(self.s.check('GET', '/api/0/issues/1/', ''), 'pass')
        self.assertEqual(self.s.check('GET', '/api/0/issues/1/events/latest/', ''), 'pass')
        self.assertEqual(self.s.check('GET', '/api/0/issues/2/events/', ''), 'deny')
        self.assertEqual(self.s.check('GET', '/api/0/issues/7/', ''), 404)
        self.s.check('GET', '/api/0/issues/1/tags/', '')
        self.assertEqual(self.calls.count('/api/0/issues/1/'), 1)  # проект issue кэшируется

    def test_org_events_need_allowed_projects(self):
        self.assertEqual(self.s.check('GET', '/api/0/organizations/company/events/', 'project=12&field=count()'), 'pass')
        self.assertEqual(self.s.check('GET', '/api/0/organizations/company/events/', 'project=12&project=99'), 'deny')
        self.assertEqual(self.s.check('GET', '/api/0/organizations/company/events/', 'field=count()'), 'deny')

    def test_writes_denied(self):
        self.assertEqual(self.s.check('PUT', '/api/0/issues/1/', ''), 'deny')
        self.assertEqual(self.s.check('DELETE', '/api/0/projects/company/project-a/', ''), 'deny')
        self.assertEqual(self.s.check('GET', '/api/0/organizations/company/members/', ''), 'deny')
        self.assertEqual(self.s.check('POST', '/api/12/envelope/', ''), 'deny')  # по умолчанию выключено

    def test_envelope_when_enabled(self):
        mac.ENVELOPE = True
        try:
            self.assertEqual(self.s.check('POST', '/api/12/envelope/', ''), 'envelope')
            self.assertEqual(self.s.check('POST', '/api/99/envelope/', ''), 'deny')
        finally:
            mac.ENVELOPE = False


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
    def test_get_passes(self):
        f = Fake((200, b'{"status":"success"}'))
        st, body, src = srv.Gateway(f).handle('GET', '/grafana/prod/loki/query?query=x', b'', '')
        self.assertEqual((st, src), (200, 'upstream'))
        self.assertEqual(f.seen, [('GET', 'http://127.0.0.1:18448/grafana/prod/loki/query?query=x')])

    def test_writes_and_unknown_denied(self):
        g = srv.Gateway(Fake())
        for m, p in [('POST', '/grafana/prod/loki/query'), ('DELETE', '/sentry/api/0/issues/1/'),
                     ('GET', '/other'), ('GET', '/grafana/prod/%2e%2e/x'), ('POST', '/sentry/api/0/issues/1/')]:
            self.assertEqual(g.handle(m, p, b'', '')[0], 403, (m, p))

    def test_envelope_forwarded_to_mac(self):
        f = Fake((403, b'{"error":"READ_ONLY_OR_FOREIGN_PROJECT"}'))
        self.assertEqual(srv.Gateway(f).handle('POST', '/sentry/api/12/envelope/', b'{}', 'application/x-sentry-envelope')[0], 403)

    def test_bridge_down(self):
        st, body, src = srv.Gateway(Fake(urllib.error.URLError('refused'))).handle('GET', '/sentry/api/0/projects/', b'', '')
        self.assertEqual((st, src, json.loads(body)['error']), (503, 'error', 'OBS_UNAVAILABLE'))

    def test_upstream_errors_as_is(self):
        st, body, src = srv.Gateway(Fake((400, b'{"error":"parse"}'))).handle('GET', '/grafana/prod/loki/query?query=%7B', b'', '')
        self.assertEqual((st, body), (400, b'{"error":"parse"}'))


if __name__ == '__main__':
    unittest.main()
